#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$EmulebbBaseUrl,
    [string]$EmulebbApiKey,
    [string]$ProwlarrUrl,
    [string]$ProwlarrApiKey,
    [string]$IndexerName = 'eMuleBB'
)

$ErrorActionPreference = 'Stop'

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
    if ($Optional) {
        return $false
    }
    throw "Provider payload is missing field: $Name"
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
    foreach ($indexer in @(Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/indexer')) {
        if ($indexer.name -eq $Name) {
            return $indexer
        }
    }
    return $null
}

function Save-Indexer {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Name,
        [string]$TorznabBaseUrl,
        [string]$TorznabApiKey
    )

    $existing = Get-ExistingIndexer -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name
    if ($null -ne $existing) {
        $payload = $existing
    } else {
        $payload = Get-GenericTorznabSchema -BaseUrl $BaseUrl -ApiKey $ApiKey
    }

    $payload.name = $Name
    $payload.enable = $true
    $payload.appProfileId = [int]($payload.appProfileId -as [int])
    if ($payload.appProfileId -le 0) { $payload.appProfileId = 1 }
    $payload.priority = [int]($payload.priority -as [int])
    if ($payload.priority -le 0) { $payload.priority = 25 }
    $payload.implementation = 'Torznab'
    $payload.implementationName = 'Torznab'
    $payload.configContract = 'TorznabSettings'
    Set-ProviderField -Provider $payload -Name 'baseUrl' -Value ($TorznabBaseUrl.TrimEnd('/'))
    Set-ProviderField -Provider $payload -Name 'apiPath' -Value '/api'
    Set-ProviderField -Provider $payload -Name 'apiKey' -Value $TorznabApiKey
    Set-ProviderField -Provider $payload -Name 'torrentBaseSettings.preferMagnetUrl' -Value $true
    if ($TorznabBaseUrl.StartsWith('https://', [StringComparison]::OrdinalIgnoreCase)) {
        [void](Set-ProviderField -Provider $payload -Name 'certificateValidation' -Value 1 -Optional)
    }

    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v1/indexer/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/indexer?forceSave=true' -Method 'POST' -Body $payload
}

function Confirm-Retry {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
    $answer = Read-Host 'Retry? [Y/n]'
    return [string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLowerInvariant().StartsWith('y')
}

Write-Host 'eMuleBB Prowlarr Registration' -ForegroundColor Cyan
do {
    try {
        $ProwlarrUrl = Read-RequiredValue -Prompt 'Prowlarr URL (example http://localhost:9696)' -Value $ProwlarrUrl
        $ProwlarrApiKey = Read-SecretValue -Prompt 'Prowlarr API key' -Value $ProwlarrApiKey
        $EmulebbBaseUrl = Read-RequiredValue -Prompt 'eMuleBB base URL (example http://127.0.0.1:4711)' -Value $EmulebbBaseUrl
        $EmulebbApiKey = Read-SecretValue -Prompt 'eMuleBB API key' -Value $EmulebbApiKey
        $saved = Save-Indexer -BaseUrl $ProwlarrUrl -ApiKey $ProwlarrApiKey -Name $IndexerName -TorznabBaseUrl ($EmulebbBaseUrl.TrimEnd('/') + '/indexer/emulebb') -TorznabApiKey $EmulebbApiKey
        Write-Host ('Registered Prowlarr indexer "{0}" with id {1}.' -f $saved.name, $saved.id) -ForegroundColor Green
        exit 0
    } catch {
        if (-not (Confirm-Retry -Message ('Registration failed: {0}' -f $_.Exception.Message))) {
            exit 1
        }
        $ProwlarrUrl = ''
        $ProwlarrApiKey = ''
    }
} while ($true)
