#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Action,
    [string]$EmulebbBaseUrl,
    [string]$EmulebbApiKey,
    [string]$ProwlarrUrl,
    [string]$ProwlarrApiKey,
    [string]$RadarrUrl,
    [string]$RadarrApiKey,
    [string]$SonarrUrl,
    [string]$SonarrApiKey,
    [string]$DownloadClientName = 'eMuleBB',
    [switch]$NoRetry
)

$ErrorActionPreference = 'Stop'

function Read-OptionalValue {
    param([string]$Prompt, [string]$Value)
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return $Value.Trim()
    }
    return (Read-Host $Prompt).Trim()
}

function Read-RequiredValue {
    param([string]$Prompt, [string]$Value)
    while ([string]::IsNullOrWhiteSpace($Value)) {
        $Value = Read-Host $Prompt
    }
    return $Value.Trim()
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
        return $Value.Trim()
    }
    $secure = Read-Host $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
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
    $uri = $BaseUrl.TrimEnd('/') + $Path
    if ($null -eq $Body) {
        return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -TimeoutSec 90 -ErrorAction Stop
    }
    $json = $Body | ConvertTo-Json -Depth 20
    return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -Body $json -ContentType 'application/json; charset=utf-8' -TimeoutSec 90 -ErrorAction Stop
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

function Invoke-JsonApiWithRetry {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Path,
        [string]$Method = 'GET',
        $Body = $null,
        [int]$Attempts = 5
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path $Path -Method $Method -Body $Body
        } catch {
            $statusCode = Get-HttpStatusCode -Exception $_.Exception
            if ($statusCode -eq 404 -and $Method -eq 'DELETE') {
                return $null
            }
            if ($attempt -lt $Attempts) {
                Start-Sleep -Seconds 2
                continue
            }
            throw
        }
    }
}

function Invoke-DeleteJsonApiWithRetry {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Path
    )
    [void](Invoke-JsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path $Path -Method 'DELETE')
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
    if ($Optional) { return $false }
    throw "Provider payload is missing field: $Name"
}

function Get-QbitSchema {
    param([string]$BaseUrl, [string]$ApiKey)
    $schemas = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v3/downloadclient/schema'
    foreach ($schema in @($schemas)) {
        if ($schema.implementation -eq 'QBittorrent') {
            return $schema
        }
    }
    throw 'Arr did not expose the qBittorrent download-client schema.'
}

function Get-ExistingDownloadClient {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Name)
    $clients = Invoke-JsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v3/downloadclient'
    foreach ($client in @($clients)) {
        if ($client.name -eq $Name) {
            return $client
        }
    }
    return $null
}

function Save-QbitClient {
    param(
        [string]$Kind,
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$EmuleBaseUrl,
        [string]$EmuleApiKey,
        [string]$Name
    )
    $uri = [Uri]$EmuleBaseUrl
    $existing = Get-ExistingDownloadClient -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name
    if ($null -ne $existing) {
        $payload = $existing
    } else {
        $payload = Get-QbitSchema -BaseUrl $BaseUrl -ApiKey $ApiKey
    }
    Set-ObjectProperty -Target $payload -Name 'name' -Value $Name
    Set-ObjectProperty -Target $payload -Name 'enable' -Value $true
    Set-ObjectProperty -Target $payload -Name 'priority' -Value 1
    Set-ObjectProperty -Target $payload -Name 'implementation' -Value 'QBittorrent'
    Set-ObjectProperty -Target $payload -Name 'implementationName' -Value 'qBittorrent'
    Set-ObjectProperty -Target $payload -Name 'configContract' -Value 'QBittorrentSettings'
    Set-ObjectProperty -Target $payload -Name 'protocol' -Value 'torrent'
    Set-ObjectProperty -Target $payload -Name 'removeCompletedDownloads' -Value $false
    Set-ObjectProperty -Target $payload -Name 'removeFailedDownloads' -Value $false
    $categoryField = if ($Kind -eq 'radarr') { 'movieCategory' } else { 'tvCategory' }
    $category = if ($Kind -eq 'radarr') { 'emulebb-radarr' } else { 'emulebb-sonarr' }
    [void](Set-ProviderField -Provider $payload -Name 'host' -Value $uri.Host)
    [void](Set-ProviderField -Provider $payload -Name 'port' -Value $uri.Port)
    [void](Set-ProviderField -Provider $payload -Name 'useSsl' -Value ($uri.Scheme -eq 'https'))
    [void](Set-ProviderField -Provider $payload -Name 'urlBase' -Value '')
    [void](Set-ProviderField -Provider $payload -Name 'username' -Value 'emule')
    [void](Set-ProviderField -Provider $payload -Name 'password' -Value $EmuleApiKey)
    [void](Set-ProviderField -Provider $payload -Name $categoryField -Value $category)
    [void](Set-ProviderField -Provider $payload -Name 'initialState' -Value 0)
    if ($uri.Scheme -eq 'https') {
        [void](Set-ProviderField -Provider $payload -Name 'certificateValidation' -Value 1 -Optional)
    }
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v3/downloadclient/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v3/downloadclient?forceSave=true' -Method 'POST' -Body $payload
}

function Remove-QbitClient {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Name
    )
    $existing = Get-ExistingDownloadClient -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name
    if ($null -eq $existing -or -not $existing.id) {
        Write-Host ('Download client "{0}" is not registered.' -f $Name) -ForegroundColor Yellow
        return
    }
    Invoke-DeleteJsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v3/downloadclient/{0}' -f [int]$existing.id))
    Write-Host ('Unregistered download client "{0}" with id {1}.' -f $Name, $existing.id) -ForegroundColor Green
}

function Invoke-ProwlarrSync {
    param([string]$BaseUrl, [string]$ApiKey)
    $command = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/command' -Method 'POST' -Body @{ name = 'ApplicationIndexerSync'; forceSync = $true }
    if ($null -eq $command -or -not $command.id) {
        Write-Host 'Prowlarr application sync submitted without a command id.' -ForegroundColor Green
        return
    }
    $commandId = [int]$command.id
    $deadline = [DateTime]::UtcNow.AddSeconds(120)
    do {
        Start-Sleep -Seconds 2
        $status = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v1/command/{0}' -f $commandId))
        $state = ([string]$status.status).ToLowerInvariant()
        if ($state -eq 'completed') {
            Write-Host ('Prowlarr application sync completed: {0}' -f $commandId) -ForegroundColor Green
            return
        }
        if ($state -eq 'failed') {
            throw ('Prowlarr application sync failed: {0}' -f $commandId)
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw ('Prowlarr application sync timed out: {0}' -f $commandId)
}

function Get-ProwlarrApplicationSchema {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Kind)
    $implementation = if ($Kind -eq 'radarr') { 'Radarr' } else { 'Sonarr' }
    $schemas = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/applications/schema'
    foreach ($schema in @($schemas)) {
        if ($schema.implementation -eq $implementation) {
            return $schema
        }
    }
    throw "Prowlarr did not expose the $implementation application schema."
}

function Get-ProviderFieldValue {
    param($Provider, [string]$Name)
    foreach ($field in @($Provider.fields)) {
        if ($field.name -eq $Name) {
            return $field.value
        }
    }
    return $null
}

function Get-ExistingProwlarrApplication {
    param([string]$BaseUrl, [string]$ApiKey, [string]$ArrUrl)
    $target = $ArrUrl.TrimEnd('/').ToLowerInvariant()
    $applications = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/applications'
    foreach ($application in @($applications)) {
        $baseUrl = [string](Get-ProviderFieldValue -Provider $application -Name 'baseUrl')
        if ($baseUrl.TrimEnd('/').ToLowerInvariant() -eq $target) {
            return $application
        }
    }
    return $null
}

function Save-ProwlarrApplication {
    param(
        [string]$ProwlarrBaseUrl,
        [string]$ProwlarrKey,
        [string]$Kind,
        [string]$ArrUrl,
        [string]$ArrKey
    )
    $name = if ($Kind -eq 'radarr') { 'Radarr' } else { 'Sonarr' }
    $existing = Get-ExistingProwlarrApplication -BaseUrl $ProwlarrBaseUrl -ApiKey $ProwlarrKey -ArrUrl $ArrUrl
    if ($null -ne $existing) {
        $payload = $existing
    } else {
        $payload = Get-ProwlarrApplicationSchema -BaseUrl $ProwlarrBaseUrl -ApiKey $ProwlarrKey -Kind $Kind
    }
    Set-ObjectProperty -Target $payload -Name 'name' -Value $name
    Set-ObjectProperty -Target $payload -Name 'enable' -Value $true
    Set-ObjectProperty -Target $payload -Name 'implementation' -Value $name
    Set-ObjectProperty -Target $payload -Name 'implementationName' -Value $name
    [void](Set-ProviderField -Provider $payload -Name 'baseUrl' -Value ($ArrUrl.TrimEnd('/')))
    [void](Set-ProviderField -Provider $payload -Name 'apiKey' -Value $ArrKey)
    [void](Set-ProviderField -Provider $payload -Name 'prowlarrUrl' -Value ($ProwlarrBaseUrl.TrimEnd('/')) -Optional)
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $ProwlarrBaseUrl -ApiKey $ProwlarrKey -Path (('/api/v1/applications/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $ProwlarrBaseUrl -ApiKey $ProwlarrKey -Path '/api/v1/applications?forceSave=true' -Method 'POST' -Body $payload
}

function Run-TargetWithRetry {
    param([string]$Name, [scriptblock]$Operation, [switch]$NoRetry)
    do {
        try {
            & $Operation
            return
        } catch {
            Write-Host ('{0} failed: {1}' -f $Name, $_.Exception.Message) -ForegroundColor Red
            if ($NoRetry) {
                throw
            }
            $answer = Read-Host ('Retry {0}? [Y/n]' -f $Name)
            if (-not ([string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLowerInvariant().StartsWith('y'))) {
                return
            }
        }
    } while ($true)
}

$Action = Read-ActionValue -Value $Action
Write-Host ('eMuleBB Radarr/Sonarr Integration - {0}' -f $Action) -ForegroundColor Cyan
if ($Action -eq 'Register') {
    $EmulebbBaseUrl = Read-RequiredValue -Prompt 'eMuleBB base URL (example http://127.0.0.1:4711)' -Value $EmulebbBaseUrl
    $EmulebbApiKey = Read-SecretValue -Prompt 'eMuleBB API key' -Value $EmulebbApiKey
}
$ProwlarrUrl = Read-OptionalValue -Prompt 'Prowlarr URL for application sync (blank to skip)' -Value $ProwlarrUrl
if ($ProwlarrUrl) {
    $ProwlarrApiKey = Read-SecretValue -Prompt 'Prowlarr API key' -Value $ProwlarrApiKey
}

$RadarrUrl = Read-OptionalValue -Prompt 'Radarr URL for eMuleBB download client (blank to skip)' -Value $RadarrUrl
if ($RadarrUrl) {
    $RadarrApiKey = Read-SecretValue -Prompt 'Radarr API key' -Value $RadarrApiKey
    if ($Action -eq 'Register' -and $ProwlarrUrl) {
        Run-TargetWithRetry -Name 'Prowlarr Radarr application registration' -NoRetry:$NoRetry -Operation {
            $saved = Save-ProwlarrApplication -ProwlarrBaseUrl $ProwlarrUrl -ProwlarrKey $ProwlarrApiKey -Kind 'radarr' -ArrUrl $RadarrUrl -ArrKey $RadarrApiKey
            Write-Host ('Prowlarr Radarr application saved with id {0}.' -f $saved.id) -ForegroundColor Green
        }
    }
    Run-TargetWithRetry -Name ('Radarr download client {0}' -f $Action.ToLowerInvariant()) -NoRetry:$NoRetry -Operation {
        if ($Action -eq 'Unregister') {
            Remove-QbitClient -BaseUrl $RadarrUrl -ApiKey $RadarrApiKey -Name $DownloadClientName
        } else {
            $saved = Save-QbitClient -Kind 'radarr' -BaseUrl $RadarrUrl -ApiKey $RadarrApiKey -EmuleBaseUrl $EmulebbBaseUrl -EmuleApiKey $EmulebbApiKey -Name $DownloadClientName
            Write-Host ('Radarr download client saved with id {0}.' -f $saved.id) -ForegroundColor Green
        }
    }
}

$SonarrUrl = Read-OptionalValue -Prompt 'Sonarr URL for eMuleBB download client (blank to skip)' -Value $SonarrUrl
if ($SonarrUrl) {
    $SonarrApiKey = Read-SecretValue -Prompt 'Sonarr API key' -Value $SonarrApiKey
    if ($Action -eq 'Register' -and $ProwlarrUrl) {
        Run-TargetWithRetry -Name 'Prowlarr Sonarr application registration' -NoRetry:$NoRetry -Operation {
            $saved = Save-ProwlarrApplication -ProwlarrBaseUrl $ProwlarrUrl -ProwlarrKey $ProwlarrApiKey -Kind 'sonarr' -ArrUrl $SonarrUrl -ArrKey $SonarrApiKey
            Write-Host ('Prowlarr Sonarr application saved with id {0}.' -f $saved.id) -ForegroundColor Green
        }
    }
    Run-TargetWithRetry -Name ('Sonarr download client {0}' -f $Action.ToLowerInvariant()) -NoRetry:$NoRetry -Operation {
        if ($Action -eq 'Unregister') {
            Remove-QbitClient -BaseUrl $SonarrUrl -ApiKey $SonarrApiKey -Name $DownloadClientName
        } else {
            $saved = Save-QbitClient -Kind 'sonarr' -BaseUrl $SonarrUrl -ApiKey $SonarrApiKey -EmuleBaseUrl $EmulebbBaseUrl -EmuleApiKey $EmulebbApiKey -Name $DownloadClientName
            Write-Host ('Sonarr download client saved with id {0}.' -f $saved.id) -ForegroundColor Green
        }
    }
}

if ($ProwlarrUrl) {
    Run-TargetWithRetry -Name 'Prowlarr application sync' -NoRetry:$NoRetry -Operation {
        Invoke-ProwlarrSync -BaseUrl $ProwlarrUrl -ApiKey $ProwlarrApiKey
    }
}

Write-Host ('eMuleBB integration {0} finished.' -f $Action.ToLowerInvariant()) -ForegroundColor Green
exit 0
