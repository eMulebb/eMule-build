#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Action,
    [string]$EmulebbBaseUrl,
    [string]$EmulebbApiKey,
    [string]$ProwlarrUrl,
    [string]$ProwlarrApiKey,
    [string]$IndexerName = 'eMuleBB',
    [string]$AppProfileName = 'eMuleBB Suite',
    [switch]$NoRetry
)

$ErrorActionPreference = 'Stop'

function Normalize-ArgumentValue {
    param([string]$Value)
    if ($null -eq $Value) {
        return ''
    }
    $normalized = $Value.Trim()
    while ($normalized.Length -ge 2) {
        $first = $normalized[0]
        $last = $normalized[$normalized.Length - 1]
        if (($first -eq "'" -and $last -eq "'") -or ($first -eq '"' -and $last -eq '"')) {
            $normalized = $normalized.Substring(1, $normalized.Length - 2).Trim()
            continue
        }
        break
    }
    return $normalized
}

function Normalize-HttpBaseUrl {
    param([string]$Value, [string]$Name)
    $normalized = (Normalize-ArgumentValue -Value $Value).TrimEnd('/')
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        throw "$Name is required."
    }

    $uri = $null
    if (-not [Uri]::TryCreate($normalized, [UriKind]::Absolute, [ref]$uri)) {
        throw "$Name must be an absolute HTTP or HTTPS URL, not '$Value'."
    }
    if ($uri.Scheme -ne 'http' -and $uri.Scheme -ne 'https') {
        throw "$Name must use http or https, not '$($uri.Scheme)'."
    }
    if (-not [string]::IsNullOrEmpty($uri.Query) -or -not [string]::IsNullOrEmpty($uri.Fragment)) {
        throw "$Name must be a base URL without query or fragment, not '$Value'."
    }
    return $normalized
}

function Read-RequiredValue {
    param([string]$Prompt, [string]$Value)
    while ([string]::IsNullOrWhiteSpace($Value)) {
        $Value = Read-Host $Prompt
    }
    return Normalize-ArgumentValue -Value $Value
}

function Read-ActionValue {
    param([string]$Value)
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        $normalized = $Value.Trim().ToLowerInvariant()
        if ($normalized -eq 'register' -or $normalized -eq 'r') { return 'Register' }
        if ($normalized -eq 'unregister' -or $normalized -eq 'u') { return 'Unregister' }
        throw "Action must be Register or Unregister, not '$Value'."
    }
    while ($true) {
        $answer = Read-Host 'Action [R]egister/[U]nregister (default Register)'
        if ([string]::IsNullOrWhiteSpace($answer)) { return 'Register' }
        $normalized = $answer.Trim().ToLowerInvariant()
        if ($normalized.StartsWith('r')) { return 'Register' }
        if ($normalized.StartsWith('u')) { return 'Unregister' }
        Write-Host 'Enter R to register or U to unregister.' -ForegroundColor Yellow
    }
}

function Read-SecretValue {
    param([string]$Prompt, [string]$Value)
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return Normalize-ArgumentValue -Value $Value
    }
    return Normalize-ArgumentValue -Value (Read-Host $Prompt)
}

function Read-RequiredSecretValue {
    param([string]$Prompt, [string]$Value, [string]$Name)
    $secret = Read-SecretValue -Prompt $Prompt -Value $Value
    while ([string]::IsNullOrWhiteSpace($secret)) {
        Write-Host "$Name is required." -ForegroundColor Yellow
        $secret = Read-SecretValue -Prompt $Prompt -Value ''
    }
    return Normalize-ArgumentValue -Value $secret
}

function Invoke-JsonApi {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Path,
        [string]$Method = 'GET',
        $Body = $null
    )
    $headers = @{ 'X-Api-Key' = $ApiKey }
    $uri = (Normalize-HttpBaseUrl -Value $BaseUrl -Name 'BaseUrl') + $Path
    try {
        if ($null -eq $Body) {
            return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -TimeoutSec 90 -ErrorAction Stop
        }
        $json = $Body | ConvertTo-Json -Depth 20
        return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -Body $json -ContentType 'application/json; charset=utf-8' -TimeoutSec 90 -ErrorAction Stop
    } catch {
        $statusCode = Get-HttpStatusCode -Exception $_.Exception
        if ($statusCode -eq 401 -or $statusCode -eq 403) {
            throw "Prowlarr API key was rejected by $uri. Copy the API key from Settings > General in the Prowlarr web UI, then rerun this script."
        }
        throw
    }
}

function Get-HttpStatusCode {
    param($Exception)
    if ($null -eq $Exception -or $null -eq $Exception.Response) {
        return 0
    }
    try {
        return [int]$Exception.Response.StatusCode
    } catch {
        return 0
    }
}

function Get-HttpErrorDetail {
    param($Exception)
    if ($null -eq $Exception -or $null -eq $Exception.Response) {
        return ''
    }
    $response = $Exception.Response
    $status = Get-HttpStatusCode -Exception $Exception
    $statusText = if ($status -gt 0) { "HTTP $status" } else { 'HTTP request failed' }
    try {
        if (-not [string]::IsNullOrWhiteSpace([string]$response.StatusDescription)) {
            $statusText = "$statusText $($response.StatusDescription)"
        }
    } catch {
    }
    $detail = ''
    try {
        $stream = $response.GetResponseStream()
        if ($null -ne $stream) {
            $reader = New-Object IO.StreamReader($stream)
            try {
                $detail = $reader.ReadToEnd()
            } finally {
                $reader.Dispose()
            }
        }
    } catch {
    }
    $detail = ([string]$detail -replace '\s+', ' ').Trim()
    if ($detail.Length -gt 1200) {
        $detail = $detail.Substring(0, 1200) + '...'
    }
    if ([string]::IsNullOrWhiteSpace($detail)) {
        return $statusText
    }
    return "$statusText`: $detail"
}

function Get-ExceptionMessage {
    param($Exception)
    $detail = Get-HttpErrorDetail -Exception $Exception
    if (-not [string]::IsNullOrWhiteSpace($detail)) {
        return $detail
    }
    return $Exception.Message
}

function Copy-JsonObject {
    param($Value)
    return ($Value | ConvertTo-Json -Depth 20 | ConvertFrom-Json)
}

function Set-ObjectProperty {
    param($Target, [string]$Name, $Value)
    if ($null -ne $Target.PSObject.Properties[$Name]) {
        $Target.$Name = $Value
    } else {
        $Target | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
}

function Set-ProviderField {
    param($Provider, [string]$Name, $Value, [switch]$Optional)
    foreach ($field in @($Provider.fields)) {
        if ($field.name -eq $Name) {
            if ($field -is [System.Collections.IDictionary]) {
                $field['value'] = $Value
            } elseif ($null -ne $field.PSObject.Properties['value']) {
                $field.value = $Value
            } else {
                $field | Add-Member -NotePropertyName 'value' -NotePropertyValue $Value -Force
            }
            return $true
        }
    }
    if ($Optional) {
        return $false
    }
    throw "Provider payload is missing field: $Name"
}

function Set-LocalCertificateValidation {
    param([string]$BaseUrl, [string]$ApiKey)
    $hostConfig = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/config/host'
    if ($null -eq $hostConfig) {
        throw 'Prowlarr host config did not return a response.'
    }
    if ([string]$hostConfig.certificateValidation -eq 'disabledForLocalAddresses') {
        return $hostConfig
    }
    Set-ObjectProperty -Target $hostConfig -Name 'certificateValidation' -Value 'disabledForLocalAddresses'
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/config/host' -Method 'PUT' -Body $hostConfig
}

function Get-GenericTorznabSchema {
    param([string]$BaseUrl, [string]$ApiKey)
    $schemas = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/indexer/schema'
    foreach ($schema in @($schemas)) {
        if ($schema.implementation -eq 'Torznab' -and $schema.name -eq 'Generic Torznab') {
            return $schema
        }
    }
    throw 'Prowlarr did not expose the Generic Torznab indexer schema.'
}

function Get-ExistingIndexer {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Name)
    $indexers = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/indexer'
    foreach ($indexer in @($indexers)) {
        if ($indexer.name -eq $Name) {
            return $indexer
        }
    }
    return $null
}

function Get-ExistingAppProfile {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Name)
    $profiles = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/appprofile'
    foreach ($profile in @($profiles)) {
        if ($profile.name -eq $Name) {
            return $profile
        }
    }
    return $null
}

function Save-AppProfile {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Name)
    $existing = Get-ExistingAppProfile -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name
    if ($null -ne $existing) {
        $payload = $existing
    } else {
        $payload = [pscustomobject]@{}
    }
    Set-ObjectProperty -Target $payload -Name 'name' -Value $Name
    Set-ObjectProperty -Target $payload -Name 'enableRss' -Value $true
    Set-ObjectProperty -Target $payload -Name 'enableAutomaticSearch' -Value $true
    Set-ObjectProperty -Target $payload -Name 'enableInteractiveSearch' -Value $true
    Set-ObjectProperty -Target $payload -Name 'minimumSeeders' -Value 1
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v1/appprofile/{0}' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/appprofile' -Method 'POST' -Body $payload
}

function Save-Indexer {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Name,
        [string]$TorznabBaseUrl,
        [string]$TorznabApiKey,
        [int]$AppProfileId
    )

    if ($AppProfileId -le 0) {
        throw 'AppProfileId must be a positive Prowlarr app profile id.'
    }
    $existing = Get-ExistingIndexer -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name
    if ($null -ne $existing) {
        $payload = $existing
    } else {
        $payload = Get-GenericTorznabSchema -BaseUrl $BaseUrl -ApiKey $ApiKey
    }

    Set-ObjectProperty -Target $payload -Name 'name' -Value $Name
    Set-ObjectProperty -Target $payload -Name 'enable' -Value $true
    Set-ObjectProperty -Target $payload -Name 'appProfileId' -Value $AppProfileId
    $priority = [int]((Get-ObjectPropertyValue -Target $payload -Name 'priority' -Default 0) -as [int])
    if ($priority -le 0) { $priority = 25 }
    Set-ObjectProperty -Target $payload -Name 'priority' -Value $priority
    Set-ObjectProperty -Target $payload -Name 'implementation' -Value 'Torznab'
    Set-ObjectProperty -Target $payload -Name 'implementationName' -Value 'Torznab'
    Set-ObjectProperty -Target $payload -Name 'configContract' -Value 'TorznabSettings'
    $normalizedTorznabBaseUrl = Normalize-HttpBaseUrl -Value $TorznabBaseUrl -Name 'TorznabBaseUrl'
    [void](Set-ProviderField -Provider $payload -Name 'baseUrl' -Value $normalizedTorznabBaseUrl)
    [void](Set-ProviderField -Provider $payload -Name 'apiPath' -Value '/api')
    [void](Set-ProviderField -Provider $payload -Name 'apiKey' -Value $TorznabApiKey)
    [void](Set-ProviderField -Provider $payload -Name 'torrentBaseSettings.preferMagnetUrl' -Value $true)
    if ($normalizedTorznabBaseUrl.StartsWith('https://', [StringComparison]::OrdinalIgnoreCase)) {
        [void](Set-LocalCertificateValidation -BaseUrl $BaseUrl -ApiKey $ApiKey)
        [void](Set-ProviderField -Provider $payload -Name 'certificateValidation' -Value 1 -Optional)
    }

    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v1/indexer/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    try {
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/indexer?forceSave=true' -Method 'POST' -Body $payload
    } catch {
        $statusCode = Get-HttpStatusCode -Exception $_.Exception
        if ($statusCode -lt 400 -or $statusCode -ge 500) {
            throw
        }
        $disabledPayload = Copy-JsonObject -Value $payload
        Set-ObjectProperty -Target $disabledPayload -Name 'enable' -Value $false
        $created = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/indexer?forceSave=true' -Method 'POST' -Body $disabledPayload
        if ($null -eq $created -or -not $created.id) {
            throw 'Prowlarr did not return an id for the disabled indexer fallback.'
        }
        Set-ObjectProperty -Target $payload -Name 'id' -Value ([int]$created.id)
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v1/indexer/{0}?forceSave=true' -f [int]$created.id)) -Method 'PUT' -Body $payload
    }
}

function Remove-Indexer {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Name
    )
    $existing = Get-ExistingIndexer -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name
    if ($null -eq $existing -or -not $existing.id) {
        Write-Host ('Prowlarr indexer "{0}" is not registered.' -f $Name) -ForegroundColor Yellow
        return
    }
    [void](Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v1/indexer/{0}' -f [int]$existing.id)) -Method 'DELETE')
    Write-Host ('Unregistered Prowlarr indexer "{0}" with id {1}.' -f $Name, $existing.id) -ForegroundColor Green
}

function Confirm-Retry {
    param([string]$Message, [switch]$NoRetry)
    Write-Host $Message -ForegroundColor Red
    if ($NoRetry) {
        return $false
    }
    $answer = Read-Host 'Retry? [Y/n]'
    return [string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLowerInvariant().StartsWith('y')
}

$Action = Read-ActionValue -Value $Action
Write-Host ('eMuleBB Prowlarr Integration - {0}' -f $Action) -ForegroundColor Cyan
do {
    try {
        $ProwlarrUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'Prowlarr URL (example http://LAN-IP:9696)' -Value $ProwlarrUrl) -Name 'ProwlarrUrl'
        $ProwlarrApiKey = Read-RequiredSecretValue -Prompt 'Prowlarr API key' -Value $ProwlarrApiKey -Name 'ProwlarrApiKey'
        if ($Action -eq 'Unregister') {
            Remove-Indexer -BaseUrl $ProwlarrUrl -ApiKey $ProwlarrApiKey -Name $IndexerName
            return
        }
        $EmulebbBaseUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'eMuleBB base URL (example http://LAN-IP:4711)' -Value $EmulebbBaseUrl) -Name 'EmulebbBaseUrl'
        $EmulebbApiKey = Read-RequiredSecretValue -Prompt 'eMuleBB API key' -Value $EmulebbApiKey -Name 'EmulebbApiKey'
        $appProfile = Save-AppProfile -BaseUrl $ProwlarrUrl -ApiKey $ProwlarrApiKey -Name $AppProfileName
        if ($null -eq $appProfile -or -not $appProfile.id) {
            throw 'Prowlarr did not return an id for the eMuleBB app profile.'
        }
        $saved = Save-Indexer -BaseUrl $ProwlarrUrl -ApiKey $ProwlarrApiKey -Name $IndexerName -TorznabBaseUrl ($EmulebbBaseUrl.TrimEnd('/') + '/indexer/emulebb') -TorznabApiKey $EmulebbApiKey -AppProfileId ([int]$appProfile.id)
        Write-Host ('Registered Prowlarr indexer "{0}" with id {1}.' -f $saved.name, $saved.id) -ForegroundColor Green
        return
    } catch {
        $message = ('{0} failed: {1}' -f $Action, (Get-ExceptionMessage -Exception $_.Exception))
        if ($NoRetry) {
            Write-Host $message -ForegroundColor Red
            throw
        }
        if (-not (Confirm-Retry -Message $message)) {
            throw "$Action cancelled by user."
        }
        $ProwlarrUrl = ''
        $ProwlarrApiKey = ''
        $EmulebbBaseUrl = ''
        $EmulebbApiKey = ''
    }
} while ($true)
