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
    [string]$LidarrUrl,
    [string]$LidarrApiKey,
    [string]$ReadarrUrl,
    [string]$ReadarrApiKey,
    [string]$WhisparrUrl,
    [string]$WhisparrApiKey,
    [string]$SuiteAppsManifest,
    [string]$DownloadClientName = 'eMuleBB',
    [switch]$SkipProwlarrSync,
    [switch]$SyncProwlarrOnly,
    [switch]$VerifyIndexerOnly,
    [switch]$NoRetry
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Import-SuiteAppManifest.ps1')
$ArrTargets = @('Radarr', 'Sonarr', 'Lidarr', 'Readarr', 'Whisparr')
$ArrTargetPorts = @{
    Radarr = 7878
    Sonarr = 8989
    Lidarr = 8686
    Readarr = 8787
    Whisparr = 6969
}
$script:ArrTargetIndexerCategories = @{
    radarr = @(2000)
    sonarr = @(5000)
    lidarr = @(3000)
    readarr = @(7000)
    whisparr = @(6000)
}

function Get-SuiteAppsManifestPath {
    if (-not [string]::IsNullOrWhiteSpace($SuiteAppsManifest)) {
        if (Test-Path -LiteralPath $SuiteAppsManifest -PathType Leaf) {
            return [IO.Path]::GetFullPath($SuiteAppsManifest)
        }
        throw "SuiteAppsManifest does not exist: $SuiteAppsManifest"
    }
    $candidates = @(
        (Join-Path (Split-Path -Parent $PSScriptRoot) 'config\suite-apps.json'),
        ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..\config\suite-apps.json')))
    )
    $seen = @{}
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate) -or $seen.ContainsKey($candidate)) {
            continue
        }
        $seen[$candidate] = $true
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return ''
}

function Initialize-ArrIndexerCategories {
    $manifestPath = Get-SuiteAppsManifestPath
    if ([string]::IsNullOrWhiteSpace($manifestPath)) {
        return
    }
    try {
        $manifest = Read-SuiteAppManifest -Path $manifestPath
        foreach ($key in $manifest.ArrIndexerCategories.Keys) {
            $script:ArrTargetIndexerCategories[$key] = $manifest.ArrIndexerCategories[$key]
        }
    } catch {
        throw "Could not load Arr indexer categories from suite app manifest: $manifestPath. $($_.Exception.Message)"
    }
}

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
        Write-Host 'First-time setup or repair: press Enter to register. Choose U only to remove this Arr integration.' -ForegroundColor Cyan
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
        if ($normalized -eq 'readarr' -or $normalized -eq 're') { return 'Readarr' }
        if ($normalized -eq 'radarr' -or $normalized -eq 'r') { return 'Radarr' }
        if ($normalized -eq 'sonarr' -or $normalized -eq 's') { return 'Sonarr' }
        if ($normalized -eq 'lidarr' -or $normalized -eq 'l') { return 'Lidarr' }
        if ($normalized -eq 'whisparr' -or $normalized -eq 'w') { return 'Whisparr' }
        throw "Target must be Radarr, Sonarr, Lidarr, Readarr, or Whisparr, not '$Value'."
    }
    while ($true) {
        $answer = Read-Host 'Target [R]adarr/[S]onarr/[L]idarr/Re[a]darr/[W]hisparr'
        $normalized = $answer.Trim().ToLowerInvariant()
        if ($normalized.StartsWith('r')) { return 'Radarr' }
        if ($normalized.StartsWith('s')) { return 'Sonarr' }
        if ($normalized.StartsWith('l')) { return 'Lidarr' }
        if ($normalized -eq 'a' -or $normalized -eq 'readarr') { return 'Readarr' }
        if ($normalized.StartsWith('w')) { return 'Whisparr' }
        Write-Host 'Enter R, S, L, A, or W.' -ForegroundColor Yellow
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

function Get-ArrUrlPrompt {
    param([string]$Target)
    return "$Target URL for eMuleBB download client (example http://LAN-IP:$($ArrTargetPorts[$Target]))"
}

function Get-TargetUrlParameter {
    param([string]$Target)
    switch ($Target) {
        'Radarr' { return Normalize-ArgumentValue -Value $RadarrUrl }
        'Sonarr' { return Normalize-ArgumentValue -Value $SonarrUrl }
        'Lidarr' { return Normalize-ArgumentValue -Value $LidarrUrl }
        'Readarr' { return Normalize-ArgumentValue -Value $ReadarrUrl }
        'Whisparr' { return Normalize-ArgumentValue -Value $WhisparrUrl }
    }
    return ''
}

function Get-TargetApiKeyParameter {
    param([string]$Target)
    switch ($Target) {
        'Radarr' { return Normalize-ArgumentValue -Value $RadarrApiKey }
        'Sonarr' { return Normalize-ArgumentValue -Value $SonarrApiKey }
        'Lidarr' { return Normalize-ArgumentValue -Value $LidarrApiKey }
        'Readarr' { return Normalize-ArgumentValue -Value $ReadarrApiKey }
        'Whisparr' { return Normalize-ArgumentValue -Value $WhisparrApiKey }
    }
    return ''
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
            throw "Arr API key was rejected by $uri. Copy the API key from Settings > General in the matching Radarr/Sonarr web UI, then rerun this script."
        }
        throw
    }
}

function Get-ExceptionResponse {
    param($Exception)
    if ($null -eq $Exception) {
        return $null
    }
    try {
        $responseProperty = $Exception.PSObject.Properties['Response']
        if ($null -eq $responseProperty) {
            return $null
        }
        return $responseProperty.Value
    } catch {
        return $null
    }
}

function Get-HttpStatusCode {
    param($Exception)
    $response = Get-ExceptionResponse -Exception $Exception
    if ($null -eq $response) {
        return 0
    }
    try {
        return [int]$response.StatusCode
    } catch {
        return 0
    }
}

function Get-HttpErrorDetail {
    param($Exception)
    $response = Get-ExceptionResponse -Exception $Exception
    if ($null -eq $response) {
        return ''
    }
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

function Test-ApiKeyRejectedError {
    param($Exception)
    if ($null -eq $Exception -or [string]::IsNullOrWhiteSpace([string]$Exception.Message)) {
        return $false
    }
    return ([string]$Exception.Message).StartsWith('Arr API key was rejected by ', [StringComparison]::OrdinalIgnoreCase)
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
            if (Test-ApiKeyRejectedError -Exception $_.Exception) {
                throw
            }
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

function Get-ArrApiBasePath {
    param([string]$Kind)
    switch ($Kind.ToLowerInvariant()) {
        'lidarr' { return '/api/v1' }
        'readarr' { return '/api/v1' }
        default { return '/api/v3' }
    }
}

function Set-LocalCertificateValidation {
    param([string]$Kind, [string]$BaseUrl, [string]$ApiKey)
    $apiBasePath = Get-ArrApiBasePath -Kind $Kind
    $hostConfig = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path "$apiBasePath/config/host"
    if ($null -eq $hostConfig) {
        throw 'Arr host config did not return a response.'
    }
    if ([string]$hostConfig.certificateValidation -eq 'disabledForLocalAddresses') {
        return $hostConfig
    }
    Set-ObjectProperty -Target $hostConfig -Name 'certificateValidation' -Value 'disabledForLocalAddresses'
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path "$apiBasePath/config/host" -Method 'PUT' -Body $hostConfig
}

function Get-QbitSchema {
    param([string]$Kind, [string]$BaseUrl, [string]$ApiKey)
    $apiBasePath = Get-ArrApiBasePath -Kind $Kind
    $schemas = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path "$apiBasePath/downloadclient/schema"
    foreach ($schema in @($schemas)) {
        if ($schema.implementation -eq 'QBittorrent') {
            return $schema
        }
    }
    throw 'Arr did not expose the qBittorrent download-client schema.'
}

function Get-ProwlarrQbitSchema {
    param([string]$BaseUrl, [string]$ApiKey)
    $schemas = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/downloadclient/schema'
    foreach ($schema in @($schemas)) {
        if ($schema.implementation -eq 'QBittorrent') {
            return $schema
        }
    }
    throw 'Prowlarr did not expose the qBittorrent download-client schema.'
}

function Get-ExistingDownloadClient {
    param([string]$Kind, [string]$BaseUrl, [string]$ApiKey, [string]$Name)
    $apiBasePath = Get-ArrApiBasePath -Kind $Kind
    $clients = Invoke-JsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path "$apiBasePath/downloadclient"
    foreach ($client in @($clients)) {
        if ($client.name -eq $Name) {
            return $client
        }
    }
    return $null
}

function Get-ExistingProwlarrDownloadClient {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Name)
    $clients = Invoke-JsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/downloadclient'
    foreach ($client in @($clients)) {
        if ($client.name -eq $Name) {
            return $client
        }
    }
    return $null
}

function Get-ArrProwlarrIndexerName {
    param([string]$Name)
    if ($Name.EndsWith(' (Prowlarr)', [StringComparison]::OrdinalIgnoreCase)) {
        return $Name
    }
    return "$Name (Prowlarr)"
}

function Test-ArrProwlarrIndexerName {
    param([string]$ActualName, [string]$Name)
    return [string]::Equals($ActualName, $Name, [StringComparison]::OrdinalIgnoreCase) -or [string]::Equals($ActualName, (Get-ArrProwlarrIndexerName -Name $Name), [StringComparison]::OrdinalIgnoreCase)
}

function Get-ExistingArrIndexers {
    param([string]$Kind, [string]$BaseUrl, [string]$ApiKey, [string]$Name)
    $matches = @()
    $apiBasePath = Get-ArrApiBasePath -Kind $Kind
    $indexers = Invoke-JsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path "$apiBasePath/indexer"
    foreach ($indexerGroup in @($indexers)) {
        foreach ($indexer in @($indexerGroup)) {
            if (Test-ArrProwlarrIndexerName -ActualName ([string]$indexer.name) -Name $Name) {
                $matches += $indexer
            }
        }
    }
    return $matches
}

function Get-PreferredArrIndexer {
    param($Indexers, [string]$Name)
    $managedName = Get-ArrProwlarrIndexerName -Name $Name
    foreach ($indexerGroup in @($Indexers)) {
        foreach ($indexer in @($indexerGroup)) {
            if ([string]::Equals([string]$indexer.name, $managedName, [StringComparison]::OrdinalIgnoreCase)) {
                return $indexer
            }
        }
    }
    foreach ($indexerGroup in @($Indexers)) {
        foreach ($indexer in @($indexerGroup)) {
            return $indexer
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
    $apiBasePath = Get-ArrApiBasePath -Kind $Kind
    $existing = Get-ExistingDownloadClient -Kind $Kind -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name
    if ($null -ne $existing) {
        $payload = $existing
    } else {
        $payload = Get-QbitSchema -Kind $Kind -BaseUrl $BaseUrl -ApiKey $ApiKey
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
    $category = (Get-ArrCategoryInfo -Kind $Kind).Name
    $urlBase = if ($uri.AbsolutePath -and $uri.AbsolutePath -ne '/') { $uri.AbsolutePath.TrimEnd('/') } else { '' }
    [void](Set-ProviderField -Provider $payload -Name 'host' -Value $uri.Host)
    [void](Set-ProviderField -Provider $payload -Name 'port' -Value $uri.Port)
    [void](Set-ProviderField -Provider $payload -Name 'useSsl' -Value ($uri.Scheme -eq 'https'))
    [void](Set-ProviderField -Provider $payload -Name 'urlBase' -Value $urlBase)
    [void](Set-ProviderField -Provider $payload -Name 'username' -Value 'emule')
    [void](Set-ProviderField -Provider $payload -Name 'password' -Value $EmuleApiKey)
    if ($Kind -eq 'radarr') {
        [void](Set-ProviderField -Provider $payload -Name 'movieCategory' -Value $category)
    } elseif ($Kind -eq 'sonarr') {
        [void](Set-ProviderField -Provider $payload -Name 'tvCategory' -Value $category)
    } else {
        [void](Set-ProviderField -Provider $payload -Name 'category' -Value $category -Optional)
        [void](Set-ProviderField -Provider $payload -Name 'musicCategory' -Value $category -Optional)
        [void](Set-ProviderField -Provider $payload -Name 'bookCategory' -Value $category -Optional)
        [void](Set-ProviderField -Provider $payload -Name 'tvCategory' -Value $category -Optional)
    }
    [void](Set-ProviderField -Provider $payload -Name 'initialState' -Value 0)
    if ($uri.Scheme -eq 'https') {
        [void](Set-LocalCertificateValidation -Kind $Kind -BaseUrl $BaseUrl -ApiKey $ApiKey)
        [void](Set-ProviderField -Provider $payload -Name 'certificateValidation' -Value 1 -Optional)
    }
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('{0}/downloadclient/{1}?forceSave=true' -f $apiBasePath, [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path "$apiBasePath/downloadclient?forceSave=true" -Method 'POST' -Body $payload
}

function Save-ProwlarrQbitClient {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$EmuleBaseUrl,
        [string]$EmuleApiKey,
        [string]$Name
    )
    $normalizedEmuleBaseUrl = Normalize-HttpBaseUrl -Value $EmuleBaseUrl -Name 'EmuleBaseUrl'
    $uri = [Uri]$normalizedEmuleBaseUrl
    $existing = Get-ExistingProwlarrDownloadClient -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name
    if ($null -ne $existing) {
        $payload = $existing
    } else {
        $payload = Get-ProwlarrQbitSchema -BaseUrl $BaseUrl -ApiKey $ApiKey
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
    $urlBase = if ($uri.AbsolutePath -and $uri.AbsolutePath -ne '/') { $uri.AbsolutePath.TrimEnd('/') } else { '' }
    [void](Set-ProviderField -Provider $payload -Name 'host' -Value $uri.Host)
    [void](Set-ProviderField -Provider $payload -Name 'port' -Value $uri.Port)
    [void](Set-ProviderField -Provider $payload -Name 'useSsl' -Value ($uri.Scheme -eq 'https'))
    [void](Set-ProviderField -Provider $payload -Name 'urlBase' -Value $urlBase)
    [void](Set-ProviderField -Provider $payload -Name 'username' -Value 'emule')
    [void](Set-ProviderField -Provider $payload -Name 'password' -Value $EmuleApiKey)
    [void](Set-ProviderField -Provider $payload -Name 'category' -Value '' -Optional)
    [void](Set-ProviderField -Provider $payload -Name 'initialState' -Value 0 -Optional)
    if ($uri.Scheme -eq 'https') {
        [void](Set-ProviderField -Provider $payload -Name 'certificateValidation' -Value 1 -Optional)
    }
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('/api/v1/downloadclient/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/downloadclient?forceSave=true' -Method 'POST' -Body $payload
}

function Get-ArrCategoryName {
    param([string]$Kind)
    return (Get-ArrCategoryInfo -Kind $Kind).Name
}

function Get-ArrIndexerCategories {
    param([string]$Kind)
    $key = $Kind.ToLowerInvariant()
    if ($null -eq $script:ArrTargetIndexerCategories) {
        $script:ArrTargetIndexerCategories = @{
            radarr = @(2000)
            sonarr = @(5000)
            lidarr = @(3000)
            readarr = @(7000)
            whisparr = @(6000)
        }
    }
    if ($script:ArrTargetIndexerCategories.ContainsKey($key)) {
        return ,@($script:ArrTargetIndexerCategories[$key])
    }
    return ,@(5000)
}

function Get-ArrCategoryRelativePath {
    param([string]$Kind)
    return (Get-ArrCategoryInfo -Kind $Kind).RelativePath
}

function Get-ArrCategoryInfo {
    param([string]$Kind)
    $normalized = $Kind.ToLowerInvariant()
    return [pscustomobject]@{ Name = "emulebb-$normalized"; RelativePath = "downloads\$normalized" }
}

function Get-CultureInvariantTitleCase {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ''
    }
    $lower = $Value.ToLowerInvariant()
    return $lower.Substring(0, 1).ToUpperInvariant() + $lower.Substring(1)
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

function Get-ProwlarrIndexer {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Name)
    $indexers = Invoke-JsonApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/v1/indexer'
    foreach ($indexer in @($indexers)) {
        if ($indexer.name -eq $Name) {
            return $indexer
        }
    }
    throw "Prowlarr indexer '$Name' is not registered. Run Register-Prowlarr.ps1 first, then rerun this script."
}

function Assert-ProviderFieldEquals {
    param($Provider, [string]$FieldName, $ExpectedValue, [string]$FailureMessage)
    $actualValue = Get-ProviderFieldValue -Provider $Provider -Name $FieldName
    if ([string]$actualValue -ne [string]$ExpectedValue) {
        throw ($FailureMessage -f $actualValue)
    }
}

function Assert-ProviderFieldPresent {
    param($Provider, [string]$FieldName, [string]$FailureMessage)
    foreach ($field in @($Provider.fields)) {
        if ($field.name -eq $FieldName) {
            return
        }
    }
    throw $FailureMessage
}

function Test-CategorySetEquals {
    param($Actual, $Expected)
    $actualItems = @($Actual | ForEach-Object { [int]$_ } | Sort-Object)
    $expectedItems = @($Expected | ForEach-Object { [int]$_ } | Sort-Object)
    if ($actualItems.Count -ne $expectedItems.Count) {
        return $false
    }
    for ($i = 0; $i -lt $actualItems.Count; $i++) {
        if ($actualItems[$i] -ne $expectedItems[$i]) {
            return $false
        }
    }
    return $true
}

function Verify-ArrProwlarrIndexer {
    param(
        [string]$Kind,
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Name,
        [string]$ProwlarrBaseUrl,
        [string]$ProwlarrKey
    )
    $managedName = Get-ArrProwlarrIndexerName -Name $Name
    $prowlarrIndexer = Get-ProwlarrIndexer -BaseUrl $ProwlarrBaseUrl -ApiKey $ProwlarrKey -Name $Name
    if ($null -eq $prowlarrIndexer -or -not $prowlarrIndexer.id) {
        throw "Prowlarr indexer '$Name' did not return an id."
    }

    $indexers = @(Get-ExistingArrIndexers -Kind $Kind -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name)
    $indexer = Get-PreferredArrIndexer -Indexers $indexers -Name $Name
    if ($null -eq $indexer) {
        throw "Arr indexer '$managedName' was not found after Prowlarr application sync."
    }

    $expectedBaseUrl = (Normalize-HttpBaseUrl -Value $ProwlarrBaseUrl -Name 'ProwlarrBaseUrl') + '/' + [int]$prowlarrIndexer.id
    $actualBaseUrl = [string](Get-ProviderFieldValue -Provider $indexer -Name 'baseUrl')
    if ($actualBaseUrl.TrimEnd('/').ToLowerInvariant() -ne $expectedBaseUrl.ToLowerInvariant()) {
        throw ('Arr indexer "{0}" points at "{1}" instead of "{2}". Run Prowlarr application sync again.' -f $indexer.name, $actualBaseUrl, $expectedBaseUrl)
    }
    Assert-ProviderFieldEquals -Provider $indexer -FieldName 'apiPath' -ExpectedValue '/api' -FailureMessage ('Arr indexer "{0}" has unexpected apiPath: {{0}}' -f $indexer.name)
    Assert-ProviderFieldPresent -Provider $indexer -FieldName 'apiKey' -FailureMessage ('Arr indexer "{0}" is missing its Prowlarr API key field.' -f $indexer.name)

    $actualCategories = @(Get-ProviderFieldValue -Provider $indexer -Name 'categories')
    $expectedCategories = Get-ArrIndexerCategories -Kind $Kind
    if (-not (Test-CategorySetEquals -Actual $actualCategories -Expected $expectedCategories)) {
        throw ('Arr indexer "{0}" has categories "{1}" instead of "{2}". Run Prowlarr application sync again.' -f $indexer.name, ($actualCategories -join ','), ($expectedCategories -join ','))
    }
    return $indexer
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
        [string]$Kind,
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Name
    )
    $apiBasePath = Get-ArrApiBasePath -Kind $Kind
    $existing = Get-ExistingDownloadClient -Kind $Kind -BaseUrl $BaseUrl -ApiKey $ApiKey -Name $Name
    if ($null -eq $existing -or -not $existing.id) {
        Write-Host ('Download client "{0}" is not registered.' -f $Name) -ForegroundColor Yellow
        return
    }
    Invoke-DeleteJsonApiWithRetry -BaseUrl $BaseUrl -ApiKey $ApiKey -Path (('{0}/downloadclient/{1}' -f $apiBasePath, [int]$existing.id))
    Write-Host ('Unregistered download client "{0}" with id {1}.' -f $Name, $existing.id) -ForegroundColor Green
}

function Get-ProwlarrCommandFailureDetail {
    param($Status)
    if ($null -eq $Status) {
        return ''
    }
    $parts = New-Object 'System.Collections.Generic.List[string]'
    foreach ($name in @('status', 'state', 'message', 'errorMessage', 'exception')) {
        if ($null -eq $Status.PSObject.Properties[$name]) {
            continue
        }
        $value = ([string]$Status.PSObject.Properties[$name].Value -replace '\s+', ' ').Trim()
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $parts.Add(('{0}: {1}' -f $name, $value))
        }
    }
    if ($parts.Count -eq 0) {
        return ''
    }
    $detail = $parts -join '; '
    if ($detail.Length -gt 1200) {
        return $detail.Substring(0, 1200) + '...'
    }
    return $detail
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
            $detail = Get-ProwlarrCommandFailureDetail -Status $status
            if ([string]::IsNullOrWhiteSpace($detail)) {
                throw ('Prowlarr application sync failed: {0}' -f $commandId)
            }
            throw ('Prowlarr application sync failed: {0}. {1}' -f $commandId, $detail)
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw ('Prowlarr application sync timed out: {0}' -f $commandId)
}

function Get-ProwlarrApplicationSchema {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Kind)
    $kindText = $Kind.ToLowerInvariant()
    $implementation = $kindText.Substring(0, 1).ToUpperInvariant() + $kindText.Substring(1)
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
    $kindText = $Kind.ToLowerInvariant()
    $name = $kindText.Substring(0, 1).ToUpperInvariant() + $kindText.Substring(1)
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
    [void](Set-ProviderField -Provider $payload -Name 'syncCategories' -Value (Get-ArrIndexerCategories -Kind $Kind) -Optional)
    [void](Set-ProviderField -Provider $payload -Name 'animeSyncCategories' -Value @() -Optional)
    if ($null -ne $existing -and $existing.id) {
        return Invoke-JsonApi -BaseUrl $normalizedProwlarrBaseUrl -ApiKey $ProwlarrKey -Path (('/api/v1/applications/{0}?forceSave=true' -f [int]$existing.id)) -Method 'PUT' -Body $payload
    }
    return Invoke-JsonApi -BaseUrl $normalizedProwlarrBaseUrl -ApiKey $ProwlarrKey -Path '/api/v1/applications?forceSave=true' -Method 'POST' -Body $payload
}

function Run-TargetWithRetry {
    param([string]$Name, [scriptblock]$Operation, [scriptblock]$OnRetry = $null, [switch]$NoRetry)
    do {
        try {
            & $Operation
            return
        } catch {
            Write-Host ('{0} failed: {1}' -f $Name, (Get-ExceptionMessage -Exception $_.Exception)) -ForegroundColor Red
            if ($NoRetry) {
                throw
            }
            $answer = Read-Host ('Retry {0}? [Y/n]' -f $Name)
            if (-not ([string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLowerInvariant().StartsWith('y'))) {
                throw "$Name cancelled by user."
            }
            if ($null -ne $OnRetry) {
                & $OnRetry
            }
        }
    } while ($true)
}

Initialize-ArrIndexerCategories

if ($SyncProwlarrOnly) {
    Write-Host 'eMuleBB Prowlarr Application Sync' -ForegroundColor Cyan
    Run-TargetWithRetry -Name 'Prowlarr application sync' -NoRetry:$NoRetry -OnRetry {
        $script:ProwlarrUrl = ''
        $script:ProwlarrApiKey = ''
    } -Operation {
        $script:ProwlarrUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'Prowlarr URL for application sync (example http://LAN-IP:9696)' -Value $script:ProwlarrUrl) -Name 'ProwlarrUrl'
        $script:ProwlarrApiKey = Read-RequiredSecretValue -Prompt 'Prowlarr API key' -Value $script:ProwlarrApiKey -Name 'ProwlarrApiKey'
        Invoke-ProwlarrSync -BaseUrl $script:ProwlarrUrl -ApiKey $script:ProwlarrApiKey
    }
    return
}

if ($VerifyIndexerOnly) {
    $Target = Read-TargetValue -Value $Target
    $targetKind = $Target.ToLowerInvariant()
    Write-Host ('eMuleBB {0} Indexer Verification' -f $Target) -ForegroundColor Cyan
    $script:targetUrl = Get-TargetUrlParameter -Target $Target
    $script:targetApiKey = Get-TargetApiKeyParameter -Target $Target
    Run-TargetWithRetry -Name "$Target indexer verification" -NoRetry:$NoRetry -OnRetry {
        $script:ProwlarrUrl = ''
        $script:ProwlarrApiKey = ''
        $script:targetUrl = ''
        $script:targetApiKey = ''
    } -Operation {
        $script:ProwlarrUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'Prowlarr URL for indexer verification (example http://LAN-IP:9696)' -Value $script:ProwlarrUrl) -Name 'ProwlarrUrl'
        $script:ProwlarrApiKey = Read-RequiredSecretValue -Prompt 'Prowlarr API key' -Value $script:ProwlarrApiKey -Name 'ProwlarrApiKey'
        $script:targetUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt (Get-ArrUrlPrompt -Target $Target) -Value $script:targetUrl) -Name ("${Target}Url")
        $script:targetApiKey = Read-RequiredSecretValue -Prompt "$Target API key" -Value $script:targetApiKey -Name ("${Target}ApiKey")
        $saved = Verify-ArrProwlarrIndexer -Kind $targetKind -BaseUrl $script:targetUrl -ApiKey $script:targetApiKey -Name $DownloadClientName -ProwlarrBaseUrl $script:ProwlarrUrl -ProwlarrKey $script:ProwlarrApiKey
        Write-Host ('{0} indexer "{1}" is configured with id {2}.' -f $Target, $saved.name, $saved.id) -ForegroundColor Green
    }
    return
}

$ProwlarrUrl = Read-OptionalValue -Prompt 'Prowlarr URL for application sync (example http://LAN-IP:9696)' -Value $ProwlarrUrl

$Action = Read-ActionValue -Value $Action
$Target = Read-TargetValue -Value $Target
$targetKind = $Target.ToLowerInvariant()
Write-Host ('eMuleBB {0} Integration - {1}' -f $Target, $Action) -ForegroundColor Cyan
if ($Action -eq 'Register' -and [string]::IsNullOrWhiteSpace($ProwlarrUrl)) {
    throw 'ProwlarrUrl is required for Arr registration. Register eMuleBB in Prowlarr and let Prowlarr sync indexers to selected Arr apps.'
}
$script:targetUrl = Get-TargetUrlParameter -Target $Target
$script:targetApiKey = Get-TargetApiKeyParameter -Target $Target

if ($Action -eq 'Register') {
    $arrCategoryName = Get-ArrCategoryName -Kind $targetKind
    $EmulebbCategoryPath = Normalize-OptionalCategoryPath -Path $EmulebbCategoryPath
    Run-TargetWithRetry -Name 'eMuleBB category registration' -NoRetry:$NoRetry -OnRetry {
        $script:EmulebbBaseUrl = ''
        $script:EmulebbApiKey = ''
    } -Operation {
        $script:EmulebbBaseUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'eMuleBB base URL (example http://LAN-IP:4711)' -Value $script:EmulebbBaseUrl) -Name 'EmulebbBaseUrl'
        $script:EmulebbApiKey = Read-RequiredSecretValue -Prompt 'eMuleBB API key' -Value $script:EmulebbApiKey -Name 'EmulebbApiKey'
        Ensure-EmuleCategory -BaseUrl $script:EmulebbBaseUrl -ApiKey $script:EmulebbApiKey -Name $arrCategoryName -Path $EmulebbCategoryPath
    }
}

if ($Action -eq 'Register' -and $ProwlarrUrl) {
    Run-TargetWithRetry -Name "Prowlarr $Target application registration" -NoRetry:$NoRetry -OnRetry {
        $script:ProwlarrUrl = ''
        $script:ProwlarrApiKey = ''
        $script:targetUrl = ''
        $script:targetApiKey = ''
    } -Operation {
        $script:ProwlarrUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'Prowlarr URL for application sync (example http://LAN-IP:9696)' -Value $script:ProwlarrUrl) -Name 'ProwlarrUrl'
        $script:ProwlarrApiKey = Read-RequiredSecretValue -Prompt 'Prowlarr API key' -Value $script:ProwlarrApiKey -Name 'ProwlarrApiKey'
        $script:targetUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt (Get-ArrUrlPrompt -Target $Target) -Value $script:targetUrl) -Name ("${Target}Url")
        $script:targetApiKey = Read-RequiredSecretValue -Prompt "$Target API key" -Value $script:targetApiKey -Name ("${Target}ApiKey")
        $saved = Save-ProwlarrApplication -ProwlarrBaseUrl $script:ProwlarrUrl -ProwlarrKey $script:ProwlarrApiKey -Kind $targetKind -ArrUrl $script:targetUrl -ArrKey $script:targetApiKey
        Write-Host ('Prowlarr {0} application saved with id {1}.' -f $Target, $saved.id) -ForegroundColor Green
    }
}

if ($Action -eq 'Register' -and $ProwlarrUrl) {
    Run-TargetWithRetry -Name 'Prowlarr download client registration' -NoRetry:$NoRetry -OnRetry {
        $script:ProwlarrUrl = ''
        $script:ProwlarrApiKey = ''
        $script:EmulebbBaseUrl = ''
        $script:EmulebbApiKey = ''
    } -Operation {
        $script:ProwlarrUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'Prowlarr URL for download client setup (example http://LAN-IP:9696)' -Value $script:ProwlarrUrl) -Name 'ProwlarrUrl'
        $script:ProwlarrApiKey = Read-RequiredSecretValue -Prompt 'Prowlarr API key' -Value $script:ProwlarrApiKey -Name 'ProwlarrApiKey'
        $script:EmulebbBaseUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'eMuleBB base URL (example http://LAN-IP:4711)' -Value $script:EmulebbBaseUrl) -Name 'EmulebbBaseUrl'
        $script:EmulebbApiKey = Read-RequiredSecretValue -Prompt 'eMuleBB API key' -Value $script:EmulebbApiKey -Name 'EmulebbApiKey'
        $saved = Save-ProwlarrQbitClient -BaseUrl $script:ProwlarrUrl -ApiKey $script:ProwlarrApiKey -EmuleBaseUrl $script:EmulebbBaseUrl -EmuleApiKey $script:EmulebbApiKey -Name $DownloadClientName
        Write-Host ('Prowlarr download client saved with id {0}.' -f $saved.id) -ForegroundColor Green
    }
}

Run-TargetWithRetry -Name ("$Target download client {0}" -f $Action.ToLowerInvariant()) -NoRetry:$NoRetry -OnRetry {
    $script:targetUrl = ''
    $script:targetApiKey = ''
    if ($script:Action -eq 'Register') {
        $script:EmulebbBaseUrl = ''
        $script:EmulebbApiKey = ''
    }
} -Operation {
    $script:targetUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt (Get-ArrUrlPrompt -Target $Target) -Value $script:targetUrl) -Name ("${Target}Url")
    $script:targetApiKey = Read-RequiredSecretValue -Prompt "$Target API key" -Value $script:targetApiKey -Name ("${Target}ApiKey")
    if ($Action -eq 'Unregister') {
        Remove-QbitClient -Kind $targetKind -BaseUrl $script:targetUrl -ApiKey $script:targetApiKey -Name $DownloadClientName
    } else {
        $script:EmulebbBaseUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'eMuleBB base URL (example http://LAN-IP:4711)' -Value $script:EmulebbBaseUrl) -Name 'EmulebbBaseUrl'
        $script:EmulebbApiKey = Read-RequiredSecretValue -Prompt 'eMuleBB API key' -Value $script:EmulebbApiKey -Name 'EmulebbApiKey'
        $saved = Save-QbitClient -Kind $targetKind -BaseUrl $script:targetUrl -ApiKey $script:targetApiKey -EmuleBaseUrl $script:EmulebbBaseUrl -EmuleApiKey $script:EmulebbApiKey -Name $DownloadClientName
        Write-Host ('{0} download client saved with id {1}.' -f $Target, $saved.id) -ForegroundColor Green
    }
}

if ($ProwlarrUrl -and -not $SkipProwlarrSync) {
    Run-TargetWithRetry -Name 'Prowlarr application sync' -NoRetry:$NoRetry -OnRetry {
        $script:ProwlarrUrl = ''
        $script:ProwlarrApiKey = ''
    } -Operation {
        $script:ProwlarrUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'Prowlarr URL for application sync (example http://LAN-IP:9696)' -Value $script:ProwlarrUrl) -Name 'ProwlarrUrl'
        $script:ProwlarrApiKey = Read-RequiredSecretValue -Prompt 'Prowlarr API key' -Value $script:ProwlarrApiKey -Name 'ProwlarrApiKey'
        Invoke-ProwlarrSync -BaseUrl $script:ProwlarrUrl -ApiKey $script:ProwlarrApiKey
    }
}

if ($Action -eq 'Register' -and $ProwlarrUrl -and -not $SkipProwlarrSync) {
    Run-TargetWithRetry -Name "$Target indexer verification" -NoRetry:$NoRetry -OnRetry {
        $script:ProwlarrUrl = ''
        $script:ProwlarrApiKey = ''
        $script:targetUrl = ''
        $script:targetApiKey = ''
    } -Operation {
        $script:ProwlarrUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'Prowlarr URL for indexer verification (example http://LAN-IP:9696)' -Value $script:ProwlarrUrl) -Name 'ProwlarrUrl'
        $script:ProwlarrApiKey = Read-RequiredSecretValue -Prompt 'Prowlarr API key' -Value $script:ProwlarrApiKey -Name 'ProwlarrApiKey'
        $script:targetUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt (Get-ArrUrlPrompt -Target $Target) -Value $script:targetUrl) -Name ("${Target}Url")
        $script:targetApiKey = Read-RequiredSecretValue -Prompt "$Target API key" -Value $script:targetApiKey -Name ("${Target}ApiKey")
        $saved = Verify-ArrProwlarrIndexer -Kind $targetKind -BaseUrl $script:targetUrl -ApiKey $script:targetApiKey -Name $DownloadClientName -ProwlarrBaseUrl $script:ProwlarrUrl -ProwlarrKey $script:ProwlarrApiKey
        Write-Host ('{0} indexer "{1}" is configured with id {2}.' -f $Target, $saved.name, $saved.id) -ForegroundColor Green
    }
}

Write-Host ('eMuleBB {0} integration {1} finished.' -f $Target, $Action.ToLowerInvariant()) -ForegroundColor Green
return
