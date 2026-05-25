#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$EmulebbBaseUrl,
    [string]$EmulebbApiKey,
    [string]$ProwlarrUrl,
    [string]$ProwlarrApiKey,
    [string]$RadarrUrl,
    [string]$RadarrApiKey,
    [string]$SonarrUrl,
    [string]$SonarrApiKey
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
        return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -TimeoutSec 90
    }
    $json = $Body | ConvertTo-Json -Depth 20
    return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -Body $json -ContentType 'application/json; charset=utf-8' -TimeoutSec 90
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
    foreach ($client in @(Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v3/downloadclient')) {
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
        [string]$EmuleApiKey
    )
    $uri = [Uri]$EmuleBaseUrl
    $existing = Get-ExistingDownloadClient -BaseUrl $BaseUrl -ApiKey $ApiKey -Name 'eMuleBB'
    if ($null -ne $existing) {
        $payload = $existing
    } else {
        $payload = Get-QbitSchema -BaseUrl $BaseUrl -ApiKey $ApiKey
    }
    $payload.name = 'eMuleBB'
    $payload.enable = $true
    $payload.priority = 1
    $payload.implementation = 'QBittorrent'
    $payload.implementationName = 'qBittorrent'
    $payload.configContract = 'QBittorrentSettings'
    $payload.protocol = 'torrent'
    $payload.removeCompletedDownloads = $false
    $payload.removeFailedDownloads = $false
    $categoryField = if ($Kind -eq 'radarr') { 'movieCategory' } else { 'tvCategory' }
    $category = if ($Kind -eq 'radarr') { 'emulebb-radarr' } else { 'emulebb-sonarr' }
    Set-ProviderField -Provider $payload -Name 'host' -Value $uri.Host
    Set-ProviderField -Provider $payload -Name 'port' -Value $uri.Port
    Set-ProviderField -Provider $payload -Name 'useSsl' -Value ($uri.Scheme -eq 'https')
    Set-ProviderField -Provider $payload -Name 'urlBase' -Value ''
    Set-ProviderField -Provider $payload -Name 'username' -Value 'emule'
    Set-ProviderField -Provider $payload -Name 'password' -Value $EmuleApiKey
    Set-ProviderField -Provider $payload -Name $categoryField -Value $category
    Set-ProviderField -Provider $payload -Name 'initialState' -Value 0
    if ($uri.Scheme -eq 'https') {
        [void](Set-ProviderField -Provider $payload -Name 'certificateValidation' -Value 1 -Optional)
    }
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v3/downloadclient/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v3/downloadclient?forceSave=true' -Method 'POST' -Body $payload
}

function Invoke-ProwlarrSync {
    param([string]$BaseUrl, [string]$ApiKey)
    $command = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/command' -Method 'POST' -Body @{ name = 'ApplicationIndexerSync'; forceSync = $true }
    Write-Host ('Prowlarr application sync submitted: {0}' -f $command.id) -ForegroundColor Green
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
    foreach ($application in @(Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/applications')) {
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
    $payload.name = $name
    $payload.enable = $true
    $payload.implementation = $name
    $payload.implementationName = $name
    Set-ProviderField -Provider $payload -Name 'baseUrl' -Value ($ArrUrl.TrimEnd('/'))
    Set-ProviderField -Provider $payload -Name 'apiKey' -Value $ArrKey
    [void](Set-ProviderField -Provider $payload -Name 'prowlarrUrl' -Value ($ProwlarrBaseUrl.TrimEnd('/')) -Optional)
    [void](Set-ProviderField -Provider $payload -Name 'syncCategories' -Value @() -Optional)
    [void](Set-ProviderField -Provider $payload -Name 'animeSyncCategories' -Value @() -Optional)
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $ProwlarrBaseUrl -ApiKey $ProwlarrKey -Path (('/api/v1/applications/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $ProwlarrBaseUrl -ApiKey $ProwlarrKey -Path '/api/v1/applications?forceSave=true' -Method 'POST' -Body $payload
}

function Run-TargetWithRetry {
    param([string]$Name, [scriptblock]$Action)
    do {
        try {
            & $Action
            return
        } catch {
            Write-Host ('{0} failed: {1}' -f $Name, $_.Exception.Message) -ForegroundColor Red
            $answer = Read-Host ('Retry {0}? [Y/n]' -f $Name)
            if (-not ([string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLowerInvariant().StartsWith('y'))) {
                return
            }
        }
    } while ($true)
}

Write-Host 'eMuleBB Radarr/Sonarr Integration Registration' -ForegroundColor Cyan
$EmulebbBaseUrl = Read-RequiredValue -Prompt 'eMuleBB base URL (example http://127.0.0.1:4711)' -Value $EmulebbBaseUrl
$EmulebbApiKey = Read-SecretValue -Prompt 'eMuleBB API key' -Value $EmulebbApiKey
$ProwlarrUrl = Read-OptionalValue -Prompt 'Prowlarr URL for application sync (blank to skip)' -Value $ProwlarrUrl
if ($ProwlarrUrl) {
    $ProwlarrApiKey = Read-SecretValue -Prompt 'Prowlarr API key' -Value $ProwlarrApiKey
}

$RadarrUrl = Read-OptionalValue -Prompt 'Radarr URL for eMuleBB download client (blank to skip)' -Value $RadarrUrl
if ($RadarrUrl) {
    $RadarrApiKey = Read-SecretValue -Prompt 'Radarr API key' -Value $RadarrApiKey
    if ($ProwlarrUrl) {
        Run-TargetWithRetry -Name 'Prowlarr Radarr application registration' -Action {
            $saved = Save-ProwlarrApplication -ProwlarrBaseUrl $ProwlarrUrl -ProwlarrKey $ProwlarrApiKey -Kind 'radarr' -ArrUrl $RadarrUrl -ArrKey $RadarrApiKey
            Write-Host ('Prowlarr Radarr application saved with id {0}.' -f $saved.id) -ForegroundColor Green
        }
    }
    Run-TargetWithRetry -Name 'Radarr download client registration' -Action {
        $saved = Save-QbitClient -Kind 'radarr' -BaseUrl $RadarrUrl -ApiKey $RadarrApiKey -EmuleBaseUrl $EmulebbBaseUrl -EmuleApiKey $EmulebbApiKey
        Write-Host ('Radarr download client saved with id {0}.' -f $saved.id) -ForegroundColor Green
    }
}

$SonarrUrl = Read-OptionalValue -Prompt 'Sonarr URL for eMuleBB download client (blank to skip)' -Value $SonarrUrl
if ($SonarrUrl) {
    $SonarrApiKey = Read-SecretValue -Prompt 'Sonarr API key' -Value $SonarrApiKey
    if ($ProwlarrUrl) {
        Run-TargetWithRetry -Name 'Prowlarr Sonarr application registration' -Action {
            $saved = Save-ProwlarrApplication -ProwlarrBaseUrl $ProwlarrUrl -ProwlarrKey $ProwlarrApiKey -Kind 'sonarr' -ArrUrl $SonarrUrl -ArrKey $SonarrApiKey
            Write-Host ('Prowlarr Sonarr application saved with id {0}.' -f $saved.id) -ForegroundColor Green
        }
    }
    Run-TargetWithRetry -Name 'Sonarr download client registration' -Action {
        $saved = Save-QbitClient -Kind 'sonarr' -BaseUrl $SonarrUrl -ApiKey $SonarrApiKey -EmuleBaseUrl $EmulebbBaseUrl -EmuleApiKey $EmulebbApiKey
        Write-Host ('Sonarr download client saved with id {0}.' -f $saved.id) -ForegroundColor Green
    }
}

if ($ProwlarrUrl) {
    Run-TargetWithRetry -Name 'Prowlarr application sync' -Action {
        Invoke-ProwlarrSync -BaseUrl $ProwlarrUrl -ApiKey $ProwlarrApiKey
    }
}

Write-Host 'eMuleBB integration registration finished.' -ForegroundColor Green
exit 0
