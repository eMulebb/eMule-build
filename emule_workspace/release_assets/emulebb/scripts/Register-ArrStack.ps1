#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Action,
    [string]$Target,
    [string]$EmulebbBaseUrl,
    [string]$EmulebbApiKey,
    [string]$EmulebbCategoryPath,
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

function Read-OptionalValue {
    param([string]$Prompt, [string]$Value)
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return Normalize-ArgumentValue -Value $Value
    }
    return Normalize-ArgumentValue -Value (Read-Host $Prompt)
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

function Read-TargetValue {
    param([string]$Value)
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        $normalized = $Value.Trim().ToLowerInvariant()
        if ($normalized -eq 'radarr' -or $normalized -eq 'r') { return 'Radarr' }
        if ($normalized -eq 'sonarr' -or $normalized -eq 's') { return 'Sonarr' }
        throw "Target must be Radarr or Sonarr, not '$Value'."
    }
    while ($true) {
        $answer = Read-Host 'Target [R]adarr/[S]onarr'
        $normalized = $answer.Trim().ToLowerInvariant()
        if ($normalized.StartsWith('r')) { return 'Radarr' }
        if ($normalized.StartsWith('s')) { return 'Sonarr' }
        Write-Host 'Enter R for Radarr or S for Sonarr.' -ForegroundColor Yellow
    }
}

function Read-SecretValue {
    param([string]$Prompt, [string]$Value)
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return Normalize-ArgumentValue -Value $Value
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
    $uri = (Normalize-HttpBaseUrl -Value $BaseUrl -Name 'BaseUrl') + $Path
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

function Set-LocalCertificateValidation {
    param([string]$BaseUrl, [string]$ApiKey)
    $hostConfig = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v3/config/host'
    if ($null -eq $hostConfig) {
        throw 'Arr host config did not return a response.'
    }
    if ([string]$hostConfig.certificateValidation -eq 'disabledForLocalAddresses') {
        return $hostConfig
    }
    Set-ObjectProperty -Target $hostConfig -Name 'certificateValidation' -Value 'disabledForLocalAddresses'
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v3/config/host' -Method 'PUT' -Body $hostConfig
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
    $normalizedEmuleBaseUrl = Normalize-HttpBaseUrl -Value $EmuleBaseUrl -Name 'EmuleBaseUrl'
    $uri = [Uri]$normalizedEmuleBaseUrl
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
    $category = (Get-ArrCategoryInfo -Kind $Kind).Name
    $urlBase = if ($uri.AbsolutePath -and $uri.AbsolutePath -ne '/') { $uri.AbsolutePath.TrimEnd('/') } else { '' }
    [void](Set-ProviderField -Provider $payload -Name 'host' -Value $uri.Host)
    [void](Set-ProviderField -Provider $payload -Name 'port' -Value $uri.Port)
    [void](Set-ProviderField -Provider $payload -Name 'useSsl' -Value ($uri.Scheme -eq 'https'))
    [void](Set-ProviderField -Provider $payload -Name 'urlBase' -Value $urlBase)
    [void](Set-ProviderField -Provider $payload -Name 'username' -Value 'emule')
    [void](Set-ProviderField -Provider $payload -Name 'password' -Value $EmuleApiKey)
    [void](Set-ProviderField -Provider $payload -Name $categoryField -Value $category)
    [void](Set-ProviderField -Provider $payload -Name 'initialState' -Value 0)
    if ($uri.Scheme -eq 'https') {
        [void](Set-LocalCertificateValidation -BaseUrl $BaseUrl -ApiKey $ApiKey)
        [void](Set-ProviderField -Provider $payload -Name 'certificateValidation' -Value 1 -Optional)
    }
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v3/downloadclient/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v3/downloadclient?forceSave=true' -Method 'POST' -Body $payload
}

function Get-ArrCategoryName {
    param([string]$Kind)
    return (Get-ArrCategoryInfo -Kind $Kind).Name
}

function Get-ArrCategoryRelativePath {
    param([string]$Kind)
    return (Get-ArrCategoryInfo -Kind $Kind).RelativePath
}

function Get-ArrCategoryInfo {
    param([string]$Kind)
    if ($Kind -eq 'radarr') {
        return [pscustomobject]@{ Name = 'emulebb-radarr'; RelativePath = 'downloads\radarr' }
    }
    return [pscustomobject]@{ Name = 'emulebb-sonarr'; RelativePath = 'downloads\sonarr' }
}

function Normalize-OptionalCategoryPath {
    param([string]$Path)
    return (Normalize-ArgumentValue -Value $Path)
}

function Normalize-ComparablePath {
    param([string]$Path)
    return (Normalize-ArgumentValue -Value $Path).TrimEnd([char[]]@('\', '/'))
}

function Find-EmuleCategory {
    param($CategoriesResponse, [string]$Name)
    $items = @()
    if ($null -eq $CategoriesResponse) {
        return $null
    }
    if ($CategoriesResponse.PSObject.Properties['data'] -and $CategoriesResponse.data.PSObject.Properties['items']) {
        $items = @($CategoriesResponse.data.items)
    } else {
        $items = @($CategoriesResponse)
    }
    foreach ($item in $items) {
        if ($null -ne $item.PSObject.Properties['name'] -and [string]::Equals([string]$item.name, $Name, [StringComparison]::OrdinalIgnoreCase)) {
            return $item
        }
    }
    return $null
}

function Test-EmuleCategoryExists {
    param($CategoriesResponse, [string]$Name)
    return $null -ne (Find-EmuleCategory -CategoriesResponse $CategoriesResponse -Name $Name)
}

function Ensure-EmuleCategory {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Name, [string]$Path)
    $categories = Invoke-JsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/categories'
    $existing = Find-EmuleCategory -CategoriesResponse $categories -Name $Name
    $normalizedPath = Normalize-OptionalCategoryPath -Path $Path
    if ($null -ne $existing) {
        if (-not [string]::IsNullOrWhiteSpace($normalizedPath) -and $existing.PSObject.Properties['id']) {
            $currentPath = if ($existing.PSObject.Properties['path']) { [string]$existing.path } else { '' }
            if ((Normalize-ComparablePath -Path $currentPath) -ne (Normalize-ComparablePath -Path $normalizedPath)) {
                [void](Invoke-JsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v1/categories/{0}' -f [int]$existing.id)) -Method 'PATCH' -Body @{
                    path = $normalizedPath
                })
                Write-Host ('Updated eMuleBB category "{0}" path.' -f $Name) -ForegroundColor Green
                return
            }
        }
        Write-Host ('eMuleBB category "{0}" is already configured.' -f $Name) -ForegroundColor Green
        return
    }
    $body = @{
        name = $Name
        comment = 'eMuleBB Arr integration'
    }
    if (-not [string]::IsNullOrWhiteSpace($normalizedPath)) {
        $body['path'] = $normalizedPath
    }
    [void](Invoke-JsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/categories' -Method 'POST' -Body $body)
    Write-Host ('Created eMuleBB category "{0}".' -f $Name) -ForegroundColor Green
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
    $target = (Normalize-HttpBaseUrl -Value $ArrUrl -Name 'ArrUrl').ToLowerInvariant()
    $applications = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/applications'
    foreach ($application in @($applications)) {
        $baseUrl = [string](Get-ProviderFieldValue -Provider $application -Name 'baseUrl')
        if ((Normalize-ArgumentValue -Value $baseUrl).TrimEnd('/').ToLowerInvariant() -eq $target) {
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
    $normalizedProwlarrBaseUrl = Normalize-HttpBaseUrl -Value $ProwlarrBaseUrl -Name 'ProwlarrBaseUrl'
    $normalizedArrUrl = Normalize-HttpBaseUrl -Value $ArrUrl -Name 'ArrUrl'
    $existing = Get-ExistingProwlarrApplication -BaseUrl $normalizedProwlarrBaseUrl -ApiKey $ProwlarrKey -ArrUrl $normalizedArrUrl
    if ($null -ne $existing) {
        $payload = $existing
    } else {
        $payload = Get-ProwlarrApplicationSchema -BaseUrl $normalizedProwlarrBaseUrl -ApiKey $ProwlarrKey -Kind $Kind
    }
    Set-ObjectProperty -Target $payload -Name 'name' -Value $name
    Set-ObjectProperty -Target $payload -Name 'enable' -Value $true
    Set-ObjectProperty -Target $payload -Name 'implementation' -Value $name
    Set-ObjectProperty -Target $payload -Name 'implementationName' -Value $name
    Set-ObjectProperty -Target $payload -Name 'syncLevel' -Value 'fullSync'
    [void](Set-ProviderField -Provider $payload -Name 'baseUrl' -Value $normalizedArrUrl)
    [void](Set-ProviderField -Provider $payload -Name 'apiKey' -Value $ArrKey)
    [void](Set-ProviderField -Provider $payload -Name 'prowlarrUrl' -Value $normalizedProwlarrBaseUrl -Optional)
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $normalizedProwlarrBaseUrl -ApiKey $ProwlarrKey -Path (('/api/v1/applications/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $normalizedProwlarrBaseUrl -ApiKey $ProwlarrKey -Path '/api/v1/applications?forceSave=true' -Method 'POST' -Body $payload
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
$Target = Read-TargetValue -Value $Target
$targetKind = $Target.ToLowerInvariant()
Write-Host ('eMuleBB {0} Integration - {1}' -f $Target, $Action) -ForegroundColor Cyan
if ($Action -eq 'Register') {
    $EmulebbBaseUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'eMuleBB base URL (example http://127.0.0.1:4711)' -Value $EmulebbBaseUrl) -Name 'EmulebbBaseUrl'
    $EmulebbApiKey = Read-SecretValue -Prompt 'eMuleBB API key' -Value $EmulebbApiKey
}
$ProwlarrUrl = Read-OptionalValue -Prompt 'Prowlarr URL for application sync (blank to skip)' -Value $ProwlarrUrl
if ($ProwlarrUrl) {
    $ProwlarrUrl = Normalize-HttpBaseUrl -Value $ProwlarrUrl -Name 'ProwlarrUrl'
    $ProwlarrApiKey = Read-SecretValue -Prompt 'Prowlarr API key' -Value $ProwlarrApiKey
}

$targetUrl = if ($Target -eq 'Radarr') { $RadarrUrl } else { $SonarrUrl }
$targetApiKey = if ($Target -eq 'Radarr') { $RadarrApiKey } else { $SonarrApiKey }
$targetUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt ("$Target URL for eMuleBB download client") -Value $targetUrl) -Name ("${Target}Url")
$targetApiKey = Read-SecretValue -Prompt "$Target API key" -Value $targetApiKey

if ($Action -eq 'Register') {
    $arrCategoryName = Get-ArrCategoryName -Kind $targetKind
    $EmulebbCategoryPath = Normalize-OptionalCategoryPath -Path $EmulebbCategoryPath
    Run-TargetWithRetry -Name 'eMuleBB category registration' -NoRetry:$NoRetry -Operation {
        Ensure-EmuleCategory -BaseUrl $EmulebbBaseUrl -ApiKey $EmulebbApiKey -Name $arrCategoryName -Path $EmulebbCategoryPath
    }
}

if ($Action -eq 'Register' -and $ProwlarrUrl) {
    Run-TargetWithRetry -Name "Prowlarr $Target application registration" -NoRetry:$NoRetry -Operation {
        $saved = Save-ProwlarrApplication -ProwlarrBaseUrl $ProwlarrUrl -ProwlarrKey $ProwlarrApiKey -Kind $targetKind -ArrUrl $targetUrl -ArrKey $targetApiKey
        Write-Host ('Prowlarr {0} application saved with id {1}.' -f $Target, $saved.id) -ForegroundColor Green
    }
}

Run-TargetWithRetry -Name ("$Target download client {0}" -f $Action.ToLowerInvariant()) -NoRetry:$NoRetry -Operation {
    if ($Action -eq 'Unregister') {
        Remove-QbitClient -BaseUrl $targetUrl -ApiKey $targetApiKey -Name $DownloadClientName
    } else {
        $saved = Save-QbitClient -Kind $targetKind -BaseUrl $targetUrl -ApiKey $targetApiKey -EmuleBaseUrl $EmulebbBaseUrl -EmuleApiKey $EmulebbApiKey -Name $DownloadClientName
        Write-Host ('{0} download client saved with id {1}.' -f $Target, $saved.id) -ForegroundColor Green
    }
}

if ($ProwlarrUrl) {
    Run-TargetWithRetry -Name 'Prowlarr application sync' -NoRetry:$NoRetry -Operation {
        Invoke-ProwlarrSync -BaseUrl $ProwlarrUrl -ApiKey $ProwlarrApiKey
    }
}

Write-Host ('eMuleBB {0} integration {1} finished.' -f $Target, $Action.ToLowerInvariant()) -ForegroundColor Green
exit 0
