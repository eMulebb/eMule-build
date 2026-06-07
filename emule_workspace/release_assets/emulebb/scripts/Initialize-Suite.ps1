#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Read-SuiteConfig {
    $configPath = Join-Path $Root 'manifests\suite-config.json'
    if (-not (Test-Path -LiteralPath $configPath)) {
        throw "Suite config is missing: $configPath. Re-run scripts\Install-eMuleBBSuite.ps1 with -Force to rebuild it."
    }
    return Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
}

function Test-SelectedApp {
    param($Config, [string]$Name)
    return @($Config.selectedApps) -contains $Name
}

function Get-ServiceClientHost {
    param([string]$ServiceName, $Service)
    if (-not [string]::IsNullOrWhiteSpace([string]$Service.clientHost)) {
        return [string]$Service.clientHost
    }
    return [string]$Service.bindAddress
}

function Get-ServiceUrl {
    param([string]$Name, $Service)
    return "http://$(Get-ServiceClientHost -ServiceName $Name -Service $Service):$([int]$Service.port)"
}

function Get-ExceptionMessage {
    param($Exception)
    if ($null -ne $Exception -and $null -ne $Exception.Response) {
        try {
            return "HTTP $([int]$Exception.Response.StatusCode) $($Exception.Response.StatusDescription)"
        } catch {
        }
    }
    return $Exception.Message
}

function Wait-Json {
    param([string]$Name, [string]$Uri, [hashtable]$Headers = @{})
    $lastError = ''
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec 2 -ErrorAction Stop | Out-Null
            return
        } catch {
            $lastError = Get-ExceptionMessage -Exception $_.Exception
            Start-Sleep -Seconds 1
        }
    }
    throw "Timed out waiting for $Name at $Uri. Last error: $lastError"
}

function Invoke-SuiteJsonApi {
    param([string]$Name, [string]$Uri, [string]$Method = 'GET', [hashtable]$Headers = @{}, $Body = $null)
    try {
        if ($null -eq $Body) {
            return Invoke-RestMethod -Uri $Uri -Method $Method -Headers $Headers -TimeoutSec 20 -ErrorAction Stop
        }
        return Invoke-RestMethod -Uri $Uri -Method $Method -Headers $Headers -Body ($Body | ConvertTo-Json -Depth 20) -ContentType 'application/json' -TimeoutSec 20 -ErrorAction Stop
    } catch {
        throw "$Name failed at $Uri. $(Get-ExceptionMessage -Exception $_.Exception)"
    }
}

function Set-ObjectProperty {
    param($Target, [string]$Name, $Value)
    if ($null -ne $Target.PSObject.Properties[$Name]) {
        $Target.$Name = $Value
    } else {
        $Target | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
}

function Get-ObjectPropertyValue {
    param($Target, [string]$Name, $Default = $null)
    if ($null -eq $Target -or $null -eq $Target.PSObject.Properties[$Name]) {
        return $Default
    }
    return $Target.PSObject.Properties[$Name].Value
}

function Get-OrCreateObjectProperty {
    param($Target, [string]$Name)
    $value = Get-ObjectPropertyValue -Target $Target -Name $Name -Default $null
    if ($null -eq $value) {
        $value = [pscustomobject]@{}
        Set-ObjectProperty -Target $Target -Name $Name -Value $value
    }
    return $value
}

function Set-AmutorrentSuiteClient {
    param($Config, [string]$EmulebbHost, [int]$EmulebbPort, [string]$EmulebbApiKey)
    $suiteClient = [pscustomobject]@{
        id = 'emulebb-suite'
        type = 'emulebb'
        name = 'eMuleBB Suite'
        color = $null
        enabled = $true
        host = $EmulebbHost
        port = $EmulebbPort
        apiKey = $EmulebbApiKey
        useSsl = $false
        path = ''
    }
    $clients = New-Object System.Collections.Generic.List[object]
    $replaced = $false
    foreach ($client in @(Get-ObjectPropertyValue -Target $Config -Name 'clients' -Default @())) {
        if ($null -eq $client) {
            continue
        }
        $id = [string](Get-ObjectPropertyValue -Target $client -Name 'id' -Default '')
        $type = [string](Get-ObjectPropertyValue -Target $client -Name 'type' -Default '')
        $name = [string](Get-ObjectPropertyValue -Target $client -Name 'name' -Default '')
        if ([string]::Equals($id, 'emulebb-suite', [StringComparison]::OrdinalIgnoreCase) -or
            ([string]::Equals($type, 'emulebb', [StringComparison]::OrdinalIgnoreCase) -and [string]::Equals($name, 'eMuleBB Suite', [StringComparison]::OrdinalIgnoreCase))) {
            if (-not $replaced) {
                $clients.Add($suiteClient)
                $replaced = $true
            }
            continue
        }
        $clients.Add($client)
    }
    if (-not $replaced) {
        $clients.Add($suiteClient)
    }
    Set-ObjectProperty -Target $Config -Name 'clients' -Value $clients.ToArray()
}

function Initialize-AmutorrentConfig {
    param(
        [string]$DataDir,
        [string]$BindAddress,
        [int]$Port,
        [string]$Username,
        [string]$Password,
        [string]$EmulebbHost,
        [int]$EmulebbPort,
        [string]$EmulebbApiKey
    )
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $configPath = Join-Path $DataDir 'config.json'
    if (Test-Path -LiteralPath $configPath) {
        try {
            $config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
            if ($null -eq $config) { $config = [pscustomobject]@{} }
        } catch {
            $backupPath = "$configPath.corrupt.$(Get-Date -Format 'yyyyMMddHHmmss')"
            Move-Item -Force -LiteralPath $configPath -Destination $backupPath
            Write-Warning "aMuTorrent config was not valid JSON and was moved to $backupPath. A fresh suite-managed config will be written."
            $config = [pscustomobject]@{}
        }
    } else {
        $config = [pscustomobject]@{}
    }
    Set-ObjectProperty -Target $config -Name 'version' -Value '1.0'
    Set-ObjectProperty -Target $config -Name 'firstRunCompleted' -Value $true
    $server = Get-OrCreateObjectProperty -Target $config -Name 'server'
    Set-ObjectProperty -Target $server -Name 'host' -Value $BindAddress
    Set-ObjectProperty -Target $server -Name 'port' -Value $Port
    $auth = Get-OrCreateObjectProperty -Target $server -Name 'auth'
    Set-ObjectProperty -Target $auth -Name 'enabled' -Value $true
    Set-ObjectProperty -Target $auth -Name 'adminUsername' -Value $Username
    Set-ObjectProperty -Target $auth -Name 'password' -Value $Password
    $directories = Get-OrCreateObjectProperty -Target $config -Name 'directories'
    Set-ObjectProperty -Target $directories -Name 'data' -Value $DataDir
    Set-ObjectProperty -Target $directories -Name 'logs' -Value (Join-Path $DataDir 'logs')
    Set-AmutorrentSuiteClient -Config $config -EmulebbHost $EmulebbHost -EmulebbPort $EmulebbPort -EmulebbApiKey $EmulebbApiKey
    $config | ConvertTo-Json -Depth 40 | Set-Content -Encoding UTF8 -LiteralPath $configPath
}

function Set-ArrHostCredentials {
    param([string]$Name, [string]$Url, [string]$ApiPath, [string]$ApiKey, [string]$Language)
    $hostConfigUrl = "$Url/$ApiPath/config/host"
    $headers = @{ 'X-Api-Key' = $ApiKey }
    $hostConfig = Invoke-SuiteJsonApi -Name "$Name host config read" -Uri $hostConfigUrl -Headers $headers
    Set-ObjectProperty -Target $hostConfig -Name 'authenticationMethod' -Value 'forms'
    Set-ObjectProperty -Target $hostConfig -Name 'authenticationRequired' -Value 'enabled'
    Set-ObjectProperty -Target $hostConfig -Name 'username' -Value ([string]$Config.credentials.username)
    Set-ObjectProperty -Target $hostConfig -Name 'password' -Value ([string]$Config.credentials.password)
    Set-ObjectProperty -Target $hostConfig -Name 'passwordConfirmation' -Value ([string]$Config.credentials.password)
    if (-not [string]::IsNullOrWhiteSpace($Language)) {
        Set-ObjectProperty -Target $hostConfig -Name 'uiLanguage' -Value $Language
    }
    [void](Invoke-SuiteJsonApi -Name "$Name web login update" -Uri $hostConfigUrl -Method 'PUT' -Headers $headers -Body $hostConfig)
}

function Ensure-ArrRootFolder {
    param([string]$Name, [string]$Url, [string]$ApiPath, [string]$ApiKey, [string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    $rootFolderUrl = "$Url/$ApiPath/rootfolder"
    $headers = @{ 'X-Api-Key' = $ApiKey }
    $normalizedPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $rootFolders = @(Invoke-SuiteJsonApi -Name "$Name root folder list" -Uri $rootFolderUrl -Headers $headers)
    foreach ($rootFolder in $rootFolders) {
        if ($rootFolder.PSObject.Properties['path'] -and [string]::Equals(([IO.Path]::GetFullPath([string]$rootFolder.path).TrimEnd('\')), $normalizedPath, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "$Name root folder already configured: $normalizedPath"
            return
        }
    }
    try {
        [void](Invoke-SuiteJsonApi -Name "$Name root folder create" -Uri $rootFolderUrl -Method 'POST' -Headers $headers -Body @{ path = $normalizedPath })
        Write-Host "$Name root folder configured: $normalizedPath"
    } catch {
        $message = Get-ExceptionMessage -Exception $_.Exception
        if ($message -match 'already configured as a root folder') {
            Write-Host "$Name root folder already configured: $normalizedPath"
            return
        }
        throw
    }
}

function Set-ArrPreferredContentLanguage {
    param([string]$Name, [string]$Url, [string]$ApiPath, [string]$ApiKey, [string]$Language)
    if ([string]::IsNullOrWhiteSpace($Language) -or $Language -eq 'English') {
        return
    }
    $headers = @{ 'X-Api-Key' = $ApiKey }
    try {
        $languages = @(Invoke-SuiteJsonApi -Name "$Name language list" -Uri "$Url/$ApiPath/language" -Headers $headers)
        $languageMatch = $null
        foreach ($item in $languages) {
            if ([string]::Equals([string]$item.name, $Language, [StringComparison]::OrdinalIgnoreCase)) {
                $languageMatch = $item
                break
            }
        }
        if ($null -eq $languageMatch) {
            Write-Warning "$Name did not expose content language '$Language'. Leaving existing profiles unchanged."
            return
        }
        $profiles = @(Invoke-SuiteJsonApi -Name "$Name quality profile list" -Uri "$Url/$ApiPath/qualityprofile" -Headers $headers)
        foreach ($profile in $profiles) {
            $changed = $false
            if ($profile.PSObject.Properties['language']) {
                $profile.language = $languageMatch
                $changed = $true
            }
            if ($profile.PSObject.Properties['languages'] -and $profile.languages -is [System.Collections.IEnumerable]) {
                $ordered = New-Object System.Collections.Generic.List[object]
                $ordered.Add($languageMatch)
                foreach ($language in @($profile.languages)) {
                    if (-not [string]::Equals([string]$language.name, [string]$languageMatch.name, [StringComparison]::OrdinalIgnoreCase)) {
                        $ordered.Add($language)
                    }
                }
                $profile.languages = @($ordered)
                $changed = $true
            }
            if ($changed -and $profile.PSObject.Properties['id']) {
                [void](Invoke-SuiteJsonApi -Name "$Name quality profile language update" -Uri "$Url/$ApiPath/qualityprofile/$([int]$profile.id)" -Method 'PUT' -Headers $headers -Body $profile)
            }
        }
        Write-Host "$Name content language preference set to prefer $Language where supported."
    } catch {
        Write-Warning "$Name content language preference could not be applied. Existing profiles were left usable. $($_.Exception.Message)"
    }
}

function Invoke-StepWithRetry {
    param([string]$Name, [scriptblock]$Operation)
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            & $Operation
            return
        } catch {
            if ($attempt -ge 3) { throw }
            Write-Warning "$Name failed on attempt ${attempt}: $($_.Exception.Message)"
            & (Join-Path $Root 'scripts\Start-Suite.ps1')
            Start-Sleep -Seconds 3
        }
    }
}

function Get-ArrDisplayName {
    param([string]$Name)
    return $Name.Substring(0, 1).ToUpperInvariant() + $Name.Substring(1)
}

function Get-ArrApiPath {
    param([string]$Name)
    switch ($Name) {
        'prowlarr' { return 'api/v1' }
        'lidarr' { return 'api/v1' }
        'readarr' { return 'api/v1' }
        default { return 'api/v3' }
    }
}

function Get-ArrMediaRoot {
    param([string]$Name)
    switch ($Name) {
        'radarr' { return 'media\movies' }
        'sonarr' { return 'media\series' }
        'lidarr' { return 'media\music' }
        'readarr' { return 'media\books' }
        'whisparr' { return 'media\whisparr' }
        default { return '' }
    }
}

$Config = Read-SuiteConfig
$EmuleUrl = Get-ServiceUrl -Name 'emulebb' -Service $Config.services.emulebb
$EmuleKey = [string]$Config.services.emulebb.apiKey

if (Test-SelectedApp -Config $Config -Name 'amutorrent') {
    Initialize-AmutorrentConfig -DataDir (Join-Path $Root 'data\amutorrent') -BindAddress ([string]$Config.services.amutorrent.bindAddress) -Port ([int]$Config.services.amutorrent.port) -Username ([string]$Config.credentials.username) -Password ([string]$Config.credentials.password) -EmulebbHost (Get-ServiceClientHost -ServiceName 'emulebb' -Service $Config.services.emulebb) -EmulebbPort ([int]$Config.services.emulebb.port) -EmulebbApiKey $EmuleKey
}
& (Join-Path $Root 'scripts\Start-Suite.ps1')
Wait-Json -Name 'eMuleBB' -Uri "$EmuleUrl/api/v1/app" -Headers @{ 'X-API-Key' = $EmuleKey }

if (Test-SelectedApp -Config $Config -Name 'amutorrent') {
    $AmutorrentUrl = Get-ServiceUrl -Name 'amutorrent' -Service $Config.services.amutorrent
    Wait-Json -Name 'aMuTorrent' -Uri "$AmutorrentUrl/api/auth/status"
    Invoke-StepWithRetry -Name 'aMuTorrent registration' -Operation {
        & (Join-Path $Root 'apps\eMuleBB\scripts\Register-aMuTorrent.ps1') -Action Register -AmutorrentUrl $AmutorrentUrl -AmutorrentApiKey '' -AmutorrentUsername ([string]$Config.credentials.username) -AmutorrentPassword ([string]$Config.credentials.password) -EmulebbBaseUrl $EmuleUrl -EmulebbApiKey $EmuleKey -InstanceName 'eMuleBB Suite' -InstanceId 'emulebb-suite' -NoRetry
    }
}

$selectedArr = @(@($Config.selectedApps) | Where-Object { @('prowlarr', 'radarr', 'sonarr', 'lidarr', 'readarr', 'whisparr') -contains $_ })
if (@($selectedArr).Count -gt 0) {
    $arrUrls = @{}
    $suiteAppsManifest = Join-Path $Root 'config\suite-apps.json'
    foreach ($arrName in $selectedArr) {
        $arrUrls[$arrName] = Get-ServiceUrl -Name $arrName -Service $Config.services.$arrName
        $display = Get-ArrDisplayName -Name $arrName
        $apiPath = Get-ArrApiPath -Name $arrName
        Wait-Json -Name $display -Uri "$($arrUrls[$arrName])/$apiPath/system/status" -Headers @{ 'X-Api-Key' = [string]$Config.services.$arrName.apiKey }
        Invoke-StepWithRetry -Name "$display web login setup" -Operation {
            Set-ArrHostCredentials -Name $display -Url $arrUrls[$arrName] -ApiPath $apiPath -ApiKey ([string]$Config.services.$arrName.apiKey) -Language ([string]$Config.language.arrUiLanguage)
        }
        $mediaRoot = Get-ArrMediaRoot -Name $arrName
        if (-not [string]::IsNullOrWhiteSpace($mediaRoot)) {
            Invoke-StepWithRetry -Name "$display root folder setup" -Operation {
                Ensure-ArrRootFolder -Name $display -Url $arrUrls[$arrName] -ApiPath $apiPath -ApiKey ([string]$Config.services.$arrName.apiKey) -Path (Join-Path $Root $mediaRoot)
            }
            Invoke-StepWithRetry -Name "$display content language preference" -Operation {
                Set-ArrPreferredContentLanguage -Name $display -Url $arrUrls[$arrName] -ApiPath $apiPath -ApiKey ([string]$Config.services.$arrName.apiKey) -Language ([string]$Config.language.arrContentLanguage)
            }
        }
    }

    if (Test-SelectedApp -Config $Config -Name 'prowlarr') {
        Invoke-StepWithRetry -Name 'Prowlarr registration' -Operation {
            & (Join-Path $Root 'apps\eMuleBB\scripts\Register-Prowlarr.ps1') -Action Register -ProwlarrUrl $arrUrls['prowlarr'] -ProwlarrApiKey ([string]$Config.services.prowlarr.apiKey) -EmulebbBaseUrl $EmuleUrl -EmulebbApiKey $EmuleKey -IndexerName 'eMuleBB Suite' -AppProfileName 'eMuleBB Suite' -NoRetry
        }
        foreach ($arrName in @($selectedArr | Where-Object { $_ -ne 'prowlarr' })) {
            $display = Get-ArrDisplayName -Name $arrName
            Invoke-StepWithRetry -Name "$display registration" -Operation {
                $args = @{
                    Action = 'Register'
                    Target = $display
                    EmulebbBaseUrl = $EmuleUrl
                    EmulebbApiKey = $EmuleKey
                    EmulebbCategoryPath = (Join-Path $Root "downloads\$arrName")
                    ProwlarrUrl = $arrUrls['prowlarr']
                    ProwlarrApiKey = [string]$Config.services.prowlarr.apiKey
                    SuiteAppsManifest = $suiteAppsManifest
                    DownloadClientName = 'eMuleBB Suite'
                    SkipProwlarrSync = $true
                    NoRetry = $true
                }
                $args["${display}Url"] = $arrUrls[$arrName]
                $args["${display}ApiKey"] = [string]$Config.services.$arrName.apiKey
                & (Join-Path $Root 'apps\eMuleBB\scripts\Register-ArrStack.ps1') @args
            }
        }
        Invoke-StepWithRetry -Name 'Prowlarr application sync' -Operation {
            & (Join-Path $Root 'apps\eMuleBB\scripts\Register-ArrStack.ps1') -SyncProwlarrOnly -ProwlarrUrl $arrUrls['prowlarr'] -ProwlarrApiKey ([string]$Config.services.prowlarr.apiKey) -SuiteAppsManifest $suiteAppsManifest -NoRetry
        }
    }
}
