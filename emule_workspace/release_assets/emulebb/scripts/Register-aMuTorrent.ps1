#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Action,
    [string]$AmutorrentUrl,
    [string]$AmutorrentApiKey,
    [string]$EmulebbBaseUrl,
    [string]$EmulebbApiKey,
    [string]$InstanceName = 'eMuleBB',
    [string]$InstanceId,
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
        if ($normalized -eq 'register' -or $normalized -eq 'repair' -or $normalized -eq 'r') { return 'Register' }
        if ($normalized -eq 'unregister' -or $normalized -eq 'u') { return 'Unregister' }
        throw "Action must be Register or Unregister, not '$Value'."
    }
    while ($true) {
        $answer = Read-Host 'Action [R]egister/repair/[U]nregister (default Register)'
        if ([string]::IsNullOrWhiteSpace($answer)) { return 'Register' }
        $normalized = $answer.Trim().ToLowerInvariant()
        if ($normalized.StartsWith('r')) { return 'Register' }
        if ($normalized.StartsWith('u')) { return 'Unregister' }
        Write-Host 'Enter R to register/repair or U to unregister.' -ForegroundColor Yellow
    }
}

function Read-SecretValue {
    param([string]$Prompt, [string]$Value, [switch]$Optional)
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return Normalize-ArgumentValue -Value $Value
    }
    if ($Optional) {
        # aMuTorrent can run with authentication disabled during local installs
        # and helper E2E tests, so an explicit blank admin key must stay blank
        # instead of falling through to an interactive secret prompt.
        return ''
    }
    $secure = Read-Host $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
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

function Invoke-AmutorrentApi {
    param(
        [string]$BaseUrl,
        [string]$ApiKey,
        [string]$Path,
        [string]$Method = 'GET',
        $Body = $null
    )
    $headers = @{}
    if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
        $headers['X-API-Key'] = $ApiKey
    }
    $uri = (Normalize-HttpBaseUrl -Value $BaseUrl -Name 'AmutorrentUrl') + $Path
    try {
        if ($null -eq $Body) {
            return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -TimeoutSec 90 -ErrorAction Stop
        }
        $json = $Body | ConvertTo-Json -Depth 40
        return Invoke-RestMethod -Uri $uri -Method $Method -Headers $headers -Body $json -ContentType 'application/json; charset=utf-8' -TimeoutSec 90 -ErrorAction Stop
    } catch {
        $statusCode = Get-HttpStatusCode -Exception $_.Exception
        if ($statusCode -eq 401 -or $statusCode -eq 403) {
            throw "aMuTorrent rejected the request. Use an admin user's API key from Settings > User Management."
        }
        throw
    }
}

function Remove-PropertyIfPresent {
    param($Target, [string]$Name)
    if ($null -ne $Target -and $null -ne $Target.PSObject.Properties[$Name]) {
        $Target.PSObject.Properties.Remove($Name)
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

function Copy-JsonObject {
    param($Value)
    return ($Value | ConvertTo-Json -Depth 40 | ConvertFrom-Json)
}

function Get-EmulebbConnection {
    param([string]$BaseUrl)
    $normalized = Normalize-HttpBaseUrl -Value $BaseUrl -Name 'EmulebbBaseUrl'
    $uri = [Uri]$normalized
    $path = if ($uri.AbsolutePath -and $uri.AbsolutePath -ne '/') { $uri.AbsolutePath.TrimEnd('/') } else { '' }
    return [PSCustomObject]@{
        BaseUrl = $normalized
        Host = $uri.Host
        Port = [int]$uri.Port
        UseSsl = ($uri.Scheme -eq 'https')
        Path = $path
    }
}

function Get-GeneratedInstanceId {
    param([string]$Host, [int]$Port)
    $safeHost = $Host.Replace(':', '_')
    return "emulebb-$safeHost-$Port"
}

function Get-ClientArray {
    param($Config)
    if ($null -eq $Config.PSObject.Properties['clients'] -or $null -eq $Config.clients) {
        Set-ObjectProperty -Target $Config -Name 'clients' -Value @()
    }
    return @($Config.clients)
}

function Find-EmulebbClientIndex {
    param($Clients, [string]$TargetId, [string]$Name, $Connection)
    for ($i = 0; $i -lt $Clients.Count; ++$i) {
        $client = $Clients[$i]
        if ($client.type -ne 'emulebb') { continue }
        if (-not [string]::IsNullOrWhiteSpace($TargetId) -and $client.id -eq $TargetId) {
            return $i
        }
    }
    for ($i = 0; $i -lt $Clients.Count; ++$i) {
        $client = $Clients[$i]
        if ($client.type -ne 'emulebb') { continue }
        $clientPath = if ($client.path) { ([string]$client.path).TrimEnd('/') } else { '' }
        if ($client.host -eq $Connection.Host -and [int]$client.port -eq $Connection.Port -and [bool]$client.useSsl -eq [bool]$Connection.UseSsl -and $clientPath -eq $Connection.Path) {
            return $i
        }
    }
    for ($i = 0; $i -lt $Clients.Count; ++$i) {
        $client = $Clients[$i]
        if ($client.type -eq 'emulebb' -and $client.name -eq $Name) {
            return $i
        }
    }
    return -1
}

function Assert-CanRepairClient {
    param($Client)
    if ($null -eq $Client) {
        return
    }
    # aMuTorrent treats source:'env' and _fromEnv fields as operator-owned
    # settings. Writing over them via /api/config/save would appear to work for
    # this run, then be reverted by the next process start from EMULEBB_*.
    if ($Client.source -eq 'env') {
        throw 'The matching aMuTorrent eMuleBB client is owned by EMULEBB_* environment variables. Repair those variables or remove the env-owned client before using this script.'
    }
    $fromEnv = $Client._fromEnv
    if ($null -ne $fromEnv) {
        foreach ($field in @('host', 'port', 'apiKey', 'useSsl', 'path')) {
            if ($fromEnv.$field -eq $true) {
                throw "The matching aMuTorrent eMuleBB client has env-owned field '$field'. Repair the matching EMULEBB_* environment variable instead."
            }
        }
    }
}

function New-EmulebbClient {
    param($Connection, [string]$ApiKey, [string]$Name, [string]$Id)
    if ([string]::IsNullOrWhiteSpace($Id)) {
        $Id = Get-GeneratedInstanceId -Host $Connection.Host -Port $Connection.Port
    }
    return [PSCustomObject]@{
        id = $Id
        type = 'emulebb'
        name = $Name
        color = $null
        enabled = $true
        host = $Connection.Host
        port = $Connection.Port
        apiKey = $ApiKey
        useSsl = $Connection.UseSsl
        path = $Connection.Path
    }
}

function Update-EmulebbClient {
    param($Client, $Connection, [string]$ApiKey, [string]$Name, [string]$Id)
    if (-not [string]::IsNullOrWhiteSpace($Id)) {
        Set-ObjectProperty -Target $Client -Name 'id' -Value $Id
    } elseif ([string]::IsNullOrWhiteSpace($Client.id)) {
        Set-ObjectProperty -Target $Client -Name 'id' -Value (Get-GeneratedInstanceId -Host $Connection.Host -Port $Connection.Port)
    }
    Set-ObjectProperty -Target $Client -Name 'type' -Value 'emulebb'
    Set-ObjectProperty -Target $Client -Name 'name' -Value $Name
    Set-ObjectProperty -Target $Client -Name 'enabled' -Value $true
    Set-ObjectProperty -Target $Client -Name 'host' -Value $Connection.Host
    Set-ObjectProperty -Target $Client -Name 'port' -Value $Connection.Port
    Set-ObjectProperty -Target $Client -Name 'apiKey' -Value $ApiKey
    Set-ObjectProperty -Target $Client -Name 'useSsl' -Value $Connection.UseSsl
    Set-ObjectProperty -Target $Client -Name 'path' -Value $Connection.Path
    if ($null -eq $Client.PSObject.Properties['color']) {
        Set-ObjectProperty -Target $Client -Name 'color' -Value $null
    }
    Remove-PropertyIfPresent -Target $Client -Name '_fromEnv'
    return $Client
}

function Test-EmulebbClientThroughAmutorrent {
    param([string]$BaseUrl, [string]$ApiKey, $Connection, [string]$EmuleApiKey)
    $body = @{
        emulebb = @{
            enabled = $true
            host = $Connection.Host
            port = $Connection.Port
            apiKey = $EmuleApiKey
            useSsl = $Connection.UseSsl
            path = $Connection.Path
        }
    }
    $result = Invoke-AmutorrentApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/config/test' -Method 'POST' -Body $body
    if ($result.success -eq $true -and $result.results.emulebb.success -eq $true) {
        Write-Host ('aMuTorrent reached eMuleBB: {0}' -f $result.results.emulebb.message) -ForegroundColor Green
        return
    }
    $message = $result.results.emulebb.error
    if ([string]::IsNullOrWhiteSpace($message)) {
        $message = 'aMuTorrent did not accept the eMuleBB connection test.'
    }
    throw $message
}

function Save-AmutorrentConfig {
    param([string]$BaseUrl, [string]$ApiKey, $Config)
    # /api/config/current adds read-only metadata for the settings UI. The save
    # endpoint validates the complete runtime config, so strip that annotation
    # before posting the edited object back.
    Remove-PropertyIfPresent -Target $Config -Name '_meta'
    [void](Invoke-AmutorrentApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/config/save' -Method 'POST' -Body $Config)
}

function Register-EmulebbClient {
    param([string]$BaseUrl, [string]$ApiKey, [string]$EmuleBaseUrl, [string]$EmuleKey, [string]$Name, [string]$Id)
    $connection = Get-EmulebbConnection -BaseUrl $EmuleBaseUrl
    Test-EmulebbClientThroughAmutorrent -BaseUrl $BaseUrl -ApiKey $ApiKey -Connection $connection -EmuleApiKey $EmuleKey

    $config = Invoke-AmutorrentApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/config/current'
    $config = Copy-JsonObject -Value $config
    $clients = Get-ClientArray -Config $config
    $index = Find-EmulebbClientIndex -Clients $clients -TargetId $Id -Name $Name -Connection $connection
    if ($index -ge 0) {
        Assert-CanRepairClient -Client $clients[$index]
        $clients[$index] = Update-EmulebbClient -Client $clients[$index] -Connection $connection -ApiKey $EmuleKey -Name $Name -Id $Id
        Write-Host ('Repaired aMuTorrent eMuleBB client "{0}".' -f $clients[$index].name) -ForegroundColor Green
    } else {
        $clients += New-EmulebbClient -Connection $connection -ApiKey $EmuleKey -Name $Name -Id $Id
        Write-Host ('Added aMuTorrent eMuleBB client "{0}".' -f $Name) -ForegroundColor Green
    }
    Set-ObjectProperty -Target $config -Name 'clients' -Value @($clients)
    Save-AmutorrentConfig -BaseUrl $BaseUrl -ApiKey $ApiKey -Config $config
}

function Unregister-EmulebbClient {
    param([string]$BaseUrl, [string]$ApiKey, [string]$Name, [string]$Id)
    $config = Invoke-AmutorrentApi -BaseUrl $BaseUrl -ApiKey $ApiKey -Path '/api/config/current'
    $config = Copy-JsonObject -Value $config
    $clients = Get-ClientArray -Config $config
    $index = -1
    if (-not [string]::IsNullOrWhiteSpace($Id)) {
        $index = Find-EmulebbClientIndex -Clients $clients -TargetId $Id -Name $Name -Connection ([PSCustomObject]@{ Host = ''; Port = 0; UseSsl = $false; Path = '' })
    } else {
        for ($i = 0; $i -lt $clients.Count; ++$i) {
            if ($clients[$i].type -eq 'emulebb' -and $clients[$i].name -eq $Name) {
                $index = $i
                break
            }
        }
    }
    if ($index -lt 0) {
        Write-Host ('aMuTorrent eMuleBB client "{0}" is not registered.' -f $Name) -ForegroundColor Yellow
        return
    }

    Assert-CanRepairClient -Client $clients[$index]
    $remaining = @()
    for ($i = 0; $i -lt $clients.Count; ++$i) {
        if ($i -ne $index) {
            $remaining += $clients[$i]
        }
    }
    $enabledCount = 0
    foreach ($client in $remaining) {
        if ($client.enabled -ne $false) {
            ++$enabledCount
        }
    }
    # aMuTorrent rejects configs with no enabled download client. Failing here
    # keeps unregister repairable instead of saving an unusable configuration.
    if ($enabledCount -le 0) {
        throw 'Refusing to unregister the last enabled aMuTorrent download client.'
    }
    Set-ObjectProperty -Target $config -Name 'clients' -Value @($remaining)
    Save-AmutorrentConfig -BaseUrl $BaseUrl -ApiKey $ApiKey -Config $config
    Write-Host ('Unregistered aMuTorrent eMuleBB client "{0}".' -f $Name) -ForegroundColor Green
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
                exit 1
            }
        }
    } while ($true)
}

$Action = Read-ActionValue -Value $Action
Write-Host ('eMuleBB aMuTorrent Integration - {0}' -f $Action) -ForegroundColor Cyan
$AmutorrentUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'aMuTorrent URL (example http://127.0.0.1:4000)' -Value $AmutorrentUrl) -Name 'AmutorrentUrl'
$AmutorrentApiKey = Read-SecretValue -Prompt 'aMuTorrent admin API key (blank only when auth is disabled)' -Value $AmutorrentApiKey -Optional
$InstanceName = Read-RequiredValue -Prompt 'aMuTorrent eMuleBB instance name' -Value $InstanceName
$InstanceId = Normalize-ArgumentValue -Value $InstanceId

if ($Action -eq 'Register') {
    $EmulebbBaseUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue -Prompt 'eMuleBB base URL (example http://127.0.0.1:4711)' -Value $EmulebbBaseUrl) -Name 'EmulebbBaseUrl'
    $EmulebbApiKey = Read-SecretValue -Prompt 'eMuleBB API key' -Value $EmulebbApiKey
}

Run-TargetWithRetry -Name "aMuTorrent eMuleBB $Action" -NoRetry:$NoRetry -Operation {
    if ($Action -eq 'Unregister') {
        Unregister-EmulebbClient -BaseUrl $AmutorrentUrl -ApiKey $AmutorrentApiKey -Name $InstanceName -Id $InstanceId
    } else {
        Register-EmulebbClient -BaseUrl $AmutorrentUrl -ApiKey $AmutorrentApiKey -EmuleBaseUrl $EmulebbBaseUrl -EmuleKey $EmulebbApiKey -Name $InstanceName -Id $InstanceId
    }
}

Write-Host ('eMuleBB aMuTorrent integration {0} finished.' -f $Action.ToLowerInvariant()) -ForegroundColor Green
exit 0
