#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Bundle = 'Full',

    [string]$InstallRoot = 'C:\eMuleBBSuite',

    [string]$Version = '0.7.3-rc.1',

    [ValidateSet('x64', 'ARM64')]
    [string]$Platform = 'x64',

    [ValidateSet('Production', 'Development', 'Test')]
    [string]$InstallKind = 'Production',

    [ValidateSet('Pinned', 'Latest')]
    [string]$DependencyChannel = 'Pinned',

    [string]$ReleaseBaseUrl,
    [string]$AmutorrentReleaseBaseUrl,
    [string]$AmutorrentVersion,
    [string]$EmulebbPackageZip,
    [string]$EmulebbPackageManifest,
    [string]$AmutorrentPackageZip,
    [string]$AmutorrentPackageManifest,
    [string]$NodeBaseUrl,
    [string]$DependencyManifest,
    [string]$ImportProfileDir,
    [string]$EmulebbPdbPath,
    [ValidateSet('standard', 'diagnostics')]
    [string]$EmulebbPackageFlavor = 'standard',

    [string]$ConfigFile,

    [string]$ControlBindAddress = $env:X_LOCAL_IP,
    [string]$EmulebbBindAddress,
    [string]$AmutorrentBindAddress,
    [string]$ProwlarrBindAddress,
    [string]$RadarrBindAddress,
    [string]$SonarrBindAddress,

    [string]$SuiteUsername = 'admin',
    [string]$SuitePassword,

    [ValidateRange(0, 65535)]
    [int]$EmulebbPort = 0,
    [ValidateRange(0, 65535)]
    [int]$AmutorrentPort = 0,
    [ValidateRange(0, 65535)]
    [int]$ProwlarrPort = 0,
    [ValidateRange(0, 65535)]
    [int]$RadarrPort = 0,
    [ValidateRange(0, 65535)]
    [int]$SonarrPort = 0,

    [string]$P2PBindInterface,

    [switch]$AllowRemoteServiceBind,
    [switch]$NonInteractive,
    [switch]$DryRun,
    [switch]$Force,
    [switch]$NoStart,
    [switch]$KeepDownloads
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Enable-Tls12 {
    try {
        $tls12 = [Net.SecurityProtocolType]::Tls12
        if (([Net.ServicePointManager]::SecurityProtocol -band $tls12) -ne $tls12) {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor $tls12
        }
    } catch {
        Write-Warning "Could not enable TLS 1.2 for HTTPS downloads. If downloads fail, download the ZIP assets in a browser and pass the local package parameters. $($_.Exception.Message)"
    }
}

Enable-Tls12

if ($Bundle -like '-*') {
    throw "Install-eMuleBBSuite.ps1 was invoked with positional parameter strings. Call it with named parameters, for example -Bundle Full, not an argv string array."
}
$script:InstallerBoundParameters = $PSBoundParameters

$AutoPortRangeStart = 54000
$AutoPortRangeEnd = 59999
$NodeVersion = 'v24.15.0'
$MinimumNodeMajor = 24
$NodeArchives = @{
    x64 = @{
        FileName = 'node-v24.15.0-win-x64.zip'
        Sha256 = 'cc5149eabd53779ce1e7bdc5401643622d0c7e6800ade18928a767e940bb0e62'
    }
    ARM64 = @{
        FileName = 'node-v24.15.0-win-arm64.zip'
        Sha256 = 'c9eb7402eda26e2ba7e44b6727fc85a8de56c5095b1f71ebd3062892211aa116'
    }
}
$PinnedDependencies = @{
    prowlarr = @{
        Repo = 'Prowlarr/Prowlarr'
        Tag = 'v2.3.5.5327'
        Pattern = 'windows(?:-core)?-x64\.zip$'
        Exe = 'Prowlarr.exe'
        Url = 'https://github.com/Prowlarr/Prowlarr/releases/download/v2.3.5.5327/Prowlarr.master.2.3.5.5327.windows-core-x64.zip'
        Sha256 = '9d388c476edfe579439830dc87f05fc50c86fa0dce80802726832c72088e731b'
    }
    radarr = @{
        Repo = 'Radarr/Radarr'
        Tag = 'v6.1.1.10360'
        Pattern = 'windows(?:-core)?-x64\.zip$'
        Exe = 'Radarr.exe'
        Url = 'https://github.com/Radarr/Radarr/releases/download/v6.1.1.10360/Radarr.master.6.1.1.10360.windows-core-x64.zip'
        Sha256 = 'cc4fdffc4a82a3805e53aa9c016749fd17247eb21dd6764b1b53ced471695bb7'
    }
    sonarr = @{
        Repo = 'Sonarr/Sonarr'
        Tag = 'v4.0.17.2952'
        Pattern = 'win(?:dows)?(?:-core)?-x64\.zip$'
        Exe = 'Sonarr.exe'
        Url = 'https://github.com/Sonarr/Sonarr/releases/download/v4.0.17.2952/Sonarr.main.4.0.17.2952.win-x64.zip'
        Sha256 = '19a81e69dedd8d317b5fa8a1a9c48d63bc3b3f3ba87b84c94ff6d75b1803e419'
    }
}

function Write-Step {
    param([string]$Message)
    Write-Host "[eMuleBB suite] $Message"
}

function Assert-NoSpaces {
    param([string]$Path)
    if ($Path -match '\s') {
        throw "InstallRoot must not contain spaces for v1 suite installs: $Path. Choose a short folder such as C:\eMuleBBSuite or C:\eMuleBB, not C:\Program Files\... or a path under a user profile with spaces."
    }
}

function Assert-InstallRootValue {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'InstallRoot is required. Pass -InstallRoot C:\eMuleBBSuite or choose a short absolute folder in the installer wizard.'
    }
    if ($Path -match '[<>|"*?]') {
        throw "InstallRoot contains characters Windows cannot use in folder names: $Path. Choose a short absolute folder such as C:\eMuleBBSuite or C:\eMuleBB."
    }
    $root = [IO.Path]::GetPathRoot($Path)
    if ([string]::IsNullOrWhiteSpace($root) -or -not [IO.Path]::IsPathRooted($Path) -or $root -notmatch '^[A-Za-z]:\\$') {
        throw "InstallRoot must be an absolute drive path such as C:\eMuleBBSuite or D:\eMuleBB, not '$Path'."
    }
}

function New-Secret {
    param([int]$Length = 24)
    $alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    $result = New-Object System.Text.StringBuilder
    $buffer = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        while ($result.Length -lt $Length) {
            $rng.GetBytes($buffer)
            foreach ($byte in $buffer) {
                if ($byte -ge 248) {
                    continue
                }
                [void]$result.Append($alphabet[$byte % $alphabet.Length])
                if ($result.Length -eq $Length) {
                    break
                }
            }
        }
    } finally {
        $rng.Dispose()
    }
    return $result.ToString()
}

function Assert-FixedSecret {
    param([string]$Name, [string]$Value)
    if ($Value -notmatch '^[A-Za-z0-9]{24}$') {
        throw "$Name must be exactly 24 alphanumeric characters."
    }
}

function New-SuitePassword {
    return New-Secret
}

function New-ApiKey {
    return New-Secret -Length 24
}

function Resolve-Secret {
    param([string]$Value, [string]$Name = 'Secret')
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return New-Secret
    }
    $trimmed = $Value.Trim()
    Assert-FixedSecret -Name $Name -Value $trimmed
    return $trimmed
}

function Resolve-ApiKey {
    param([string]$Value, [string]$Name)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return New-ApiKey
    }
    $trimmed = $Value.Trim()
    if ($trimmed -notmatch '^[A-Za-z0-9]{24}$') {
        throw "$Name must be exactly 24 alphanumeric characters, or blank to generate a new key."
    }
    return $trimmed
}

function Test-VpnLikeInterfaceName {
    param([string]$Name)
    $lowered = ([string]$Name).ToLowerInvariant()
    foreach ($token in @('vpn', 'hide.me', 'tap', 'tun', 'wireguard', 'tailscale')) {
        if ($lowered.Contains($token)) {
            return $true
        }
    }
    return $false
}

function Test-AutoLanIPv4Address {
    param([string]$Address)
    if ([string]::IsNullOrWhiteSpace($Address)) {
        return $false
    }
    try {
        $parsed = [Net.IPAddress]::Parse($Address)
    } catch {
        return $false
    }
    if ($parsed.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        return $false
    }
    $bytes = $parsed.GetAddressBytes()
    if ($bytes[0] -eq 10) {
        return $true
    }
    if ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) {
        return $true
    }
    if ($bytes[0] -eq 192 -and $bytes[1] -eq 168) {
        return $true
    }
    return $false
}

function ConvertTo-IPv4SubnetMask {
    param([Nullable[int]]$PrefixLength)
    if ($null -eq $PrefixLength -or $PrefixLength -lt 0 -or $PrefixLength -gt 32) {
        return ''
    }
    $bits = ('1' * $PrefixLength) + ('0' * (32 - $PrefixLength))
    $octets = @()
    for ($offset = 0; $offset -lt 32; $offset += 8) {
        $octets += [Convert]::ToInt32($bits.Substring($offset, 8), 2)
    }
    return ($octets -join '.')
}

function Get-LocalIPv4InterfaceInfos {
    $candidates = @()
    try {
        $candidates += @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*' } |
            ForEach-Object {
                [pscustomobject]@{
                    InterfaceAlias = [string]$_.InterfaceAlias
                    IPAddress = [string]$_.IPAddress
                    PrefixLength = [int]$_.PrefixLength
                    IsVpnLike = [bool](Test-VpnLikeInterfaceName -Name $_.InterfaceAlias)
                }
            })
    } catch {
        try {
            $candidates += @([System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
                Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
                ForEach-Object {
                    [pscustomobject]@{
                        InterfaceAlias = ''
                        IPAddress = [string]$_.IPAddressToString
                        PrefixLength = $null
                        IsVpnLike = $false
                    }
                })
        } catch {
        }
    }
    return @($candidates)
}

function Get-AutoLanBindAddress {
    $privateCandidates = @(Get-LocalIPv4InterfaceInfos | Where-Object { Test-AutoLanIPv4Address -Address $_.IPAddress })
    foreach ($candidate in @($privateCandidates | Where-Object { -not $_.IsVpnLike })) {
        return $candidate.IPAddress
    }
    foreach ($candidate in $privateCandidates) {
        if ($candidate.IsVpnLike) {
            return $candidate.IPAddress
        }
    }
    return ''
}

function Get-DefaultControlBindAddress {
    if (-not [string]::IsNullOrWhiteSpace($env:X_LOCAL_IP)) {
        return $env:X_LOCAL_IP.Trim()
    }
    $lanAddress = Get-AutoLanBindAddress
    if (-not [string]::IsNullOrWhiteSpace($lanAddress)) {
        return $lanAddress
    }
    return '127.0.0.1'
}

function Get-EmulebbExecutableNameForFlavor {
    param([string]$PackageFlavor)
    if ($PackageFlavor -eq 'diagnostics') {
        return 'emulebb-diagnostics.exe'
    }
    return 'emulebb.exe'
}

function Get-EmulebbPdbFileName {
    param([string]$ExecutableName)
    return [IO.Path]::ChangeExtension($ExecutableName, '.pdb')
}

function Assert-EmulebbExecutableName {
    param([string]$PackageFlavor, [string]$ExecutableName)
    if ([string]::IsNullOrWhiteSpace($ExecutableName)) {
        throw 'EmulebbExecutableName must not be empty.'
    }
    if ($ExecutableName -ne [IO.Path]::GetFileName($ExecutableName)) {
        throw "EmulebbExecutableName must be a file name, not a path: $ExecutableName"
    }
    if ([IO.Path]::GetExtension($ExecutableName) -ne '.exe') {
        throw "EmulebbExecutableName must end with .exe: $ExecutableName"
    }
    $expectedExecutableName = Get-EmulebbExecutableNameForFlavor -PackageFlavor $PackageFlavor
    if ($ExecutableName -ne $expectedExecutableName) {
        throw "EmulebbExecutableName must be $expectedExecutableName for package flavor $PackageFlavor."
    }
}

function Get-LocalPackageVersionFromZipName {
    param([string]$ZipPath, [string]$PackageName)
    if ([string]::IsNullOrWhiteSpace($ZipPath)) {
        return ''
    }
    $name = [IO.Path]::GetFileName($ZipPath)
    if ($PackageName -eq 'eMuleBB' -and $name -match '^emulebb-(.+?)(?:-diagnostics)?-(?:x64|ARM64)\.zip$') {
        return $Matches[1]
    }
    if ($PackageName -eq 'aMuTorrent' -and $name -match '^emulebb-(.+?)-amutorrent-x64\.zip$') {
        return $Matches[1]
    }
    throw "Cannot infer $PackageName package version from local ZIP name: $name. Pass -Version or -AmutorrentVersion explicitly."
}

function New-SuiteConfig {
    $controlBind = Resolve-OptionalValue -Value $ControlBindAddress -Default (Get-DefaultControlBindAddress)
    $resolvedVersion = $Version
    if (-not $script:InstallerBoundParameters.ContainsKey('Version')) {
        $inferredVersion = Get-LocalPackageVersionFromZipName -ZipPath $EmulebbPackageZip -PackageName 'eMuleBB'
        if (-not [string]::IsNullOrWhiteSpace($inferredVersion)) {
            $resolvedVersion = $inferredVersion
        }
    }
    $resolvedAmutorrentVersion = $AmutorrentVersion
    if (-not $script:InstallerBoundParameters.ContainsKey('AmutorrentVersion')) {
        $inferredAmutorrentVersion = Get-LocalPackageVersionFromZipName -ZipPath $AmutorrentPackageZip -PackageName 'aMuTorrent'
        if (-not [string]::IsNullOrWhiteSpace($inferredAmutorrentVersion)) {
            $resolvedAmutorrentVersion = $inferredAmutorrentVersion
        }
    }
    $config = [ordered]@{
        schema = 'emulebb.suite-config.v1'
        bundle = $Bundle
        version = $resolvedVersion
        platform = $Platform
        installKind = $InstallKind
        installRoot = $InstallRoot
        dependencyChannel = $DependencyChannel
        releaseBaseUrl = $ReleaseBaseUrl
        amutorrentReleaseBaseUrl = $AmutorrentReleaseBaseUrl
        amutorrentVersion = $resolvedAmutorrentVersion
        packageSources = [ordered]@{
            emulebb = [ordered]@{
                zip = $EmulebbPackageZip
                manifest = $EmulebbPackageManifest
            }
            amutorrent = [ordered]@{
                zip = $AmutorrentPackageZip
                manifest = $AmutorrentPackageManifest
            }
        }
        emulebbPackageFlavor = $EmulebbPackageFlavor
        emulebbExecutableName = (Get-EmulebbExecutableNameForFlavor -PackageFlavor $EmulebbPackageFlavor)
        nodeBaseUrl = $NodeBaseUrl
        dependencyManifest = $DependencyManifest
        importProfileDir = $ImportProfileDir
        credentials = [ordered]@{
            username = (Resolve-OptionalValue -Value $SuiteUsername -Default 'admin')
            password = $SuitePassword
        }
        symbols = [ordered]@{
            emulebbPdbPath = $EmulebbPdbPath
        }
        allowRemoteServiceBind = [bool]$AllowRemoteServiceBind
        services = [ordered]@{
            emulebb = [ordered]@{ bindAddress = (Resolve-OptionalValue -Value $EmulebbBindAddress -Default $controlBind); port = $EmulebbPort; apiKey = '' }
            amutorrent = [ordered]@{ bindAddress = (Resolve-OptionalValue -Value $AmutorrentBindAddress -Default $controlBind); port = $AmutorrentPort }
            prowlarr = [ordered]@{ bindAddress = (Resolve-OptionalValue -Value $ProwlarrBindAddress -Default $controlBind); port = $ProwlarrPort; apiKey = '' }
            radarr = [ordered]@{ bindAddress = (Resolve-OptionalValue -Value $RadarrBindAddress -Default $controlBind); port = $RadarrPort; apiKey = '' }
            sonarr = [ordered]@{ bindAddress = (Resolve-OptionalValue -Value $SonarrBindAddress -Default $controlBind); port = $SonarrPort; apiKey = '' }
        }
        p2p = [ordered]@{
            bindInterface = (Resolve-OptionalValue -Value $P2PBindInterface -Default '')
            blockNetworkWhenBindUnavailableAtStartup = $false
            networkGuardMode = 'Off'
            networkGuardAllowedCIDRs = ''
        }
    }
    return $config
}

function Resolve-OptionalValue {
    param([string]$Value, [string]$Default)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Default
    }
    return $Value.Trim()
}

function ConvertTo-Hashtable {
    param([object]$Value)
    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $result = [ordered]@{}
        foreach ($key in $Value.Keys) {
            $result[$key] = ConvertTo-Hashtable $Value[$key]
        }
        return $result
    }
    if ($Value -is [pscustomobject]) {
        $result = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) {
            $result[$property.Name] = ConvertTo-Hashtable $property.Value
        }
        return $result
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        $items = @()
        foreach ($item in $Value) {
            $items += ,(ConvertTo-Hashtable $item)
        }
        return $items
    }
    return $Value
}

function Merge-Hashtable {
    param([System.Collections.IDictionary]$Target, [System.Collections.IDictionary]$Source)
    foreach ($key in $Source.Keys) {
        if ($Target.Contains($key) -and $Target[$key] -is [System.Collections.IDictionary] -and $Source[$key] -is [System.Collections.IDictionary]) {
            Merge-Hashtable -Target $Target[$key] -Source $Source[$key]
        } else {
            $Target[$key] = $Source[$key]
        }
    }
}

function Get-SuiteServiceNames {
    return @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')
}

function ConvertTo-BindIPAddress {
    param([string]$BindAddress)
    if ([string]::IsNullOrWhiteSpace($BindAddress) -or $BindAddress -eq '0.0.0.0') {
        return [Net.IPAddress]::Any
    }
    if ($BindAddress -eq '::') {
        return [Net.IPAddress]::IPv6Any
    }
    try {
        return [Net.IPAddress]::Parse($BindAddress)
    } catch {
        throw "Bind address must be an IP address for automatic port probing: $BindAddress"
    }
}

function Test-TcpPortAvailable {
    param([string]$BindAddress, [int]$Port)
    if ($Port -lt 1 -or $Port -gt 65535) {
        return $false
    }
    $listener = $null
    try {
        $ipAddress = ConvertTo-BindIPAddress -BindAddress $BindAddress
        $listener = [Net.Sockets.TcpListener]::new($ipAddress, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Resolve-ServicePorts {
    param([hashtable]$Config)
    $serviceNames = @(Get-SuiteServiceNames)
    $explicitPorts = @{}
    foreach ($serviceName in $serviceNames) {
        $service = $Config.services[$serviceName]
        $port = [int]$service.port
        if ($port -gt 0) {
            if ($explicitPorts.ContainsKey($port)) {
                throw "Duplicate configured service port $port for $($explicitPorts[$port]) and $serviceName."
            }
            if (-not (Test-TcpPortAvailable -BindAddress ([string]$service.bindAddress) -Port $port)) {
                throw "Configured $serviceName port $port is not free on $($service.bindAddress)."
            }
            $explicitPorts[$port] = $serviceName
        }
    }

    $autoServiceNames = @($serviceNames | Where-Object { [int]$Config.services[$_].port -le 0 })
    if ($autoServiceNames.Count -eq 0) {
        return
    }

    for ($basePort = $AutoPortRangeStart; $basePort -le ($AutoPortRangeEnd - $autoServiceNames.Count + 1); ++$basePort) {
        $candidatePorts = @()
        for ($offset = 0; $offset -lt $autoServiceNames.Count; ++$offset) {
            $candidatePorts += ($basePort + $offset)
        }
        $available = $true
        for ($index = 0; $index -lt $autoServiceNames.Count; ++$index) {
            $serviceName = $autoServiceNames[$index]
            $port = $candidatePorts[$index]
            if ($explicitPorts.ContainsKey($port) -or -not (Test-TcpPortAvailable -BindAddress ([string]$Config.services[$serviceName].bindAddress) -Port $port)) {
                $available = $false
                break
            }
        }
        if ($available) {
            for ($index = 0; $index -lt $autoServiceNames.Count; ++$index) {
                $Config.services[$autoServiceNames[$index]].port = $candidatePorts[$index]
            }
            Write-Step "Selected service ports $($candidatePorts -join ', ') from free high-port range $AutoPortRangeStart-$AutoPortRangeEnd"
            return
        }
    }
    throw "Could not find a free high-port range in $AutoPortRangeStart-$AutoPortRangeEnd for $($autoServiceNames.Count) service(s)."
}

function Resolve-SuiteConfig {
    $config = New-SuiteConfig
    if (-not [string]::IsNullOrWhiteSpace($ConfigFile)) {
        if (-not (Test-Path -LiteralPath $ConfigFile)) {
            throw "ConfigFile is missing: $ConfigFile"
        }
        $fileConfig = ConvertTo-Hashtable (Get-Content -Raw -LiteralPath $ConfigFile | ConvertFrom-Json)
        Merge-Hashtable -Target $config -Source $fileConfig
    }

    foreach ($entry in @(
        @('Bundle', { param($c, $v) $c.bundle = $v }),
        @('InstallRoot', { param($c, $v) $c.installRoot = $v }),
        @('Version', { param($c, $v) $c.version = $v }),
        @('Platform', { param($c, $v) $c.platform = $v }),
        @('InstallKind', { param($c, $v) $c.installKind = $v }),
        @('DependencyChannel', { param($c, $v) $c.dependencyChannel = $v }),
        @('ReleaseBaseUrl', { param($c, $v) $c.releaseBaseUrl = $v }),
        @('AmutorrentReleaseBaseUrl', { param($c, $v) $c.amutorrentReleaseBaseUrl = $v }),
        @('AmutorrentVersion', { param($c, $v) $c.amutorrentVersion = $v }),
        @('EmulebbPackageZip', { param($c, $v) $c.packageSources.emulebb.zip = $v }),
        @('EmulebbPackageManifest', { param($c, $v) $c.packageSources.emulebb.manifest = $v }),
        @('AmutorrentPackageZip', { param($c, $v) $c.packageSources.amutorrent.zip = $v }),
        @('AmutorrentPackageManifest', { param($c, $v) $c.packageSources.amutorrent.manifest = $v }),
        @('NodeBaseUrl', { param($c, $v) $c.nodeBaseUrl = $v }),
        @('DependencyManifest', { param($c, $v) $c.dependencyManifest = $v }),
        @('ImportProfileDir', { param($c, $v) $c.importProfileDir = $v }),
        @('EmulebbPdbPath', { param($c, $v) $c.symbols.emulebbPdbPath = $v }),
        @('EmulebbPackageFlavor', { param($c, $v) $c.emulebbPackageFlavor = $v }),
        @('ControlBindAddress', {
            param($c, $v)
            foreach ($serviceName in @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')) {
                $c.services[$serviceName].bindAddress = $v
            }
        }),
        @('EmulebbBindAddress', { param($c, $v) $c.services.emulebb.bindAddress = $v }),
        @('AmutorrentBindAddress', { param($c, $v) $c.services.amutorrent.bindAddress = $v }),
        @('ProwlarrBindAddress', { param($c, $v) $c.services.prowlarr.bindAddress = $v }),
        @('RadarrBindAddress', { param($c, $v) $c.services.radarr.bindAddress = $v }),
        @('SonarrBindAddress', { param($c, $v) $c.services.sonarr.bindAddress = $v }),
        @('EmulebbPort', { param($c, $v) $c.services.emulebb.port = $v }),
        @('AmutorrentPort', { param($c, $v) $c.services.amutorrent.port = $v }),
        @('ProwlarrPort', { param($c, $v) $c.services.prowlarr.port = $v }),
        @('RadarrPort', { param($c, $v) $c.services.radarr.port = $v }),
        @('SonarrPort', { param($c, $v) $c.services.sonarr.port = $v }),
        @('P2PBindInterface', { param($c, $v) $c.p2p.bindInterface = $v })
    )) {
        $name = [string]$entry[0]
        if ($script:InstallerBoundParameters.ContainsKey($name)) {
            & $entry[1] $config $script:InstallerBoundParameters[$name]
        }
    }
    if ($script:InstallerBoundParameters.ContainsKey('AllowRemoteServiceBind')) {
        $config.allowRemoteServiceBind = [bool]$AllowRemoteServiceBind
    }
    $config.emulebbExecutableName = Get-EmulebbExecutableNameForFlavor -PackageFlavor ([string]$config.emulebbPackageFlavor)
    return $config
}

function Test-InteractiveConsole {
    try {
        return -not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected
    } catch {
        return $false
    }
}

function Read-WizardValue {
    param([string]$Prompt, [string]$Default)
    $suffix = if ([string]::IsNullOrWhiteSpace($Default)) { '' } else { " [$Default]" }
    $value = Read-Host "$Prompt$suffix"
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value.Trim()
}

function Read-WizardPortValue {
    param([string]$Prompt, [int]$Default)
    while ($true) {
        $raw = Read-WizardValue -Prompt "$Prompt (0=auto, 1-65535=explicit)" -Default ([string]$Default)
        $port = 0
        if ([int]::TryParse($raw, [ref]$port) -and $port -ge 0 -and $port -le 65535) {
            return $port
        }
        Write-Host 'Enter a number from 0 to 65535. Use 0 to auto-select a free suite port.' -ForegroundColor Yellow
    }
}

function Read-WizardChoice {
    param([string]$Prompt, [string[]]$Choices, [int]$DefaultIndex = 0)
    while ($true) {
        Write-Host ''
        Write-Host $Prompt
        for ($i = 0; $i -lt $Choices.Count; $i++) {
            $marker = if ($i -eq $DefaultIndex) { '*' } else { ' ' }
            Write-Host ("  {0}{1}. {2}" -f $marker, ($i + 1), $Choices[$i])
        }
        $raw = Read-Host "Select 1-$($Choices.Count), B=back, Q=quit"
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $DefaultIndex
        }
        if ($raw -match '^[Qq]$') {
            throw 'Installer cancelled.'
        }
        if ($raw -match '^[Bb]$') {
            return -1
        }
        $selected = 0
        if ([int]::TryParse($raw, [ref]$selected) -and $selected -ge 1 -and $selected -le $Choices.Count) {
            return ($selected - 1)
        }
        Write-Host 'Invalid selection.'
    }
}

function Get-BindableInterfaceOptions {
    $options = @()
    foreach ($info in @(Get-LocalIPv4InterfaceInfos | Sort-Object InterfaceAlias, IPAddress)) {
        if ([string]::IsNullOrWhiteSpace($info.InterfaceAlias)) {
            continue
        }
        $prefix = if ($null -ne $info.PrefixLength) { "/$($info.PrefixLength)" } else { '' }
        $mask = ConvertTo-IPv4SubnetMask -PrefixLength $info.PrefixLength
        $maskText = if ([string]::IsNullOrWhiteSpace($mask)) { '' } else { " ($mask)" }
        $vpnText = if ($info.IsVpnLike) { ' [VPN-like]' } else { '' }
        $options += [pscustomobject]@{
            InterfaceAlias = [string]$info.InterfaceAlias
            Label = ('{0} - {1}{2}{3}{4}' -f $info.InterfaceAlias, $info.IPAddress, $prefix, $maskText, $vpnText)
        }
    }
    return @($options)
}

function Get-BindableInterfaceNames {
    return @(Get-BindableInterfaceOptions | ForEach-Object { $_.InterfaceAlias } | Sort-Object -Unique)
}

function Invoke-InstallWizard {
    param([hashtable]$Config)
    $step = 0
    while ($step -lt 6) {
        switch ($step) {
            0 {
                $choice = Read-WizardChoice -Prompt 'Bundle' -Choices @('Full suite', 'Controller only', 'Core app only') -DefaultIndex (@('Full', 'Controller', 'Core').IndexOf([string]$Config.bundle))
                if ($choice -lt 0) { $step = [Math]::Max(0, $step - 1); continue }
                $Config.bundle = @('Full', 'Controller', 'Core')[$choice]
                $Config.installRoot = Read-WizardValue -Prompt 'Install root' -Default $Config.installRoot
                $step++
            }
            1 {
                $defaultBind = Get-DefaultControlBindAddress
                $choice = Read-WizardChoice -Prompt 'Control service bind policy' -Choices @("Default local bind ($defaultBind)", 'One custom bind address for all services', 'Per-service bind addresses') -DefaultIndex 0
                if ($choice -lt 0) { $step--; continue }
                if ($choice -eq 0) {
                    foreach ($serviceName in @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')) {
                        $Config.services[$serviceName].bindAddress = $defaultBind
                    }
                } elseif ($choice -eq 1) {
                    $bind = Read-WizardValue -Prompt 'Bind address for all control services' -Default $defaultBind
                    foreach ($serviceName in @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')) {
                        $Config.services[$serviceName].bindAddress = $bind
                    }
                } else {
                    foreach ($serviceName in @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')) {
                        $Config.services[$serviceName].bindAddress = Read-WizardValue -Prompt "$serviceName bind address" -Default $Config.services[$serviceName].bindAddress
                    }
                }
                $Config.allowRemoteServiceBind = Test-HasRemoteServiceBind -Config $Config
                $step++
            }
            2 {
                $interfaceOptions = @(Get-BindableInterfaceOptions)
                $choices = @('No P2P bind')
                $choices += @($interfaceOptions | ForEach-Object { $_.Label })
                $choices += 'Custom interface name'
                $choice = Read-WizardChoice -Prompt 'eMuleBB P2P bind interface' -Choices $choices -DefaultIndex 0
                if ($choice -lt 0) { $step--; continue }
                if ($choice -eq 0) {
                    $Config.p2p.bindInterface = ''
                } elseif ($choice -le $interfaceOptions.Count) {
                    $Config.p2p.bindInterface = $interfaceOptions[$choice - 1].InterfaceAlias
                } else {
                    $Config.p2p.bindInterface = Read-WizardValue -Prompt 'P2P bind interface name' -Default $Config.p2p.bindInterface
                }
                $Config.p2p.blockNetworkWhenBindUnavailableAtStartup = $false
                $Config.p2p.networkGuardMode = 'Off'
                $Config.p2p.networkGuardAllowedCIDRs = ''
                $step++
            }
            3 {
                $choice = Read-WizardChoice -Prompt 'Ports' -Choices @('Use defaults/current values', 'Edit service ports') -DefaultIndex 0
                if ($choice -lt 0) { $step--; continue }
                if ($choice -eq 1) {
                    foreach ($serviceName in @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')) {
                        $Config.services[$serviceName].port = Read-WizardPortValue -Prompt "$serviceName port" -Default ([int]$Config.services[$serviceName].port)
                    }
                }
                $step++
            }
            4 {
                if ([string]::IsNullOrWhiteSpace([string]$Config.dependencyManifest)) {
                    if ($Config.dependencyChannel -eq 'Latest') {
                        Write-Host 'Latest dependency releases require -DependencyManifest with exact URLs and SHA256 hashes. Using pinned dependency versions.' -ForegroundColor Yellow
                        $Config.dependencyChannel = 'Pinned'
                    }
                    Write-Host 'Latest dependency releases are unavailable unless you pass -DependencyManifest. Using pinned dependency versions.' -ForegroundColor Yellow
                    $Config.dependencyChannel = 'Pinned'
                    $step++
                    continue
                }
                $choice = Read-WizardChoice -Prompt 'Dependency resolution' -Choices @('Pinned dependency versions', 'Latest dependency releases') -DefaultIndex $(if ($Config.dependencyChannel -eq 'Latest') { 1 } else { 0 })
                if ($choice -lt 0) { $step--; continue }
                $Config.dependencyChannel = @('Pinned', 'Latest')[$choice]
                $step++
            }
            5 {
                Write-ConfigSummary -Config $Config
                $choice = Read-WizardChoice -Prompt 'Install plan' -Choices @('Install now', 'Back to edit', 'Quit') -DefaultIndex 0
                if ($choice -eq 0) { return }
                if ($choice -eq 1 -or $choice -lt 0) { $step--; continue }
                throw 'Installer cancelled.'
            }
        }
    }
}

function Test-HasRemoteServiceBind {
    param([hashtable]$Config)
    foreach ($serviceName in @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')) {
        $address = [string]$Config.services[$serviceName].bindAddress
        if (-not (Test-LoopbackAddress -Address $address)) {
            return $true
        }
    }
    return $false
}

function Write-ConfigSummary {
    param([hashtable]$Config)
    Write-Host ''
    Write-Host 'Install summary'
    Write-Host "  Bundle: $($Config.bundle)"
    Write-Host "  Root: $($Config.installRoot)"
    Write-Host "  Version/platform: $($Config.version) / $($Config.platform)"
    foreach ($serviceName in @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')) {
        $service = $Config.services[$serviceName]
        Write-Host ("  {0}: {1}:{2}" -f $serviceName, $service.bindAddress, $service.port)
    }
    if ([string]::IsNullOrWhiteSpace($Config.p2p.bindInterface)) {
        Write-Host '  P2P bind interface: none'
    } else {
        Write-Host "  P2P bind interface: $($Config.p2p.bindInterface) (warn-only policy)"
    }
    if (-not [string]::IsNullOrWhiteSpace($Config.importProfileDir)) {
        Write-Host "  Import profile: $($Config.importProfileDir)"
    }
}

function Get-LocalIPv4Addresses {
    $addresses = @('127.0.0.1')
    if (-not [string]::IsNullOrWhiteSpace($env:X_LOCAL_IP)) {
        $addresses += $env:X_LOCAL_IP.Trim()
    }
    try {
        $addresses += @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            ForEach-Object { $_.IPAddress } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    } catch {
        try {
            $addresses += @([System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
                Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
                ForEach-Object { $_.IPAddressToString })
        } catch {
        }
    }
    return @($addresses | Sort-Object -Unique)
}

function Test-LoopbackAddress {
    param([string]$Address)
    return $Address -eq 'localhost' -or $Address -eq '::1' -or $Address -eq '127.0.0.1' -or $Address -match '^127\.'
}

function Assert-ServiceBindAddress {
    param([string]$ServiceName, [string]$Address, [bool]$AllowRemote)
    if ([string]::IsNullOrWhiteSpace($Address)) {
        throw "$ServiceName bind address must not be empty."
    }
    if (Test-LoopbackAddress -Address $Address) {
        return
    }
    if ($Address -eq '0.0.0.0') {
        if (-not $AllowRemote) {
            Write-Warning "$ServiceName bind address $Address exposes the service."
            return
        }
        Write-Warning "$ServiceName will bind to all interfaces."
        return
    }
    $localAddresses = @(Get-LocalIPv4Addresses)
    if ($localAddresses -notcontains $Address) {
        throw "$ServiceName bind address $Address is not a local IPv4 address. Local addresses: $($localAddresses -join ', ')"
    }
    return
}

function Assert-Port {
    param([string]$ServiceName, [int]$Port)
    if ($Port -lt 1 -or $Port -gt 65535) {
        throw "$ServiceName port must be between 1 and 65535: $Port"
    }
}

function Test-PortAvailable {
    param([string]$Address, [int]$Port)
    $listener = $null
    try {
        $ip = if ($Address -eq 'localhost') { [Net.IPAddress]::Parse('127.0.0.1') } elseif ($Address -eq '0.0.0.0') { [Net.IPAddress]::Any } else { [Net.IPAddress]::Parse($Address) }
        $listener = New-Object Net.Sockets.TcpListener($ip, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Assert-SuiteConfig {
    param([hashtable]$Config)
    if (@('Core', 'Controller', 'Full') -notcontains $Config.bundle) {
        throw "Bundle must be Core, Controller, or Full: $($Config.bundle)"
    }
    if (@('x64', 'ARM64') -notcontains $Config.platform) {
        throw "Platform must be x64 or ARM64: $($Config.platform)"
    }
    if (($Config.bundle -eq 'Controller' -or $Config.bundle -eq 'Full') -and $Config.platform -ne 'x64') {
        throw 'Controller and Full bundles are x64-only in v1 because aMuTorrent native node_modules are packaged for the selected Node architecture.'
    }
    if (@('standard', 'diagnostics') -notcontains $Config.emulebbPackageFlavor) {
        throw "EmulebbPackageFlavor must be standard or diagnostics: $($Config.emulebbPackageFlavor)"
    }
    if ($Config.dependencyChannel -eq 'Latest' -and [string]::IsNullOrWhiteSpace([string]$Config.dependencyManifest)) {
        throw 'DependencyChannel Latest requires -DependencyManifest with exact URLs and SHA256 hashes. Use the default pinned dependencies, or pass -DependencyManifest C:\Path\dependencies.json.'
    }
    Assert-EmulebbExecutableName -PackageFlavor ([string]$Config.emulebbPackageFlavor) -ExecutableName ([string]$Config.emulebbExecutableName)
    if ($null -eq $Config.credentials) {
        $Config.credentials = [ordered]@{ username = 'admin'; password = '' }
    }
    if ($null -eq $Config.packageSources) {
        $Config.packageSources = [ordered]@{
            emulebb = [ordered]@{ zip = ''; manifest = '' }
            amutorrent = [ordered]@{ zip = ''; manifest = '' }
        }
    }
    if ([string]::IsNullOrWhiteSpace($Config.credentials.username) -or $Config.credentials.username -notmatch '^[a-zA-Z0-9_]{3,32}$') {
        throw "SuiteUsername must be 3-32 characters and contain only letters, numbers, or underscores: $($Config.credentials.username)"
    }
    foreach ($serviceName in @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')) {
        $service = $Config.services[$serviceName]
        Assert-ServiceBindAddress -ServiceName $serviceName -Address $service.bindAddress -AllowRemote ([bool]$Config.allowRemoteServiceBind)
        Assert-Port -ServiceName $serviceName -Port ([int]$service.port)
    }
    if (-not [string]::IsNullOrWhiteSpace($Config.p2p.bindInterface)) {
        $interfaces = @(Get-BindableInterfaceNames)
        if ($interfaces.Count -gt 0 -and $interfaces -notcontains $Config.p2p.bindInterface) {
            Write-Warning "P2P bind interface '$($Config.p2p.bindInterface)' was not found now. eMuleBB will warn/fallback according to its runtime policy."
        }
        $Config.p2p.blockNetworkWhenBindUnavailableAtStartup = $false
        $Config.p2p.networkGuardMode = 'Off'
        $Config.p2p.networkGuardAllowedCIDRs = ''
    }
    if (-not $DryRun -and -not $Force) {
        foreach ($serviceName in @('emulebb', 'amutorrent', 'prowlarr', 'radarr', 'sonarr')) {
            if (($Config.bundle -eq 'Core' -and $serviceName -ne 'emulebb') -or ($Config.bundle -eq 'Controller' -and @('prowlarr', 'radarr', 'sonarr') -contains $serviceName)) {
                continue
            }
            $service = $Config.services[$serviceName]
            if (-not (Test-PortAvailable -Address $service.bindAddress -Port ([int]$service.port))) {
                throw "$serviceName port is not available on $($service.bindAddress):$($service.port)"
            }
        }
    }
}

function Format-DownloadSize {
    param([long]$Bytes)
    if ($Bytes -ge 1GB) {
        return ('{0:N1} GB' -f ($Bytes / 1GB))
    }
    if ($Bytes -ge 1MB) {
        return ('{0:N1} MB' -f ($Bytes / 1MB))
    }
    if ($Bytes -ge 1KB) {
        return ('{0:N1} KB' -f ($Bytes / 1KB))
    }
    return ('{0} bytes' -f $Bytes)
}

function Invoke-HttpDownload {
    param([string]$Url, [string]$TempPath, [string]$Destination)
    $activity = "Downloading $(Split-Path -Leaf $Destination)"
    Write-Host "  $activity"
    $invokeWebRequestCommand = Get-Command Invoke-WebRequest -ErrorAction SilentlyContinue
    if ($null -ne $invokeWebRequestCommand -and $invokeWebRequestCommand.CommandType -eq 'Function') {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $TempPath
        if (Test-Path -LiteralPath $TempPath) {
            Write-Host ('  Downloaded {0}' -f (Format-DownloadSize -Bytes ([IO.FileInfo]$TempPath).Length))
        }
        return
    }
    $request = [System.Net.HttpWebRequest][System.Net.WebRequest]::Create($Url)
    $request.UserAgent = 'eMuleBB-Suite-Installer'
    $request.AllowAutoRedirect = $true
    $response = $request.GetResponse()
    try {
        $total = [long]$response.ContentLength
        $inputStream = $response.GetResponseStream()
        $outputStream = [System.IO.File]::Open($TempPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try {
            $buffer = New-Object byte[] (1024 * 1024)
            $downloaded = [long]0
            $nextHostReport = (Get-Date).AddSeconds(5)
            do {
                $read = $inputStream.Read($buffer, 0, $buffer.Length)
                if ($read -le 0) {
                    break
                }
                $outputStream.Write($buffer, 0, $read)
                $downloaded += $read
                $now = Get-Date
                if ($total -gt 0) {
                    $percent = [int]([Math]::Min(100, [Math]::Floor(($downloaded * 100.0) / $total)))
                    $status = '{0} of {1} ({2}%)' -f (Format-DownloadSize -Bytes $downloaded), (Format-DownloadSize -Bytes $total), $percent
                    Write-Progress -Activity $activity -Status $status -PercentComplete $percent
                } else {
                    $status = '{0} downloaded' -f (Format-DownloadSize -Bytes $downloaded)
                    Write-Progress -Activity $activity -Status $status
                }
                if ($now -ge $nextHostReport) {
                    Write-Host "  $status"
                    $nextHostReport = $now.AddSeconds(5)
                }
            } while ($true)
            Write-Progress -Activity $activity -Completed
            Write-Host ('  Downloaded {0}' -f (Format-DownloadSize -Bytes $downloaded))
        } finally {
            $outputStream.Dispose()
            if ($null -ne $inputStream) {
                $inputStream.Dispose()
            }
        }
    } finally {
        $response.Dispose()
    }
}

function Invoke-Download {
    param([string]$Url, [string]$Destination)
    if ($DryRun) {
        Write-Step "Would download $Url -> $Destination"
        return
    }
    $parent = Split-Path -Parent $Destination
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $tmp = "$Destination.tmp"
    Remove-Item -Force -LiteralPath $tmp -ErrorAction SilentlyContinue
    $uri = $null
    try {
        if ([Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$uri) -and $uri.IsFile) {
            Copy-Item -Force -LiteralPath $uri.LocalPath -Destination $tmp
            Move-Item -Force -LiteralPath $tmp -Destination $Destination
            return
        }
        if (Test-Path -LiteralPath $Url) {
            Copy-Item -Force -LiteralPath $Url -Destination $tmp
            Move-Item -Force -LiteralPath $tmp -Destination $Destination
            return
        }
        Invoke-HttpDownload -Url $Url -TempPath $tmp -Destination $Destination
        Move-Item -Force -LiteralPath $tmp -Destination $Destination
    } catch {
        throw "Failed to download $Url -> $Destination. $($_.Exception.Message)"
    } finally {
        Remove-Item -Force -LiteralPath $tmp -ErrorAction SilentlyContinue
    }
}

function Assert-FileHash {
    param([string]$Path, [string]$ExpectedSha256)
    if ([string]::IsNullOrWhiteSpace($ExpectedSha256) -or $DryRun) {
        return
    }
    $actual = Get-Sha256 -Path $Path
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "SHA256 mismatch for $Path. Expected $ExpectedSha256, got $actual."
    }
}

function Assert-RequiredSha256 {
    param([string]$Value, [string]$Description)
    if ($Value -notmatch '^[0-9a-fA-F]{64}$') {
        throw "$Description must include a SHA256 hash."
    }
}

function Get-Sha256 {
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $hash = $sha.ComputeHash($stream)
            return ([BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
        } finally {
            $sha.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

function Expand-ZipSafe {
    param([string]$Archive, [string]$Destination)
    if ($DryRun) {
        Write-Step "Would extract $Archive -> $Destination"
        return
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $destinationRoot = [IO.Path]::GetFullPath($Destination)
    if (-not $destinationRoot.EndsWith([IO.Path]::DirectorySeparatorChar)) {
        $destinationRoot += [IO.Path]::DirectorySeparatorChar
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -Recurse -Force -LiteralPath $Destination
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $Destination $entry.FullName))
            if (-not $target.StartsWith($destinationRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Unsafe ZIP member escapes extraction root: $($entry.FullName)"
            }
        }
    } finally {
        $zip.Dispose()
    }
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Destination)
}

function Get-GithubReleaseAsset {
    param([string]$Repo, [string]$Tag, [string]$Pattern)
    $endpoint = if ($Tag -eq 'latest') { 'latest' } else { "tags/$Tag" }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/$endpoint" -Headers @{ 'User-Agent' = 'emulebb-suite-installer' }
    foreach ($asset in @($release.assets)) {
        if ($asset.name -match $Pattern) {
            return $asset
        }
    }
    throw "No asset in $Repo $Tag matched $Pattern."
}

function Load-DependencyManifestPayload {
    param([string]$ManifestPath)
    if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
        return $null
    }
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        throw "DependencyManifest is missing: $ManifestPath"
    }
    return Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
}

function Load-DependencyManifest {
    param([object]$Payload, [string]$Channel)
    if ($null -eq $Payload) {
        if ($Channel -eq 'Latest') {
            throw 'Latest dependency resolution requires -DependencyManifest entries with exact URLs and SHA256 hashes.'
        }
        return $PinnedDependencies
    }
    $result = @{}
    foreach ($name in @('prowlarr', 'radarr', 'sonarr')) {
        $item = $Payload.$name
        if ($null -eq $item) {
            throw "Dependency manifest is missing '$name'."
        }
        $result[$name] = @{
            Repo = [string]$item.repo
            Tag = [string]$item.tag
            Pattern = [string]$item.assetPattern
            Exe = [string]$item.exeName
            Sha256 = [string]$item.sha256
            Url = [string]$item.url
        }
    }
    return $result
}

function Load-NodeSpec {
    param([object]$Payload, [string]$Platform)
    $defaultSpec = $NodeArchives[$Platform]
    $result = @{
        FileName = [string]$defaultSpec.FileName
        Sha256 = [string]$defaultSpec.Sha256
        Url = ''
    }
    if ($null -eq $Payload) {
        return $result
    }
    $item = $Payload.node
    if ($null -eq $item) {
        return $result
    }
    $url = [string]$item.url
    $fileName = [string]$item.fileName
    if ([string]::IsNullOrWhiteSpace($fileName) -and -not [string]::IsNullOrWhiteSpace($url)) {
        $fileName = [IO.Path]::GetFileName($url)
    }
    if ([string]::IsNullOrWhiteSpace($fileName)) {
        throw 'Node dependency manifest entry requires fileName or url.'
    }
    $sha256 = [string]$item.sha256
    if ([string]::IsNullOrWhiteSpace($sha256)) {
        throw 'Node dependency download requires a SHA256 hash.'
    }
    $result.FileName = $fileName
    $result.Sha256 = $sha256
    $result.Url = $url
    return $result
}

function Save-ReleaseZip {
    param([string]$Name, [string]$ZipUrl, [string]$ManifestUrl)
    $downloadRoot = Join-Path $script:Root 'downloads-cache'
    $archivePath = Join-Path $downloadRoot ([IO.Path]::GetFileName($ZipUrl))
    $manifestPath = Join-Path $downloadRoot ([IO.Path]::GetFileName($ManifestUrl))
    Write-Step "Downloading $Name manifest"
    Invoke-Download -Url $ManifestUrl -Destination $manifestPath
    Write-Step "Downloading $Name package"
    Invoke-Download -Url $ZipUrl -Destination $archivePath
    $expectedHash = ''
    if (-not $DryRun -and (Test-Path -LiteralPath $manifestPath)) {
        $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
        $sha256Property = @($manifest.PSObject.Properties | Where-Object { $_.Name -eq 'sha256' } | Select-Object -First 1)
        if ($sha256Property.Count -gt 0) {
            $expectedHash = [string]$sha256Property[0].Value
        }
        Assert-RequiredSha256 -Value $expectedHash -Description "$Name release manifest"
    }
    Write-Step "Verifying $Name package"
    Assert-FileHash -Path $archivePath -ExpectedSha256 $expectedHash
    return [ordered]@{
        Name = $Name
        ArchivePath = $archivePath
    }
}

function Resolve-LocalManifestPath {
    param([string]$ZipPath, [string]$ManifestPath)
    if (-not [string]::IsNullOrWhiteSpace($ManifestPath)) {
        return [IO.Path]::GetFullPath($ManifestPath)
    }
    if ([string]::IsNullOrWhiteSpace($ZipPath)) {
        return ''
    }
    $candidate = [IO.Path]::Combine([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ZipPath)), ([IO.Path]::GetFileNameWithoutExtension($ZipPath) + '.manifest.json'))
    if (Test-Path -LiteralPath $candidate) {
        return $candidate
    }
    return ''
}

function Save-PackageZip {
    param(
        [string]$Name,
        [string]$ZipUrl,
        [string]$ManifestUrl,
        [string]$LocalZip,
        [string]$LocalManifest
    )
    if ([string]::IsNullOrWhiteSpace($LocalZip)) {
        return Save-ReleaseZip -Name $Name -ZipUrl $ZipUrl -ManifestUrl $ManifestUrl
    }
    $archivePath = [IO.Path]::GetFullPath($LocalZip)
    if (-not $DryRun -and -not (Test-Path -LiteralPath $archivePath)) {
        throw "$Name local package ZIP is missing: $archivePath"
    }
    $manifestPath = Resolve-LocalManifestPath -ZipPath $archivePath -ManifestPath $LocalManifest
    if (-not [string]::IsNullOrWhiteSpace($manifestPath)) {
        if (-not $DryRun -and -not (Test-Path -LiteralPath $manifestPath)) {
            throw "$Name local package manifest is missing: $manifestPath"
        }
        if (-not $DryRun) {
            $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
            $sha256Property = @($manifest.PSObject.Properties | Where-Object { $_.Name -eq 'sha256' } | Select-Object -First 1)
            $expectedHash = ''
            if ($sha256Property.Count -gt 0) {
                $expectedHash = [string]$sha256Property[0].Value
            }
            Assert-RequiredSha256 -Value $expectedHash -Description "$Name local package manifest"
            Write-Step "Verifying local $Name package"
            Assert-FileHash -Path $archivePath -ExpectedSha256 $expectedHash
        }
        Write-Step "Using local $Name package $archivePath with manifest $manifestPath"
    } else {
        Write-Step "Using local $Name package $archivePath without a manifest sidecar"
    }
    return [ordered]@{
        Name = $Name
        ArchivePath = $archivePath
    }
}

function Install-VerifiedReleaseZip {
    param([string]$Name, [string]$ArchivePath, [string]$Destination)
    $downloadRoot = Join-Path $script:Root 'downloads-cache'
    $extractRoot = Join-Path $downloadRoot ("extract-$Name")
    Write-Step "Extracting $Name package"
    Expand-ZipSafe -Archive $archivePath -Destination $extractRoot
    if (-not $DryRun) {
        $extractedPackageRoot = Join-Path $extractRoot $Name
        if (-not (Test-Path -LiteralPath $extractedPackageRoot)) {
            throw "$Name release ZIP did not contain expected root directory '$Name'."
        }
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        $targetPackageRoot = Join-Path $Destination $Name
        if (Test-Path -LiteralPath $targetPackageRoot) {
            Remove-Item -Recurse -Force -LiteralPath $targetPackageRoot
        }
        Move-Item -LiteralPath $extractedPackageRoot -Destination $targetPackageRoot
        Remove-Item -Recurse -Force -LiteralPath $extractRoot -ErrorAction SilentlyContinue
    }
    Write-Step "$Name installed"
}

function Install-ReleaseZip {
    param([string]$Name, [string]$ZipUrl, [string]$ManifestUrl, [string]$Destination)
    $package = Save-ReleaseZip -Name $Name -ZipUrl $ZipUrl -ManifestUrl $ManifestUrl
    Install-VerifiedReleaseZip -Name $Name -ArchivePath $package.ArchivePath -Destination $Destination
}

function Install-ArrDependency {
    param([string]$Name, [hashtable]$Spec, [string]$Channel)
    if ($script:SuiteConfig.platform -ne 'x64') {
        throw "Full suite Arr dependencies are x64-only in v1."
    }
    $tag = if ($Channel -eq 'Latest') { 'latest' } else { $Spec.Tag }
    $assetName = $null
    $assetUrl = $Spec.Url
    if ($DryRun -and [string]::IsNullOrWhiteSpace($assetUrl)) {
        Write-Step "Would resolve $Name from $($Spec.Repo) $tag using pattern $($Spec.Pattern)"
        return
    }
    if ([string]::IsNullOrWhiteSpace($assetUrl)) {
        $asset = Get-GithubReleaseAsset -Repo $Spec.Repo -Tag $tag -Pattern $Spec.Pattern
        $assetName = [string]$asset.name
        $assetUrl = [string]$asset.browser_download_url
    } else {
        $assetName = [IO.Path]::GetFileName($assetUrl)
    }
    $archivePath = Join-Path (Join-Path $script:Root 'downloads-cache') $assetName
    $extractRoot = Join-Path (Join-Path $script:Root 'apps') $Name
    Write-Step "Downloading $Name dependency $assetName"
    Invoke-Download -Url $assetUrl -Destination $archivePath
    if ([string]::IsNullOrWhiteSpace($Spec.Sha256)) {
        throw "$Name dependency download requires a SHA256 hash. Use pinned dependencies or provide -DependencyManifest with sha256."
    }
    Write-Step "Verifying $Name dependency"
    Assert-FileHash -Path $archivePath -ExpectedSha256 $Spec.Sha256
    Write-Step "Extracting $Name dependency"
    Expand-ZipSafe -Archive $archivePath -Destination $extractRoot
    Write-Step "$Name installed"
}

function ConvertTo-XmlText {
    param([string]$Value)
    return [Security.SecurityElement]::Escape($Value)
}

function Write-ArrConfig {
    param([string]$Name, [int]$Port, [string]$BindAddress, [string]$ApiKey, [string]$Username, [string]$Password)
    $dataDir = Join-Path (Join-Path $script:Root 'data') $Name
    if (-not $DryRun) {
        New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
        $safeUsername = ConvertTo-XmlText -Value $Username
        $safePassword = ConvertTo-XmlText -Value $Password
        @(
            '<Config>'
            '  <LogLevel>info</LogLevel>'
            "  <Port>$Port</Port>"
            '  <UrlBase></UrlBase>'
            "  <BindAddress>$BindAddress</BindAddress>"
            '  <EnableSsl>False</EnableSsl>'
            "  <ApiKey>$ApiKey</ApiKey>"
            '  <AuthenticationMethod>Forms</AuthenticationMethod>'
            '  <AuthenticationRequired>Enabled</AuthenticationRequired>'
            "  <Username>$safeUsername</Username>"
            "  <Password>$safePassword</Password>"
            '  <LaunchBrowser>False</LaunchBrowser>'
            "  <InstanceName>eMuleBB $Name</InstanceName>"
            '</Config>'
            ''
        ) -join "`r`n" | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $dataDir 'config.xml')
    }
}

function New-DefaultEmulePreferencesText {
    param([hashtable]$Config)
    $p2pInterface = [string]$Config.p2p.bindInterface
    return @(
        '[eMule]'
        "IncomingDir=$(Join-Path $script:Root 'downloads\incoming')"
        "TempDir=$(Join-Path $script:Root 'downloads\temp')"
        'CreateCrashDump=2'
        "BindInterface=$p2pInterface"
        'BindAddr='
        'BlockNetworkWhenBindUnavailableAtStartup=0'
        'NetworkGuardMode=Off'
        'NetworkGuardAllowedCIDRs='
        '[WebServer]'
        'Enabled=1'
        "BindAddr=$($Config.services.emulebb.bindAddress)"
        "Port=$($Config.services.emulebb.port)"
        'UseHTTPS=0'
        'WebUseUPnP=0'
        "ApiKey=$($Config.services.emulebb.apiKey)"
        ''
    ) -join "`r`n"
}

function Copy-DirectoryContents {
    param([string]$Source, [string]$Destination)
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($child in @(Get-ChildItem -LiteralPath $Source -Force)) {
        $target = Join-Path $Destination $child.Name
        if ($child.PSIsContainer) {
            Copy-Item -Recurse -Force -LiteralPath $child.FullName -Destination $target
        } else {
            Copy-Item -Force -LiteralPath $child.FullName -Destination $target
        }
    }
}

function Append-PendingIniValues {
    param(
        [System.Collections.Generic.List[string]]$Output,
        [hashtable]$Pending,
        [string]$Section,
        [string]$Newline,
        [object[]]$Updates
    )
    foreach ($update in $Updates) {
        $pendingKey = "$(([string]$update.Section).ToLowerInvariant())|$(([string]$update.Key).ToLowerInvariant())"
        if ($pendingKey.StartsWith("$Section|") -and $Pending.ContainsKey($pendingKey)) {
            $entry = $Pending[$pendingKey]
            $Output.Add("$($entry.Key)=$($entry.Value)$Newline")
            $Pending.Remove($pendingKey)
        }
    }
}

function Update-IniText {
    param([string]$Text, [object[]]$Updates)
    $pending = @{}
    foreach ($update in $Updates) {
        $pending["$(([string]$update.Section).ToLowerInvariant())|$(([string]$update.Key).ToLowerInvariant())"] = $update
    }
    $lines = [regex]::Split($Text, "(`r`n|`n|`r)")
    $output = New-Object 'System.Collections.Generic.List[string]'
    $currentSection = ''
    $seenSections = @{}
    $newline = "`r`n"
    for ($i = 0; $i -lt $lines.Count; $i += 2) {
        $line = $lines[$i]
        if (($i + 1) -lt $lines.Count -and -not [string]::IsNullOrEmpty($lines[$i + 1])) {
            $newline = $lines[$i + 1]
        }
        if ($i -eq ($lines.Count - 1) -and [string]::IsNullOrEmpty($line)) {
            continue
        }
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith('[') -and $trimmed.EndsWith(']')) {
            Append-PendingIniValues -Output $output -Pending $pending -Section $currentSection -Newline $newline -Updates $Updates
            $currentSection = $trimmed.Substring(1, $trimmed.Length - 2).Trim().ToLowerInvariant()
            $seenSections[$currentSection] = $true
            $output.Add("$line$newline")
            continue
        }
        $equalsIndex = $line.IndexOf('=')
        if ($equalsIndex -ge 0 -and -not [string]::IsNullOrWhiteSpace($currentSection)) {
            $key = $line.Substring(0, $equalsIndex).Trim()
            $pendingKey = "$currentSection|$($key.ToLowerInvariant())"
            if ($pending.ContainsKey($pendingKey)) {
                $entry = $pending[$pendingKey]
                $output.Add("$($entry.Key)=$($entry.Value)$newline")
                $pending.Remove($pendingKey)
                continue
            }
        }
        $output.Add("$line$newline")
    }
    Append-PendingIniValues -Output $output -Pending $pending -Section $currentSection -Newline $newline -Updates $Updates
    foreach ($update in $Updates) {
        $pendingKey = "$(([string]$update.Section).ToLowerInvariant())|$(([string]$update.Key).ToLowerInvariant())"
        if (-not $pending.ContainsKey($pendingKey)) {
            continue
        }
        $entry = $pending[$pendingKey]
        $sectionName = [string]$entry.Section
        if (-not $seenSections.ContainsKey($sectionName.ToLowerInvariant())) {
            $output.Add("[$sectionName]$newline")
            $seenSections[$sectionName.ToLowerInvariant()] = $true
        }
        $output.Add("$($entry.Key)=$($entry.Value)$newline")
        $pending.Remove($pendingKey)
    }
    return ($output -join '')
}

function Update-EmulePreferencesFile {
    param([string]$PreferencesPath, [hashtable]$Config)
    $updates = @(
        [pscustomobject]@{ Section = 'eMule'; Key = 'IncomingDir'; Value = (Join-Path $script:Root 'downloads\incoming') }
        [pscustomobject]@{ Section = 'eMule'; Key = 'TempDir'; Value = (Join-Path $script:Root 'downloads\temp') }
        [pscustomobject]@{ Section = 'eMule'; Key = 'CreateCrashDump'; Value = '2' }
        [pscustomobject]@{ Section = 'eMule'; Key = 'BindInterface'; Value = [string]$Config.p2p.bindInterface }
        [pscustomobject]@{ Section = 'eMule'; Key = 'BindAddr'; Value = '' }
        [pscustomobject]@{ Section = 'eMule'; Key = 'BlockNetworkWhenBindUnavailableAtStartup'; Value = '0' }
        [pscustomobject]@{ Section = 'eMule'; Key = 'NetworkGuardMode'; Value = [string]$Config.p2p.networkGuardMode }
        [pscustomobject]@{ Section = 'eMule'; Key = 'NetworkGuardAllowedCIDRs'; Value = [string]$Config.p2p.networkGuardAllowedCIDRs }
        [pscustomobject]@{ Section = 'WebServer'; Key = 'Enabled'; Value = '1' }
        [pscustomobject]@{ Section = 'WebServer'; Key = 'BindAddr'; Value = [string]$Config.services.emulebb.bindAddress }
        [pscustomobject]@{ Section = 'WebServer'; Key = 'Port'; Value = [string]$Config.services.emulebb.port }
        [pscustomobject]@{ Section = 'WebServer'; Key = 'UseHTTPS'; Value = '0' }
        [pscustomobject]@{ Section = 'WebServer'; Key = 'WebUseUPnP'; Value = '0' }
        [pscustomobject]@{ Section = 'WebServer'; Key = 'ApiKey'; Value = [string]$Config.services.emulebb.apiKey }
    )
    $text = Get-Content -Raw -LiteralPath $PreferencesPath
    Update-IniText -Text $text -Updates $updates | Set-Content -Encoding Unicode -LiteralPath $PreferencesPath
}

function New-DefaultCategoryIniText {
    return @"
[General]
Count=0

[Cat#0]
Title=
Incoming=
Comment=
RegularExpression=
Color=-1
a4afPriority=1
AutoCat=
Filter=0
FilterNegator=0
AutoCatAsRegularExpression=0
downloadInAlphabeticalOrder=0
Care4All=0

"@
}

function Get-IniSections {
    param([string]$Text)
    $sections = @{}
    $currentSection = ''
    foreach ($line in [regex]::Split($Text, "(`r`n|`n|`r)")) {
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith('[') -and $trimmed.EndsWith(']')) {
            $currentSection = $trimmed.Substring(1, $trimmed.Length - 2).Trim()
            if (-not $sections.ContainsKey($currentSection)) {
                $sections[$currentSection] = @{}
            }
            continue
        }
        $equalsIndex = $line.IndexOf('=')
        if ($equalsIndex -lt 0 -or [string]::IsNullOrWhiteSpace($currentSection)) {
            continue
        }
        $key = $line.Substring(0, $equalsIndex).Trim()
        $value = $line.Substring($equalsIndex + 1)
        $sections[$currentSection][$key] = $value
    }
    return $sections
}

function Ensure-EmuleCategoryIni {
    param([string]$ConfigDir)
    $categoryPath = Join-Path $ConfigDir 'Category.ini'
    $prowlarrIncoming = Join-Path $script:Root 'downloads\prowlarr'
    $radarrIncoming = Join-Path $script:Root 'downloads\radarr'
    $sonarrIncoming = Join-Path $script:Root 'downloads\sonarr'
    New-Item -ItemType Directory -Force -Path $prowlarrIncoming | Out-Null
    New-Item -ItemType Directory -Force -Path $radarrIncoming | Out-Null
    New-Item -ItemType Directory -Force -Path $sonarrIncoming | Out-Null

    $text = if (Test-Path -LiteralPath $categoryPath) { Get-Content -Raw -LiteralPath $categoryPath } else { New-DefaultCategoryIniText }
    $sections = Get-IniSections -Text $text
    $categoryCount = 0
    if ($sections.ContainsKey('General') -and $sections['General'].ContainsKey('Count')) {
        [void][int]::TryParse([string]$sections['General']['Count'], [ref]$categoryCount)
    }
    foreach ($sectionName in @($sections.Keys)) {
        if ($sectionName -match '^Cat#(\d+)$') {
            $categoryCount = [Math]::Max($categoryCount, [int]$Matches[1])
        }
    }

    $updates = New-Object 'System.Collections.Generic.List[object]'
    foreach ($entry in @(
        [pscustomobject]@{ Title = 'emulebb-prowlarr'; Incoming = $prowlarrIncoming },
        [pscustomobject]@{ Title = 'emulebb-radarr'; Incoming = $radarrIncoming },
        [pscustomobject]@{ Title = 'emulebb-sonarr'; Incoming = $sonarrIncoming }
    )) {
        $section = $null
        foreach ($sectionName in @($sections.Keys)) {
            if ($sectionName -notmatch '^Cat#\d+$') {
                continue
            }
            if ($sections[$sectionName].ContainsKey('Title') -and [string]::Equals([string]$sections[$sectionName]['Title'], [string]$entry.Title, [StringComparison]::OrdinalIgnoreCase)) {
                $section = $sectionName
                break
            }
        }
        if ([string]::IsNullOrWhiteSpace($section)) {
            $categoryCount += 1
            $section = "Cat#$categoryCount"
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'Title'; Value = [string]$entry.Title })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'Comment'; Value = 'eMuleBB suite Arr integration' })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'RegularExpression'; Value = '' })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'Color'; Value = '-1' })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'a4afPriority'; Value = '1' })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'AutoCat'; Value = '' })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'Filter'; Value = '0' })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'FilterNegator'; Value = '0' })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'AutoCatAsRegularExpression'; Value = '0' })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'downloadInAlphabeticalOrder'; Value = '0' })
            $updates.Add([pscustomobject]@{ Section = $section; Key = 'Care4All'; Value = '0' })
        }
        $updates.Add([pscustomobject]@{ Section = $section; Key = 'Incoming'; Value = [IO.Path]::GetFullPath([string]$entry.Incoming) })
    }
    $updates.Add([pscustomobject]@{ Section = 'General'; Key = 'Count'; Value = [string]$categoryCount })
    Update-IniText -Text $text -Updates $updates | Set-Content -Encoding Unicode -LiteralPath $categoryPath
}

function Write-EmuleProfile {
    param([hashtable]$Config)
    $configDir = Join-Path (Join-Path $script:Root 'profiles\emulebb') 'config'
    $preferencesPath = Join-Path $configDir 'preferences.ini'
    $importResult = @{
        configured = -not [string]::IsNullOrWhiteSpace($Config.importProfileDir)
        source = if ([string]::IsNullOrWhiteSpace($Config.importProfileDir)) { $null } else { [string]$Config.importProfileDir }
        action = 'skipped-existing'
        sourcePreferencesSha256 = $null
    }
    if ($DryRun) {
        Write-Step "Would ensure eMuleBB profile under $configDir"
        return $importResult
    }
    if (-not (Test-Path -LiteralPath $preferencesPath)) {
        if (-not [string]::IsNullOrWhiteSpace($Config.importProfileDir)) {
            $sourceConfigDir = Join-Path ([IO.Path]::GetFullPath([string]$Config.importProfileDir)) 'config'
            $sourcePreferences = Join-Path $sourceConfigDir 'preferences.ini'
            if (-not (Test-Path -LiteralPath $sourcePreferences)) {
                throw "ImportProfileDir must contain config\preferences.ini: $sourcePreferences"
            }
            $importResult.action = 'imported'
            $importResult.sourcePreferencesSha256 = Get-Sha256 -Path $sourcePreferences
            if (Test-Path -LiteralPath $configDir) {
                Remove-Item -Recurse -Force -LiteralPath $configDir
            }
            Copy-DirectoryContents -Source $sourceConfigDir -Destination $configDir
        } else {
            $importResult.action = 'fresh'
            New-Item -ItemType Directory -Force -Path $configDir | Out-Null
            New-DefaultEmulePreferencesText -Config $Config | Set-Content -Encoding Unicode -LiteralPath $preferencesPath
        }
    }
    Update-EmulePreferencesFile -PreferencesPath $preferencesPath -Config $Config
    if ([string]$Config.bundle -eq 'Full') {
        Ensure-EmuleCategoryIni -ConfigDir $configDir
    }
    return $importResult
}

function Copy-OptionalEmuleSymbols {
    param([hashtable]$Config)
    $result = @{
        configured = -not [string]::IsNullOrWhiteSpace($Config.symbols.emulebbPdbPath)
        source = if ([string]::IsNullOrWhiteSpace($Config.symbols.emulebbPdbPath)) { $null } else { [string]$Config.symbols.emulebbPdbPath }
        adjacentPdb = $null
        versionedPdb = $null
        sourceSha256 = $null
        action = 'skipped-not-configured'
    }
    if ([string]::IsNullOrWhiteSpace($Config.symbols.emulebbPdbPath)) {
        return $result
    }
    $sourcePdb = [IO.Path]::GetFullPath([string]$Config.symbols.emulebbPdbPath)
    if (-not (Test-Path -LiteralPath $sourcePdb)) {
        throw "EmulebbPdbPath is missing: $sourcePdb"
    }
    $pdbFileName = Get-EmulebbPdbFileName -ExecutableName ([string]$Config.emulebbExecutableName)
    $adjacentPdb = Join-Path (Join-Path $script:Root 'apps\eMuleBB') $pdbFileName
    $symbolsDir = Join-Path (Join-Path (Join-Path $script:Root 'symbols') "emulebb-v$($Config.version)") ([string]$Config.platform)
    $versionedPdb = Join-Path $symbolsDir $pdbFileName
    $result.adjacentPdb = $adjacentPdb
    $result.versionedPdb = $versionedPdb
    $result.sourceSha256 = Get-Sha256 -Path $sourcePdb
    if ($DryRun) {
        $result.action = 'dry-run'
        Write-Step "Would copy eMuleBB symbols from $sourcePdb"
        return $result
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $adjacentPdb) | Out-Null
    New-Item -ItemType Directory -Force -Path $symbolsDir | Out-Null
    Copy-Item -Force -LiteralPath $sourcePdb -Destination $adjacentPdb
    Copy-Item -Force -LiteralPath $sourcePdb -Destination $versionedPdb
    $result.action = 'copied'
    return $result
}

function Assert-EmulebbExecutableInstalled {
    param([hashtable]$Config)
    if ($DryRun) {
        return
    }
    $exePath = Join-Path (Join-Path $script:Root 'apps\eMuleBB') ([string]$Config.emulebbExecutableName)
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Installed eMuleBB package did not include selected executable: $($Config.emulebbExecutableName)"
    }
}

function Write-SuiteConfigFile {
    param([hashtable]$Config)
    if ($DryRun) {
        return
    }
    $manifestDir = Join-Path $script:Root 'manifests'
    New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null
    $Config | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $manifestDir 'suite-config.json')
}

function Get-ServiceUrl {
    param($Service)
    $hostName = [string]$Service.bindAddress
    if ($hostName -eq '0.0.0.0' -or $hostName -eq '::') {
        $hostName = 'localhost'
    }
    return "http://$hostName`:$([int]$Service.port)"
}

function ConvertTo-HtmlText {
    param([string]$Value)
    return [Security.SecurityElement]::Escape($Value)
}

function New-CopyFieldHtml {
    param([string]$Label, [string]$Value)
    $safeLabel = ConvertTo-HtmlText -Value $Label
    $safeValue = ConvertTo-HtmlText -Value $Value
    return "<div class=`"field`"><span>$safeLabel</span><code>$safeValue</code><button type=`"button`" data-copy=`"$safeValue`">Copy</button></div>"
}

function New-ServiceCardHtml {
    param([string]$Name, [string]$Url, [object[]]$Fields)
    $safeName = ConvertTo-HtmlText -Value $Name
    $safeUrl = ConvertTo-HtmlText -Value $Url
    $fieldHtml = ($Fields -join "`r`n")
    return @"
<section class="card">
  <div class="card-head">
    <h2>$safeName</h2>
    <a class="open" href="$safeUrl" target="_blank" rel="noopener noreferrer">Open</a>
  </div>
  <div class="url"><a href="$safeUrl" target="_blank" rel="noopener noreferrer">$safeUrl</a></div>
  <div class="fields">
$fieldHtml
  </div>
</section>
"@
}

function Write-CredentialsFile {
    param([hashtable]$Config)
    if ($DryRun) {
        return
    }
    $lines = New-Object 'System.Collections.Generic.List[string]'
    $lines.Add('eMuleBB Suite credentials')
    $lines.Add("Generated UTC: $([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))")
    $lines.Add("Install root: $script:Root")
    $lines.Add("Bundle: $($Config.bundle)")
    $lines.Add('')
    $lines.Add('Suite web login')
    $lines.Add("Username: $($Config.credentials.username)")
    $lines.Add("Password: $($Config.credentials.password)")
    $lines.Add('')
    $lines.Add('Services')
    $lines.Add("eMuleBB URL: $(Get-ServiceUrl -Service $Config.services.emulebb)")
    $lines.Add("eMuleBB API key: $($Config.services.emulebb.apiKey)")
    if ([string]$Config.bundle -ne 'Core') {
        $lines.Add('')
        $lines.Add("aMuTorrent URL: $(Get-ServiceUrl -Service $Config.services.amutorrent)")
        $lines.Add("aMuTorrent username: $($Config.credentials.username)")
        $lines.Add("aMuTorrent password: $($Config.credentials.password)")
    }
    if ([string]$Config.bundle -eq 'Full') {
        foreach ($serviceName in @('prowlarr', 'radarr', 'sonarr')) {
            $service = $Config.services[$serviceName]
            $lines.Add('')
            $lines.Add("$serviceName URL: $(Get-ServiceUrl -Service $service)")
            $lines.Add("$serviceName API key: $($service.apiKey)")
            $lines.Add("$serviceName web authentication: disabled by suite config; use the API key above for integrations.")
        }
        $lines.Add('')
        $lines.Add('Radarr/Sonarr download client')
        $lines.Add('Name: eMuleBB Suite')
        $lines.Add('Username: emule')
        $lines.Add("Password: $($Config.services.emulebb.apiKey)")
    }
    if ([string]$Config.bundle -eq 'Full') {
        $lines.Add('')
        $lines.Add('First-run setup')
        $lines.Add('Run scripts\Start-Suite.ps1 once before adding movies or series. It starts the suite, registers aMuTorrent/Prowlarr/Radarr/Sonarr, and creates the Radarr/Sonarr root folders.')
    }
    $lines.Add('')
    $lines.Add('Files')
    $lines.Add('Suite config: manifests\suite-config.json')
    $lines.Add('Incoming downloads: downloads\incoming')
    $lines.Add('Temporary downloads: downloads\temp')
    ($lines -join "`r`n") + "`r`n" | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $script:Root 'credentials.txt')

    $cards = New-Object 'System.Collections.Generic.List[string]'
    $suiteFields = @(
        (New-CopyFieldHtml -Label 'Username' -Value ([string]$Config.credentials.username)),
        (New-CopyFieldHtml -Label 'Password' -Value ([string]$Config.credentials.password))
    )
    $cards.Add((New-ServiceCardHtml -Name 'Suite Login' -Url (Get-ServiceUrl -Service $Config.services.emulebb) -Fields $suiteFields))

    $emuleFields = @(
        (New-CopyFieldHtml -Label 'API key' -Value ([string]$Config.services.emulebb.apiKey))
    )
    $cards.Add((New-ServiceCardHtml -Name 'eMuleBB' -Url (Get-ServiceUrl -Service $Config.services.emulebb) -Fields $emuleFields))

    if ([string]$Config.bundle -ne 'Core') {
        $amutorrentFields = @(
            (New-CopyFieldHtml -Label 'Username' -Value ([string]$Config.credentials.username)),
            (New-CopyFieldHtml -Label 'Password' -Value ([string]$Config.credentials.password))
        )
        $cards.Add((New-ServiceCardHtml -Name 'aMuTorrent' -Url (Get-ServiceUrl -Service $Config.services.amutorrent) -Fields $amutorrentFields))
    }
    if ([string]$Config.bundle -eq 'Full') {
        foreach ($serviceName in @('prowlarr', 'radarr', 'sonarr')) {
            $service = $Config.services[$serviceName]
            $arrFields = @(
                (New-CopyFieldHtml -Label 'Username' -Value ([string]$Config.credentials.username)),
                (New-CopyFieldHtml -Label 'Password' -Value ([string]$Config.credentials.password)),
                (New-CopyFieldHtml -Label 'API key' -Value ([string]$service.apiKey))
            )
            $cards.Add((New-ServiceCardHtml -Name $serviceName -Url (Get-ServiceUrl -Service $service) -Fields $arrFields))
        }
        $downloadClientFields = @(
            (New-CopyFieldHtml -Label 'Name' -Value 'eMuleBB Suite'),
            (New-CopyFieldHtml -Label 'Username' -Value 'emule'),
            (New-CopyFieldHtml -Label 'Password' -Value ([string]$Config.services.emulebb.apiKey))
        )
        $cards.Add((New-ServiceCardHtml -Name 'Radarr/Sonarr Download Client' -Url (Get-ServiceUrl -Service $Config.services.emulebb) -Fields $downloadClientFields))
    }

    $generatedUtc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    $safeRoot = ConvertTo-HtmlText -Value $script:Root
    $safeBundle = ConvertTo-HtmlText -Value ([string]$Config.bundle)
    $safeVersion = ConvertTo-HtmlText -Value ([string]$Config.version)
    $safePlatform = ConvertTo-HtmlText -Value ([string]$Config.platform)
    $cardsHtml = ($cards -join "`r`n")
    $html = @"
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>eMuleBB Suite Credentials</title>
  <style>
    body { margin: 0; font: 14px/1.45 "Segoe UI", Arial, sans-serif; color: #1f2933; background: #f5f7fa; }
    main { max-width: 1040px; margin: 0 auto; padding: 28px; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    h2 { margin: 0; font-size: 18px; }
    .summary { margin: 0 0 22px; color: #52606d; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 14px; }
    .card { background: #fff; border: 1px solid #d9e2ec; border-radius: 8px; padding: 16px; box-shadow: 0 1px 2px rgba(16, 24, 40, .06); }
    .card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .open, button { border: 1px solid #2563eb; background: #2563eb; color: #fff; border-radius: 6px; padding: 6px 10px; text-decoration: none; cursor: pointer; }
    .url { margin: 10px 0 12px; overflow-wrap: anywhere; }
    .url a { color: #1d4ed8; }
    .field { display: grid; grid-template-columns: 78px minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 7px 0; border-top: 1px solid #edf2f7; }
    .field span { color: #52606d; }
    code { background: #f1f5f9; border: 1px solid #d9e2ec; border-radius: 4px; padding: 4px 6px; overflow-wrap: anywhere; }
    footer { margin-top: 22px; color: #697586; }
  </style>
</head>
<body>
<main>
  <h1>eMuleBB Suite Credentials</h1>
  <p class="summary">Generated $generatedUtc. Bundle $safeBundle, version $safeVersion, platform $safePlatform. Install root: $safeRoot.</p>
  <div class="grid">
$cardsHtml
  </div>
  <footer>Keep this file private. API keys and passwords are shown here for first-run setup and recovery. For Full installs, run scripts\Start-Suite.ps1 once before adding movies or series so Radarr/Sonarr root folders and suite registrations are created.</footer>
</main>
<script>
document.addEventListener('click', async function (event) {
  var button = event.target.closest('button[data-copy]');
  if (!button) return;
  var value = button.getAttribute('data-copy');
  try {
    await navigator.clipboard.writeText(value);
    button.textContent = 'Copied';
    setTimeout(function () { button.textContent = 'Copy'; }, 1200);
  } catch (err) {
    var input = document.createElement('input');
    input.value = value;
    document.body.appendChild(input);
    input.select();
    document.execCommand('copy');
    document.body.removeChild(input);
  }
});
</script>
</body>
</html>
"@
    $html | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $script:Root 'credentials.html')
}

function Write-SuiteScripts {
    param([hashtable]$Config)
    $scriptsDir = Join-Path $script:Root 'scripts'
    if ($DryRun) {
        Write-Step "Would write suite control scripts"
        return
    }
    New-Item -ItemType Directory -Force -Path $scriptsDir | Out-Null
    $rootLiteral = $script:Root.Replace("'", "''")
    $versionLiteral = ([string]$Config.version).Replace("'", "''")
    $platformLiteral = ([string]$Config.platform).Replace("'", "''")
$startEmuleBB = @"
#Requires -Version 5.1
`$ErrorActionPreference = 'Stop'
`$Root = '$rootLiteral'
`$Config = Get-Content -Raw -LiteralPath (Join-Path `$Root 'manifests\suite-config.json') | ConvertFrom-Json
`$EmuleExe = if ([string]::IsNullOrWhiteSpace([string]`$Config.emulebbExecutableName)) { 'emulebb.exe' } else { [string]`$Config.emulebbExecutableName }
`$Emule = Join-Path (Join-Path `$Root 'apps\eMuleBB') `$EmuleExe
function Test-EmuleRunning {
    param([string]`$Path)
    return [bool](Get-Process | Where-Object { `$_.Path -and [string]::Equals(`$_.Path, `$Path, [StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1)
}
if (-not (Test-Path -LiteralPath `$Emule)) {
    throw "eMuleBB executable is missing: `$Emule. Re-run scripts\Install-eMuleBBSuite.ps1 with -Force to refresh suite files."
}
`$Existing = Get-Process | Where-Object { `$_.Path -and [string]::Equals(`$_.Path, `$Emule, [StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1
if (`$Existing) {
    Write-Host "eMuleBB is already running: PID `$(`$Existing.Id)"
    return
}
Start-Process -FilePath `$Emule -ArgumentList @('-c', (Join-Path `$Root 'profiles\emulebb')) | Out-Null
Start-Sleep -Seconds 2
if (-not (Test-EmuleRunning -Path `$Emule)) {
    throw "eMuleBB did not stay running after launch from `$Emule. Check `$Root\profiles\emulebb\logs and `$Root\profiles\emulebb\config\preferences.ini."
}
"@
    $startEmuleBB | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $scriptsDir 'Start-eMuleBB.ps1')
$startSuite = @"
#Requires -Version 5.1
`$ErrorActionPreference = 'Stop'
`$Root = '$rootLiteral'
`$Config = Get-Content -Raw -LiteralPath (Join-Path `$Root 'manifests\suite-config.json') | ConvertFrom-Json
function Get-ClientHost {
    param([string]`$BindAddress)
    if (`$BindAddress -eq '0.0.0.0' -or `$BindAddress -eq '::') {
        if (-not [string]::IsNullOrWhiteSpace(`$env:X_LOCAL_IP)) { return `$env:X_LOCAL_IP.Trim() }
        return '127.0.0.1'
    }
    return `$BindAddress
}
function Get-HttpErrorDetail {
    param(`$Exception)
    if (`$null -eq `$Exception -or `$null -eq `$Exception.Response) {
        return ''
    }
    `$response = `$Exception.Response
    `$status = 0
    try { `$status = [int]`$response.StatusCode } catch { `$status = 0 }
    `$statusText = if (`$status -gt 0) { "HTTP `$status" } else { 'HTTP request failed' }
    try {
        if (-not [string]::IsNullOrWhiteSpace([string]`$response.StatusDescription)) {
            `$statusText = "`$statusText `$(`$response.StatusDescription)"
        }
    } catch {
    }
    `$detail = ''
    try {
        `$stream = `$response.GetResponseStream()
        if (`$null -ne `$stream) {
            `$reader = New-Object IO.StreamReader(`$stream)
            try {
                `$detail = `$reader.ReadToEnd()
            } finally {
                `$reader.Dispose()
            }
        }
    } catch {
    }
    `$detail = ([string]`$detail -replace '\s+', ' ').Trim()
    if (`$detail.Length -gt 1200) {
        `$detail = `$detail.Substring(0, 1200) + '...'
    }
    if ([string]::IsNullOrWhiteSpace(`$detail)) {
        return `$statusText
    }
    return "`${statusText}: `$detail"
}
function Get-ExceptionMessage {
    param(`$Exception)
    `$detail = Get-HttpErrorDetail -Exception `$Exception
    if (-not [string]::IsNullOrWhiteSpace(`$detail)) {
        return `$detail
    }
    return `$Exception.Message
}
function Invoke-SuiteJsonApi {
    param([string]`$Name, [string]`$Uri, [string]`$Method = 'GET', [hashtable]`$Headers = @{}, `$Body = `$null)
    try {
        if (`$null -eq `$Body) {
            return Invoke-RestMethod -Uri `$Uri -Method `$Method -Headers `$Headers -TimeoutSec 20 -ErrorAction Stop
        }
        return Invoke-RestMethod -Uri `$Uri -Method `$Method -Headers `$Headers -Body (`$Body | ConvertTo-Json -Depth 20) -ContentType 'application/json' -TimeoutSec 20 -ErrorAction Stop
    } catch {
        throw "`$Name failed at `$Uri. `$(Get-ExceptionMessage -Exception `$_.Exception)"
    }
}
function Get-ServiceTroubleshootingHint {
    param([string]`$Name)
    switch (`$Name) {
        'eMuleBB' { return "Check `$Root\profiles\emulebb\logs and confirm eMuleBB is not blocked by Windows Firewall or Defender." }
        'aMuTorrent' { return "Check `$Root\data\amutorrent\logs and confirm the pinned Node runtime exists under `$Root\runtime\node." }
        'Prowlarr' { return "Check `$Root\data\prowlarr\logs and `$Root\data\prowlarr\config.xml." }
        'Radarr' { return "Check `$Root\data\radarr\logs and `$Root\data\radarr\config.xml." }
        'Sonarr' { return "Check `$Root\data\sonarr\logs and `$Root\data\sonarr\config.xml." }
        default { return "Check the service log and config files under `$Root\data." }
    }
}
function Wait-Json {
    param([string]`$Name, [string]`$Uri, [hashtable]`$Headers = @{})
    `$lastError = ''
    for (`$i = 0; `$i -lt 90; `$i++) {
        try {
            Invoke-RestMethod -Uri `$Uri -Headers `$Headers -TimeoutSec 2 -ErrorAction Stop | Out-Null
            return
        } catch {
            `$lastError = Get-ExceptionMessage -Exception `$_.Exception
            Start-Sleep -Seconds 1
        }
    }
    if ([string]::IsNullOrWhiteSpace(`$lastError)) {
        throw "Timed out waiting for `$Name at `$Uri. `$(Get-ServiceTroubleshootingHint -Name `$Name)"
    }
    throw "Timed out waiting for `$Name at `$Uri. Last error: `$lastError. `$(Get-ServiceTroubleshootingHint -Name `$Name)"
}
function Set-ObjectProperty {
    param(`$Target, [string]`$Name, `$Value)
    if (`$null -ne `$Target.PSObject.Properties[`$Name]) {
        `$Target.`$Name = `$Value
    } else {
        `$Target | Add-Member -NotePropertyName `$Name -NotePropertyValue `$Value -Force
    }
}
function Get-ObjectPropertyValue {
    param(`$Target, [string]`$Name, `$Default = `$null)
    if (`$null -eq `$Target -or `$null -eq `$Target.PSObject.Properties[`$Name]) {
        return `$Default
    }
    return `$Target.PSObject.Properties[`$Name].Value
}
function Get-OrCreateObjectProperty {
    param(`$Target, [string]`$Name)
    `$value = Get-ObjectPropertyValue -Target `$Target -Name `$Name -Default `$null
    if (`$null -eq `$value) {
        `$value = [pscustomobject]@{}
        Set-ObjectProperty -Target `$Target -Name `$Name -Value `$value
    }
    return `$value
}
function Initialize-AmutorrentConfig {
    param([string]`$DataDir, [string]`$BindAddress, [int]`$Port, [string]`$Username, [string]`$Password)
    New-Item -ItemType Directory -Force -Path `$DataDir | Out-Null
    `$configPath = Join-Path `$DataDir 'config.json'
    if (Test-Path -LiteralPath `$configPath) {
        `$config = Get-Content -Raw -LiteralPath `$configPath | ConvertFrom-Json
        if (`$null -eq `$config) { `$config = [pscustomobject]@{} }
    } else {
        `$config = [pscustomobject]@{}
    }
    if ([string]::IsNullOrWhiteSpace([string](Get-ObjectPropertyValue -Target `$config -Name 'version' -Default ''))) {
        Set-ObjectProperty -Target `$config -Name 'version' -Value '1.0'
    }
    Set-ObjectProperty -Target `$config -Name 'firstRunCompleted' -Value `$true
    `$server = Get-OrCreateObjectProperty -Target `$config -Name 'server'
    Set-ObjectProperty -Target `$server -Name 'host' -Value `$BindAddress
    Set-ObjectProperty -Target `$server -Name 'port' -Value `$Port
    `$auth = Get-OrCreateObjectProperty -Target `$server -Name 'auth'
    Set-ObjectProperty -Target `$auth -Name 'enabled' -Value `$true
    Set-ObjectProperty -Target `$auth -Name 'adminUsername' -Value `$Username
    Set-ObjectProperty -Target `$auth -Name 'password' -Value `$Password
    `$directories = Get-OrCreateObjectProperty -Target `$config -Name 'directories'
    Set-ObjectProperty -Target `$directories -Name 'data' -Value `$DataDir
    Set-ObjectProperty -Target `$directories -Name 'logs' -Value (Join-Path `$DataDir 'logs')
    Set-ObjectProperty -Target `$directories -Name 'geoip' -Value (Join-Path `$DataDir 'geoip')
    if (`$null -eq `$config.PSObject.Properties['clients'] -or `$null -eq `$config.clients) {
        Set-ObjectProperty -Target `$config -Name 'clients' -Value @()
    }
    `$config | ConvertTo-Json -Depth 40 | Set-Content -Encoding UTF8 -LiteralPath `$configPath
    Write-Host "aMuTorrent bootstrap config ready: `$configPath"
}
function Set-ArrHostCredentials {
    param([string]`$Name, [string]`$Url, [string]`$ApiPath, [string]`$ApiKey)
    `$hostConfigUrl = "`$Url/`$ApiPath/config/host"
    `$headers = @{ 'X-Api-Key' = `$ApiKey }
    `$hostConfig = Invoke-SuiteJsonApi -Name "`$Name host config read" -Uri `$hostConfigUrl -Headers `$headers
    `$hostConfig.authenticationMethod = 'forms'
    `$hostConfig.authenticationRequired = 'enabled'
    `$hostConfig.username = [string]`$Config.credentials.username
    `$hostConfig.password = [string]`$Config.credentials.password
    `$hostConfig.passwordConfirmation = [string]`$Config.credentials.password
    [void](Invoke-SuiteJsonApi -Name "`$Name web login update" -Uri `$hostConfigUrl -Method 'PUT' -Headers `$headers -Body `$hostConfig)
    Write-Host "`$Name web login configured."
}
function Ensure-ArrRootFolder {
    param([string]`$Name, [string]`$Url, [string]`$ApiPath, [string]`$ApiKey, [string]`$Path)
    New-Item -ItemType Directory -Force -Path `$Path | Out-Null
    `$rootFolderUrl = "`$Url/`$ApiPath/rootfolder"
    `$headers = @{ 'X-Api-Key' = `$ApiKey }
    `$normalizedPath = [IO.Path]::GetFullPath(`$Path).TrimEnd('\')
    `$rootFolders = @(Invoke-SuiteJsonApi -Name "`$Name root folder list" -Uri `$rootFolderUrl -Headers `$headers)
    foreach (`$rootFolder in `$rootFolders) {
        if (`$null -eq `$rootFolder -or `$null -eq `$rootFolder.PSObject.Properties['path']) {
            continue
        }
        if ([string]::Equals(([IO.Path]::GetFullPath([string]`$rootFolder.path).TrimEnd('\')), `$normalizedPath, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "`$Name root folder already configured: `$normalizedPath"
            return
        }
    }
    [void](Invoke-SuiteJsonApi -Name "`$Name root folder create" -Uri `$rootFolderUrl -Method 'POST' -Headers `$headers -Body @{ path = `$normalizedPath })
    `$rootFolders = @(Invoke-SuiteJsonApi -Name "`$Name root folder verify" -Uri `$rootFolderUrl -Headers `$headers)
    foreach (`$rootFolder in `$rootFolders) {
        if (`$null -eq `$rootFolder -or `$null -eq `$rootFolder.PSObject.Properties['path']) {
            continue
        }
        if ([string]::Equals(([IO.Path]::GetFullPath([string]`$rootFolder.path).TrimEnd('\')), `$normalizedPath, [StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "`$Name root folder configured: `$normalizedPath"
            return
        }
    }
    throw "`$Name did not persist root folder `$normalizedPath. Open `$Name, go to Settings > Media Management > Root Folders, and add that folder manually before adding movies or series."
}
function Ensure-EmuleBBAvailable {
    & (Join-Path `$Root 'scripts\Start-eMuleBB.ps1')
    Wait-Json -Name 'eMuleBB' -Uri "`$EmuleUrl/api/v1/app" -Headers @{ 'X-API-Key' = `$EmuleKey }
}
function Ensure-SuiteServicesAvailable {
    Ensure-EmuleBBAvailable
    if (`$Bundle -ne 'Core' -and -not [string]::IsNullOrWhiteSpace(`$AmutorrentUrl)) {
        Wait-Json -Name 'aMuTorrent' -Uri "`$AmutorrentUrl/api/auth/status"
    }
    if (`$Bundle -eq 'Full') {
        if (-not [string]::IsNullOrWhiteSpace(`$ProwlarrUrl) -and -not [string]::IsNullOrWhiteSpace(`$ProwlarrKey)) {
            Wait-Json -Name 'Prowlarr' -Uri "`$ProwlarrUrl/api/v1/system/status" -Headers @{ 'X-Api-Key' = `$ProwlarrKey }
        }
        if (-not [string]::IsNullOrWhiteSpace(`$RadarrUrl) -and -not [string]::IsNullOrWhiteSpace(`$RadarrKey)) {
            Wait-Json -Name 'Radarr' -Uri "`$RadarrUrl/api/v3/system/status" -Headers @{ 'X-Api-Key' = `$RadarrKey }
        }
        if (-not [string]::IsNullOrWhiteSpace(`$SonarrUrl) -and -not [string]::IsNullOrWhiteSpace(`$SonarrKey)) {
            Wait-Json -Name 'Sonarr' -Uri "`$SonarrUrl/api/v3/system/status" -Headers @{ 'X-Api-Key' = `$SonarrKey }
        }
    }
}
function Invoke-StepWithRetry {
    param([string]`$Name, [scriptblock]`$Operation)
    for (`$attempt = 1; `$attempt -le 3; `$attempt++) {
        try {
            & `$Operation
            return
        } catch {
            if (`$attempt -ge 3) { throw }
            Write-Warning "`$Name failed on attempt `$(`$attempt): `$(`$_.Exception.Message)"
            Ensure-SuiteServicesAvailable
            Start-Sleep -Seconds 3
        }
    }
}
function Test-ProcessRunning {
    param([string]`$ExecutablePath, [string]`$CommandLineContains = '')
    try {
        foreach (`$process in @(Get-CimInstance Win32_Process -ErrorAction Stop)) {
            if ([string]::IsNullOrWhiteSpace(`$process.ExecutablePath)) { continue }
            if (-not [string]::Equals(`$process.ExecutablePath, `$ExecutablePath, [StringComparison]::OrdinalIgnoreCase)) { continue }
            if ([string]::IsNullOrWhiteSpace(`$CommandLineContains) -or ([string]`$process.CommandLine).IndexOf(`$CommandLineContains, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                return `$true
            }
        }
    } catch {
        return [bool](Get-Process | Where-Object { `$_.Path -and [string]::Equals(`$_.Path, `$ExecutablePath, [StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1)
    }
    return `$false
}
function Start-ProcessIfMissing {
    param([string]`$Name, [string]`$FilePath, [string[]]`$ArgumentList = @(), [string]`$WorkingDirectory = '', [string]`$CommandLineContains = '', [switch]`$Hidden)
    if (-not (Test-Path -LiteralPath `$FilePath)) {
        throw "`$Name executable is missing: `$FilePath"
    }
    if (Test-ProcessRunning -ExecutablePath `$FilePath -CommandLineContains `$CommandLineContains) {
        Write-Host "`$Name is already running: `$FilePath"
        return
    }
    Write-Host "Starting `${Name}: `$FilePath"
    `$startArgs = @{
        FilePath = `$FilePath
        ArgumentList = `$ArgumentList
    }
    if (-not [string]::IsNullOrWhiteSpace(`$WorkingDirectory)) { `$startArgs.WorkingDirectory = `$WorkingDirectory }
    if (`$Hidden) { `$startArgs.WindowStyle = 'Hidden' }
    Start-Process @startArgs | Out-Null
    Start-Sleep -Seconds 2
    if (-not (Test-ProcessRunning -ExecutablePath `$FilePath -CommandLineContains `$CommandLineContains)) {
        throw "`$Name did not stay running after launch from `$FilePath. `$(Get-ServiceTroubleshootingHint -Name `$Name)"
    }
}
function Start-ArrHost {
    param([string]`$Name, [string]`$DataDir)
    `$appRoot = Join-Path `$Root ('apps\' + `$Name)
    `$trayName = `$Name + '.exe'
    `$exe = Get-ChildItem -Path `$appRoot -Filter `$trayName -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not `$exe) {
        throw "Missing Windows tray host for `$Name under `$appRoot"
    }
    Start-ProcessIfMissing -Name `$Name -FilePath `$exe.FullName -ArgumentList @('/data=' + (Join-Path `$Root `$DataDir), '/nobrowser') -CommandLineContains (Join-Path `$Root `$DataDir)
}
`$Bundle = [string]`$Config.bundle
`$EmuleHost = Get-ClientHost `$Config.services.emulebb.bindAddress
`$EmulePort = [int]`$Config.services.emulebb.port
`$EmuleUrl = "http://`$(`$EmuleHost):`$EmulePort"
`$EmuleKey = [string]`$Config.services.emulebb.apiKey
& (Join-Path `$Root 'scripts\Start-eMuleBB.ps1')
if (`$Bundle -eq 'Full') {
    foreach (`$item in @(@('Prowlarr','data\prowlarr'), @('Radarr','data\radarr'), @('Sonarr','data\sonarr'))) {
        Start-ArrHost -Name `$item[0] -DataDir `$item[1]
    }
}
if (`$Bundle -ne 'Core') {
    `$node = `$null
    `$nodeMatch = Get-ChildItem -Path (Join-Path `$Root 'runtime\node') -Filter node.exe -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (`$nodeMatch) {
        `$node = `$nodeMatch.FullName
    } else {
        `$node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
    }
    if (-not (Test-Path -LiteralPath `$node)) { throw 'Node is not available. Re-run Install-eMuleBBSuite.ps1 to install the pinned runtime.' }
    `$amutorrentServer = Join-Path `$Root 'apps\aMuTorrent\server\server.js'
    `$env:AMUTORRENT_DATA_DIR = Join-Path `$Root 'data\amutorrent'
    Initialize-AmutorrentConfig -DataDir `$env:AMUTORRENT_DATA_DIR -BindAddress ([string]`$Config.services.amutorrent.bindAddress) -Port ([int]`$Config.services.amutorrent.port) -Username ([string]`$Config.credentials.username) -Password ([string]`$Config.credentials.password)
    Start-ProcessIfMissing -Name 'aMuTorrent' -FilePath `$node -ArgumentList @(`$amutorrentServer) -WorkingDirectory (Join-Path `$Root 'apps\aMuTorrent') -CommandLineContains `$amutorrentServer -Hidden
}
Ensure-EmuleBBAvailable
if (`$Bundle -ne 'Core') {
    `$AmutorrentHost = Get-ClientHost `$Config.services.amutorrent.bindAddress
    `$AmutorrentUrl = "http://`$(`$AmutorrentHost):`$([int]`$Config.services.amutorrent.port)"
    Wait-Json -Name 'aMuTorrent' -Uri "`$AmutorrentUrl/api/auth/status"
    Invoke-StepWithRetry -Name 'aMuTorrent registration' -Operation {
        & (Join-Path `$Root 'apps\eMuleBB\scripts\Register-aMuTorrent.ps1') -AmutorrentUrl `$AmutorrentUrl -AmutorrentApiKey '' -AmutorrentUsername ([string]`$Config.credentials.username) -AmutorrentPassword ([string]`$Config.credentials.password) -EmulebbBaseUrl `$EmuleUrl -EmulebbApiKey `$EmuleKey -InstanceName 'eMuleBB Suite' -InstanceId 'emulebb-suite' -NoRetry
    }
}
if (`$Bundle -eq 'Full') {
    `$ProwlarrUrl = "http://`$(Get-ClientHost `$Config.services.prowlarr.bindAddress):`$([int]`$Config.services.prowlarr.port)"
    `$RadarrUrl = "http://`$(Get-ClientHost `$Config.services.radarr.bindAddress):`$([int]`$Config.services.radarr.port)"
    `$SonarrUrl = "http://`$(Get-ClientHost `$Config.services.sonarr.bindAddress):`$([int]`$Config.services.sonarr.port)"
    `$ProwlarrKey = [string]`$Config.services.prowlarr.apiKey
    `$RadarrKey = [string]`$Config.services.radarr.apiKey
    `$SonarrKey = [string]`$Config.services.sonarr.apiKey
    Wait-Json -Name 'Prowlarr' -Uri "`$ProwlarrUrl/api/v1/system/status" -Headers @{ 'X-Api-Key' = `$ProwlarrKey }
    Wait-Json -Name 'Radarr' -Uri "`$RadarrUrl/api/v3/system/status" -Headers @{ 'X-Api-Key' = `$RadarrKey }
    Wait-Json -Name 'Sonarr' -Uri "`$SonarrUrl/api/v3/system/status" -Headers @{ 'X-Api-Key' = `$SonarrKey }
    Invoke-StepWithRetry -Name 'Arr web login setup' -Operation {
        Set-ArrHostCredentials -Name 'Prowlarr' -Url `$ProwlarrUrl -ApiPath 'api/v1' -ApiKey `$ProwlarrKey
        Set-ArrHostCredentials -Name 'Radarr' -Url `$RadarrUrl -ApiPath 'api/v3' -ApiKey `$RadarrKey
        Set-ArrHostCredentials -Name 'Sonarr' -Url `$SonarrUrl -ApiPath 'api/v3' -ApiKey `$SonarrKey
    }
    Invoke-StepWithRetry -Name 'Radarr root folder setup' -Operation {
        Ensure-ArrRootFolder -Name 'Radarr' -Url `$RadarrUrl -ApiPath 'api/v3' -ApiKey `$RadarrKey -Path (Join-Path `$Root 'media\movies')
    }
    Invoke-StepWithRetry -Name 'Sonarr root folder setup' -Operation {
        Ensure-ArrRootFolder -Name 'Sonarr' -Url `$SonarrUrl -ApiPath 'api/v3' -ApiKey `$SonarrKey -Path (Join-Path `$Root 'media\series')
    }
    Invoke-StepWithRetry -Name 'Prowlarr registration' -Operation {
        & (Join-Path `$Root 'apps\eMuleBB\scripts\Register-Prowlarr.ps1') -ProwlarrUrl `$ProwlarrUrl -ProwlarrApiKey `$ProwlarrKey -EmulebbBaseUrl `$EmuleUrl -EmulebbApiKey `$EmuleKey -IndexerName 'eMuleBB Suite' -AppProfileName 'eMuleBB Suite' -NoRetry
    }
    Invoke-StepWithRetry -Name 'Radarr registration' -Operation {
        & (Join-Path `$Root 'apps\eMuleBB\scripts\Register-ArrStack.ps1') -Target Radarr -EmulebbBaseUrl `$EmuleUrl -EmulebbApiKey `$EmuleKey -EmulebbCategoryPath (Join-Path `$Root 'downloads\radarr') -ProwlarrUrl `$ProwlarrUrl -ProwlarrApiKey `$ProwlarrKey -RadarrUrl `$RadarrUrl -RadarrApiKey `$RadarrKey -DownloadClientName 'eMuleBB Suite' -SkipProwlarrSync -NoRetry
    }
    Invoke-StepWithRetry -Name 'Sonarr registration' -Operation {
        & (Join-Path `$Root 'apps\eMuleBB\scripts\Register-ArrStack.ps1') -Target Sonarr -EmulebbBaseUrl `$EmuleUrl -EmulebbApiKey `$EmuleKey -EmulebbCategoryPath (Join-Path `$Root 'downloads\sonarr') -ProwlarrUrl `$ProwlarrUrl -ProwlarrApiKey `$ProwlarrKey -SonarrUrl `$SonarrUrl -SonarrApiKey `$SonarrKey -DownloadClientName 'eMuleBB Suite' -SkipProwlarrSync -NoRetry
    }
    Invoke-StepWithRetry -Name 'Prowlarr application sync' -Operation {
        & (Join-Path `$Root 'apps\eMuleBB\scripts\Register-ArrStack.ps1') -SyncProwlarrOnly -ProwlarrUrl `$ProwlarrUrl -ProwlarrApiKey `$ProwlarrKey -NoRetry
    }
}
"@
    $startSuite | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $scriptsDir 'Start-Suite.ps1')
    @"
#Requires -Version 5.1
`$ErrorActionPreference = 'Stop'
`$Root = '$rootLiteral'
`$ConfigPath = Join-Path `$Root 'manifests\suite-config.json'
`$EmuleExeName = 'emulebb.exe'
if (Test-Path -LiteralPath `$ConfigPath) {
    try {
        `$Config = Get-Content -Raw -LiteralPath `$ConfigPath | ConvertFrom-Json
        if (-not [string]::IsNullOrWhiteSpace([string]`$Config.emulebbExecutableName)) {
            `$EmuleExeName = [string]`$Config.emulebbExecutableName
        }
    } catch {
        Write-Warning "Could not read `$ConfigPath. Using default eMuleBB executable name. `$(`$_.Exception.Message)"
    }
}
`$amutorrentServer = Join-Path `$Root 'apps\aMuTorrent\server\server.js'
`$serviceExecutables = @(
    (Join-Path (Join-Path `$Root 'apps\eMuleBB') `$EmuleExeName),
    (Join-Path `$Root 'apps\Prowlarr\Prowlarr.exe'),
    (Join-Path `$Root 'apps\Radarr\Radarr.exe'),
    (Join-Path `$Root 'apps\Sonarr\Sonarr.exe')
)
function Test-SuiteProcess {
    param(`$Process)
    `$executablePath = [string]`$Process.ExecutablePath
    `$commandLine = [string]`$Process.CommandLine
    if (`$Process.Name -eq 'node.exe' -and `$commandLine.IndexOf(`$amutorrentServer, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        return `$true
    }
    if ([string]::IsNullOrWhiteSpace(`$executablePath)) {
        return `$false
    }
    foreach (`$serviceExecutable in `$serviceExecutables) {
        if ([string]::Equals(`$executablePath, `$serviceExecutable, [StringComparison]::OrdinalIgnoreCase)) {
            return `$true
        }
    }
    return `$false
}
`$processes = @(Get-CimInstance Win32_Process | Where-Object { Test-SuiteProcess -Process `$_ })
if (`$processes.Count -eq 0) {
    Write-Host 'No eMuleBB Suite processes are running.'
    exit 0
}
foreach (`$process in `$processes) {
    `$label = if ([string]::IsNullOrWhiteSpace([string]`$process.ExecutablePath)) { [string]`$process.Name } else { [string]`$process.ExecutablePath }
    Write-Host ("Stopping {0} (PID {1})" -f `$label, `$process.ProcessId)
    try {
        Stop-Process -Id `$process.ProcessId -Force -ErrorAction Stop
    } catch {
        Write-Warning "Could not stop PID `$(`$process.ProcessId): `$(`$_.Exception.Message)"
    }
}
Write-Host 'eMuleBB Suite stop request completed.'
"@ | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $scriptsDir 'Stop-Suite.ps1')
    @"
#Requires -Version 5.1
`$ErrorActionPreference = 'Stop'
`$Root = '$rootLiteral'
`$Config = Get-Content -Raw -LiteralPath (Join-Path `$Root 'manifests\suite-config.json') | ConvertFrom-Json
Write-Host "Suite root: `$Root"
Write-Host "Bundle: `$(`$Config.bundle)"
foreach (`$name in @('emulebb','amutorrent','prowlarr','radarr','sonarr')) {
    `$service = `$Config.services.`$name
    Write-Host ("{0}: {1}:{2}" -f `$name, `$service.bindAddress, `$service.port)
}
`$amutorrentServer = Join-Path `$Root 'apps\aMuTorrent\server\server.js'
`$emuleExeName = if ([string]::IsNullOrWhiteSpace([string]`$Config.emulebbExecutableName)) { 'emulebb.exe' } else { [string]`$Config.emulebbExecutableName }
`$serviceExecutables = @(
    (Join-Path (Join-Path `$Root 'apps\eMuleBB') `$emuleExeName),
    (Join-Path `$Root 'apps\Prowlarr\Prowlarr.exe'),
    (Join-Path `$Root 'apps\Radarr\Radarr.exe'),
    (Join-Path `$Root 'apps\Sonarr\Sonarr.exe')
)
function Test-SuiteProcess {
    param(`$Process)
    `$executablePath = [string]`$Process.ExecutablePath
    `$commandLine = [string]`$Process.CommandLine
    if (`$Process.Name -eq 'node.exe' -and `$commandLine.IndexOf(`$amutorrentServer, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        return `$true
    }
    if ([string]::IsNullOrWhiteSpace(`$executablePath)) {
        return `$false
    }
    foreach (`$serviceExecutable in `$serviceExecutables) {
        if ([string]::Equals(`$executablePath, `$serviceExecutable, [StringComparison]::OrdinalIgnoreCase)) {
            return `$true
        }
    }
    return `$false
}
`$processes = @(Get-CimInstance Win32_Process | Where-Object { Test-SuiteProcess -Process `$_ } | Select-Object ProcessId, Name, ExecutablePath, CommandLine)
if (`$processes.Count -eq 0) {
    Write-Host 'No eMuleBB Suite processes are running.'
} else {
    `$processes
}
"@ | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $scriptsDir 'Get-SuiteStatus.ps1')
    @"
#Requires -Version 5.1
`$ErrorActionPreference = 'Stop'
`$Root = '$rootLiteral'
Write-Host 'Suite root: $rootLiteral'
Write-Host 'Config: ' (Join-Path '$rootLiteral' 'manifests\suite-config.json')
Write-Host 'Manual reconfiguration: edit manifests\suite-config.json, profiles\emulebb\config\preferences.ini, and Arr config.xml files consistently.'
& (Join-Path '$rootLiteral' 'scripts\Get-SuiteStatus.ps1')
"@ | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $scriptsDir 'Test-Suite.ps1')
    @"
#Requires -Version 5.1
`$ErrorActionPreference = 'Stop'
& (Join-Path '$rootLiteral' 'scripts\Stop-Suite.ps1')
& (Join-Path '$rootLiteral' 'scripts\Install-eMuleBBSuite.ps1') -ConfigFile (Join-Path '$rootLiteral' 'manifests\suite-config.json') -NonInteractive -Force -Version '$versionLiteral' -Platform '$platformLiteral'
"@ | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $scriptsDir 'Update-Suite.ps1')
    $packagedInstaller = Join-Path $script:Root 'apps\eMuleBB\scripts\Install-eMuleBBSuite.ps1'
    if (-not (Test-Path -LiteralPath $packagedInstaller)) {
        throw "Installed eMuleBB package did not include scripts\Install-eMuleBBSuite.ps1."
    }
    Copy-Item -Force -LiteralPath $packagedInstaller -Destination (Join-Path $scriptsDir 'Install-eMuleBBSuite.ps1')
}

function Write-InstallManifest {
    param([hashtable]$Config, [hashtable]$ProfileImport, [hashtable]$Symbols)
    if ($DryRun) {
        return
    }
    $manifestDir = Join-Path $script:Root 'manifests'
    New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null
    @{
        schema = 'emulebb.suite-install.v1'
        installedAtUtc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
        bundle = $Config.bundle
        version = $Config.version
        platform = $Config.platform
        installKind = $Config.installKind
        installRoot = $script:Root
        emulebbPackageFlavor = $Config.emulebbPackageFlavor
        emulebbExecutableName = $Config.emulebbExecutableName
        profileImport = $ProfileImport
        symbols = $Symbols
        services = @{
            emulebb = @{ bindAddress = $Config.services.emulebb.bindAddress; port = $Config.services.emulebb.port; apiKeyPresent = -not [string]::IsNullOrWhiteSpace($Config.services.emulebb.apiKey) }
            amutorrent = @{ bindAddress = $Config.services.amutorrent.bindAddress; port = $Config.services.amutorrent.port }
            prowlarr = @{ bindAddress = $Config.services.prowlarr.bindAddress; port = $Config.services.prowlarr.port; apiKeyPresent = -not [string]::IsNullOrWhiteSpace($Config.services.prowlarr.apiKey) }
            radarr = @{ bindAddress = $Config.services.radarr.bindAddress; port = $Config.services.radarr.port; apiKeyPresent = -not [string]::IsNullOrWhiteSpace($Config.services.radarr.apiKey) }
            sonarr = @{ bindAddress = $Config.services.sonarr.bindAddress; port = $Config.services.sonarr.port; apiKeyPresent = -not [string]::IsNullOrWhiteSpace($Config.services.sonarr.apiKey) }
        }
        p2p = @{
            bindInterfacePresent = -not [string]::IsNullOrWhiteSpace($Config.p2p.bindInterface)
            blockNetworkWhenBindUnavailableAtStartup = [bool]$Config.p2p.blockNetworkWhenBindUnavailableAtStartup
            networkGuardMode = [string]$Config.p2p.networkGuardMode
            networkGuardAllowedCIDRsPresent = -not [string]::IsNullOrWhiteSpace($Config.p2p.networkGuardAllowedCIDRs)
        }
    } | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $manifestDir 'suite-install.json')
}

$script:SuiteConfig = Resolve-SuiteConfig
if (-not $NonInteractive -and (Test-InteractiveConsole)) {
    Invoke-InstallWizard -Config $script:SuiteConfig
}
$rawInstallRoot = [string]$script:SuiteConfig.installRoot
Assert-InstallRootValue -Path $rawInstallRoot
try {
    $script:Root = [IO.Path]::GetFullPath($rawInstallRoot)
} catch {
    throw "InstallRoot is not a valid Windows path: $rawInstallRoot. Choose a short absolute folder such as C:\eMuleBBSuite or C:\eMuleBB."
}
$script:SuiteConfig.installRoot = $script:Root
Assert-NoSpaces -Path $script:Root
Resolve-ServicePorts -Config $script:SuiteConfig
Assert-SuiteConfig -Config $script:SuiteConfig
Write-ConfigSummary -Config $script:SuiteConfig

if ((Test-Path -LiteralPath $script:Root) -and -not $Force -and -not $DryRun) {
    throw "InstallRoot already exists: $script:Root. Choose a different -InstallRoot, or rerun with -Force to refresh the suite files in this folder. Back up the folder first if you manually edited configuration."
}
if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $script:Root | Out-Null
}

$script:SuiteConfig.services.emulebb.apiKey = Resolve-ApiKey -Value $script:SuiteConfig.services.emulebb.apiKey -Name 'eMuleBB API key'
$script:SuiteConfig.services.prowlarr.apiKey = Resolve-ApiKey -Value $script:SuiteConfig.services.prowlarr.apiKey -Name 'Prowlarr API key'
$script:SuiteConfig.services.radarr.apiKey = Resolve-ApiKey -Value $script:SuiteConfig.services.radarr.apiKey -Name 'Radarr API key'
$script:SuiteConfig.services.sonarr.apiKey = Resolve-ApiKey -Value $script:SuiteConfig.services.sonarr.apiKey -Name 'Sonarr API key'
$script:SuiteConfig.credentials.password = Resolve-Secret -Value $script:SuiteConfig.credentials.password -Name 'Suite password'

$releaseBase = Resolve-OptionalValue -Value $script:SuiteConfig.releaseBaseUrl -Default "https://github.com/emulebb/emulebb/releases/download/emulebb-v$($script:SuiteConfig.version)"
$amutorrentVersion = Resolve-OptionalValue -Value $script:SuiteConfig.amutorrentVersion -Default $script:SuiteConfig.version
$amutorrentReleaseBase = Resolve-OptionalValue -Value $script:SuiteConfig.amutorrentReleaseBaseUrl -Default $releaseBase
$nodeBase = Resolve-OptionalValue -Value $script:SuiteConfig.nodeBaseUrl -Default "https://nodejs.org/dist/$NodeVersion"
$dependencyManifestPayload = Load-DependencyManifestPayload -ManifestPath $script:SuiteConfig.dependencyManifest
$assetArch = if ($script:SuiteConfig.platform -eq 'ARM64') { 'arm64' } else { 'x64' }
$emulebbAssetSuffix = if ($script:SuiteConfig.emulebbPackageFlavor -eq 'diagnostics') { '-diagnostics' } else { '' }
$appRoot = Join-Path $script:Root 'apps'
$emulebbPackage = Save-PackageZip -Name 'eMuleBB' -ZipUrl "$releaseBase/emulebb-$($script:SuiteConfig.version)$emulebbAssetSuffix-$assetArch.zip" -ManifestUrl "$releaseBase/emulebb-$($script:SuiteConfig.version)$emulebbAssetSuffix-$assetArch.manifest.json" -LocalZip ([string]$script:SuiteConfig.packageSources.emulebb.zip) -LocalManifest ([string]$script:SuiteConfig.packageSources.emulebb.manifest)
$amutorrentPackage = $null
if ($script:SuiteConfig.bundle -ne 'Core') {
    $amutorrentPackage = Save-PackageZip -Name 'aMuTorrent' -ZipUrl "$amutorrentReleaseBase/emulebb-$amutorrentVersion-amutorrent-x64.zip" -ManifestUrl "$amutorrentReleaseBase/emulebb-$amutorrentVersion-amutorrent-x64.manifest.json" -LocalZip ([string]$script:SuiteConfig.packageSources.amutorrent.zip) -LocalManifest ([string]$script:SuiteConfig.packageSources.amutorrent.manifest)
}

Install-VerifiedReleaseZip -Name 'eMuleBB' -ArchivePath $emulebbPackage.ArchivePath -Destination $appRoot
Assert-EmulebbExecutableInstalled -Config $script:SuiteConfig

if ($script:SuiteConfig.bundle -ne 'Core') {
    Install-VerifiedReleaseZip -Name 'aMuTorrent' -ArchivePath $amutorrentPackage.ArchivePath -Destination $appRoot
    $nodeSpec = Load-NodeSpec -Payload $dependencyManifestPayload -Platform $script:SuiteConfig.platform
    $nodeArchive = Join-Path (Join-Path $script:Root 'downloads-cache') $nodeSpec.FileName
    $nodeUrl = if ([string]::IsNullOrWhiteSpace($nodeSpec.Url)) { "$nodeBase/$($nodeSpec.FileName)" } else { [string]$nodeSpec.Url }
    Write-Step "Downloading Node runtime $($nodeSpec.FileName)"
    Invoke-Download -Url $nodeUrl -Destination $nodeArchive
    Write-Step "Verifying Node runtime"
    Assert-FileHash -Path $nodeArchive -ExpectedSha256 $nodeSpec.Sha256
    Write-Step "Extracting Node runtime"
    Expand-ZipSafe -Archive $nodeArchive -Destination (Join-Path $script:Root 'runtime\node')
}

if ($script:SuiteConfig.bundle -eq 'Full') {
    $dependencies = Load-DependencyManifest -Payload $dependencyManifestPayload -Channel $script:SuiteConfig.dependencyChannel
    foreach ($name in @('prowlarr', 'radarr', 'sonarr')) {
        Install-ArrDependency -Name $name -Spec $dependencies[$name] -Channel $script:SuiteConfig.dependencyChannel
    }
}

$script:ProfileImport = Write-EmuleProfile -Config $script:SuiteConfig
$script:Symbols = Copy-OptionalEmuleSymbols -Config $script:SuiteConfig
if ($script:SuiteConfig.bundle -eq 'Full') {
    Write-ArrConfig -Name 'prowlarr' -Port $script:SuiteConfig.services.prowlarr.port -BindAddress $script:SuiteConfig.services.prowlarr.bindAddress -ApiKey $script:SuiteConfig.services.prowlarr.apiKey -Username $script:SuiteConfig.credentials.username -Password $script:SuiteConfig.credentials.password
    Write-ArrConfig -Name 'radarr' -Port $script:SuiteConfig.services.radarr.port -BindAddress $script:SuiteConfig.services.radarr.bindAddress -ApiKey $script:SuiteConfig.services.radarr.apiKey -Username $script:SuiteConfig.credentials.username -Password $script:SuiteConfig.credentials.password
    Write-ArrConfig -Name 'sonarr' -Port $script:SuiteConfig.services.sonarr.port -BindAddress $script:SuiteConfig.services.sonarr.bindAddress -ApiKey $script:SuiteConfig.services.sonarr.apiKey -Username $script:SuiteConfig.credentials.username -Password $script:SuiteConfig.credentials.password
}
Write-SuiteConfigFile -Config $script:SuiteConfig
Write-CredentialsFile -Config $script:SuiteConfig
Write-SuiteScripts -Config $script:SuiteConfig
Write-InstallManifest -Config $script:SuiteConfig -ProfileImport $script:ProfileImport -Symbols $script:Symbols

if (-not $KeepDownloads -and -not $DryRun) {
    Remove-Item -Recurse -Force -LiteralPath (Join-Path $script:Root 'downloads-cache') -ErrorAction SilentlyContinue
}
if (-not $NoStart -and -not $DryRun) {
    & (Join-Path $script:Root 'scripts\Start-Suite.ps1')
} elseif ($NoStart -and -not $DryRun) {
    Write-Step "Start skipped because -NoStart was used. Before adding movies or series, run $(Join-Path $script:Root 'scripts\Start-Suite.ps1') once to start services, register integrations, and create Radarr/Sonarr root folders."
}
Write-Step "Installed $($script:SuiteConfig.bundle) bundle at $script:Root"
if (-not $DryRun -and -not $NonInteractive) {
    Start-Process -FilePath (Join-Path $script:Root 'credentials.html') | Out-Null
}
