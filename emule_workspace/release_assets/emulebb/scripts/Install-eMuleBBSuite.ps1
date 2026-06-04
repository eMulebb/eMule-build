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

    [ValidateRange(1, 65535)]
    [int]$EmulebbPort = 4711,
    [ValidateRange(1, 65535)]
    [int]$AmutorrentPort = 4000,
    [ValidateRange(1, 65535)]
    [int]$ProwlarrPort = 9696,
    [ValidateRange(1, 65535)]
    [int]$RadarrPort = 7878,
    [ValidateRange(1, 65535)]
    [int]$SonarrPort = 8989,

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
if ($Bundle -like '-*') {
    throw "Install-eMuleBBSuite.ps1 was invoked with positional parameter strings. Call it with named parameters, for example -Bundle Full, not an argv string array."
}
$script:InstallerBoundParameters = $PSBoundParameters

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
        throw "InstallRoot must not contain spaces for v1 suite installs: $Path"
    }
}

function New-Secret {
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Resolve-Secret {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return New-Secret
    }
    return $Value
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
    if ([string]::IsNullOrWhiteSpace($Address) -or -not $Address.StartsWith('192.168.')) {
        return $false
    }
    try {
        $parsed = [Net.IPAddress]::Parse($Address)
    } catch {
        return $false
    }
    return $parsed.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork
}

function Get-AutoLanBindAddress {
    $candidates = @()
    try {
        $candidates += @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.AddressState -eq 'Preferred' } |
            ForEach-Object {
                [pscustomobject]@{
                    InterfaceAlias = [string]$_.InterfaceAlias
                    IPAddress = [string]$_.IPAddress
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
                    }
                })
        } catch {
        }
    }
    foreach ($candidate in $candidates) {
        if ((Test-AutoLanIPv4Address -Address $candidate.IPAddress) -and -not (Test-VpnLikeInterfaceName -Name $candidate.InterfaceAlias)) {
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

function New-SuiteConfig {
    $controlBind = Resolve-OptionalValue -Value $ControlBindAddress -Default (Get-DefaultControlBindAddress)
    $config = [ordered]@{
        schema = 'emulebb.suite-config.v1'
        bundle = $Bundle
        version = $Version
        platform = $Platform
        installKind = $InstallKind
        installRoot = $InstallRoot
        dependencyChannel = $DependencyChannel
        releaseBaseUrl = $ReleaseBaseUrl
        amutorrentReleaseBaseUrl = $AmutorrentReleaseBaseUrl
        amutorrentVersion = $AmutorrentVersion
        emulebbPackageFlavor = $EmulebbPackageFlavor
        emulebbExecutableName = (Get-EmulebbExecutableNameForFlavor -PackageFlavor $EmulebbPackageFlavor)
        nodeBaseUrl = $NodeBaseUrl
        dependencyManifest = $DependencyManifest
        importProfileDir = $ImportProfileDir
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

function Get-BindableInterfaceNames {
    $names = @()
    try {
        $names = @(Get-NetIPConfiguration -ErrorAction Stop |
            Where-Object { $_.IPv4Address -and $_.NetAdapter.Status -eq 'Up' } |
            ForEach-Object { $_.InterfaceAlias } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique)
    } catch {
        try {
            $names = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
                Where-Object { $_.IPAddress -notlike '169.254.*' } |
                ForEach-Object { $_.InterfaceAlias } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Sort-Object -Unique)
        } catch {
            $names = @()
        }
    }
    return $names
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
                if (Test-HasRemoteServiceBind -Config $Config) {
                    $confirm = Read-WizardChoice -Prompt 'Non-loopback control-service bind detected' -Choices @('Allow remote control-service bind', 'Back to service binds') -DefaultIndex 1
                    if ($confirm -lt 0 -or $confirm -eq 1) { continue }
                    $Config.allowRemoteServiceBind = $true
                } else {
                    $Config.allowRemoteServiceBind = $false
                }
                $step++
            }
            2 {
                $names = @(Get-BindableInterfaceNames)
                $choices = @('No P2P bind')
                $choices += $names
                $choices += 'Custom interface name'
                $choice = Read-WizardChoice -Prompt 'eMuleBB P2P bind interface' -Choices $choices -DefaultIndex 0
                if ($choice -lt 0) { $step--; continue }
                if ($choice -eq 0) {
                    $Config.p2p.bindInterface = ''
                } elseif ($choice -le $names.Count) {
                    $Config.p2p.bindInterface = $names[$choice - 1]
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
                        $Config.services[$serviceName].port = [int](Read-WizardValue -Prompt "$serviceName port" -Default ([string]$Config.services[$serviceName].port))
                    }
                }
                $step++
            }
            4 {
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
    if (-not $AllowRemote) {
        Write-Warning "$ServiceName bind address $Address is not loopback."
        return
    }
    Write-Warning "$ServiceName will bind to non-loopback address $Address."
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
    Assert-EmulebbExecutableName -PackageFlavor ([string]$Config.emulebbPackageFlavor) -ExecutableName ([string]$Config.emulebbExecutableName)
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
    $previousProgressPreference = $ProgressPreference
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
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $tmp
        Move-Item -Force -LiteralPath $tmp -Destination $Destination
    } catch {
        throw "Failed to download $Url -> $Destination. $($_.Exception.Message)"
    } finally {
        $ProgressPreference = $previousProgressPreference
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
    Invoke-Download -Url $ManifestUrl -Destination $manifestPath
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
    Assert-FileHash -Path $archivePath -ExpectedSha256 $expectedHash
    return [ordered]@{
        Name = $Name
        ArchivePath = $archivePath
    }
}

function Install-VerifiedReleaseZip {
    param([string]$Name, [string]$ArchivePath, [string]$Destination)
    $downloadRoot = Join-Path $script:Root 'downloads-cache'
    $extractRoot = Join-Path $downloadRoot ("extract-$Name")
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
    Invoke-Download -Url $assetUrl -Destination $archivePath
    if ([string]::IsNullOrWhiteSpace($Spec.Sha256)) {
        throw "$Name dependency download requires a SHA256 hash. Use pinned dependencies or provide -DependencyManifest with sha256."
    }
    Assert-FileHash -Path $archivePath -ExpectedSha256 $Spec.Sha256
    Expand-ZipSafe -Archive $archivePath -Destination $extractRoot
    Write-Step "$Name installed"
}

function Write-ArrConfig {
    param([string]$Name, [int]$Port, [string]$BindAddress, [string]$ApiKey)
    $dataDir = Join-Path (Join-Path $script:Root 'data') $Name
    if (-not $DryRun) {
        New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
        @(
            '<Config>'
            '  <LogLevel>info</LogLevel>'
            "  <Port>$Port</Port>"
            '  <UrlBase></UrlBase>'
            "  <BindAddress>$BindAddress</BindAddress>"
            '  <EnableSsl>False</EnableSsl>'
            "  <ApiKey>$ApiKey</ApiKey>"
            '  <AuthenticationMethod>None</AuthenticationMethod>'
            '  <AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>'
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
        [string]$Newline
    )
    foreach ($pendingKey in @($Pending.Keys)) {
        if ($pendingKey.StartsWith("$Section|")) {
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
            Append-PendingIniValues -Output $output -Pending $pending -Section $currentSection -Newline $newline
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
    Append-PendingIniValues -Output $output -Pending $pending -Section $currentSection -Newline $newline
    foreach ($entry in @($pending.Values)) {
        $sectionName = [string]$entry.Section
        if (-not $seenSections.ContainsKey($sectionName.ToLowerInvariant())) {
            $output.Add("[$sectionName]$newline")
            $seenSections[$sectionName.ToLowerInvariant()] = $true
        }
        $output.Add("$($entry.Key)=$($entry.Value)$newline")
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
`$Existing = Get-Process | Where-Object { `$_.Path -and [string]::Equals(`$_.Path, `$Emule, [StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1
if (`$Existing) {
    Write-Host "eMuleBB is already running: PID `$(`$Existing.Id)"
    return
}
Start-Process -FilePath `$Emule -ArgumentList @('-c', (Join-Path `$Root 'profiles\emulebb')) | Out-Null
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
function Wait-Json {
    param([string]`$Uri, [hashtable]`$Headers = @{})
    for (`$i = 0; `$i -lt 90; `$i++) {
        try {
            Invoke-RestMethod -Uri `$Uri -Headers `$Headers -TimeoutSec 2 | Out-Null
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "Timed out waiting for `$Uri"
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
    param([string]`$FilePath, [string[]]`$ArgumentList = @(), [string]`$WorkingDirectory = '', [string]`$CommandLineContains = '', [switch]`$Hidden)
    if (Test-ProcessRunning -ExecutablePath `$FilePath -CommandLineContains `$CommandLineContains) {
        Write-Host "Already running: `$FilePath"
        return
    }
    `$startArgs = @{
        FilePath = `$FilePath
        ArgumentList = `$ArgumentList
    }
    if (-not [string]::IsNullOrWhiteSpace(`$WorkingDirectory)) { `$startArgs.WorkingDirectory = `$WorkingDirectory }
    if (`$Hidden) { `$startArgs.WindowStyle = 'Hidden' }
    Start-Process @startArgs | Out-Null
}
`$Bundle = [string]`$Config.bundle
`$EmuleHost = Get-ClientHost `$Config.services.emulebb.bindAddress
`$EmulePort = [int]`$Config.services.emulebb.port
`$EmuleUrl = "http://`$(`$EmuleHost):`$EmulePort"
`$EmuleKey = [string]`$Config.services.emulebb.apiKey
`$env:EMULEBB_ENABLED = 'true'
`$env:EMULEBB_HOST = `$EmuleHost
`$env:EMULEBB_PORT = [string]`$EmulePort
`$env:EMULEBB_API_KEY = `$EmuleKey
`$env:EMULEBB_USE_SSL = 'false'
`$env:AMUTORRENT_DATA_DIR = Join-Path `$Root 'data\amutorrent'
`$env:PORT = [string]`$Config.services.amutorrent.port
`$env:BIND_ADDRESS = [string]`$Config.services.amutorrent.bindAddress
`$env:WEB_AUTH_ENABLED = 'false'
`$env:SKIP_SETUP_WIZARD = 'true'
& (Join-Path `$Root 'scripts\Start-eMuleBB.ps1')
if (`$Bundle -eq 'Full') {
    foreach (`$item in @(@('Prowlarr','Prowlarr.exe','data\prowlarr'), @('Radarr','Radarr.exe','data\radarr'), @('Sonarr','Sonarr.exe','data\sonarr'))) {
        `$exe = Get-ChildItem -Path (Join-Path `$Root ('apps\' + `$item[0])) -Filter `$item[1] -Recurse -File | Select-Object -First 1
        if (`$exe) { Start-ProcessIfMissing -FilePath `$exe.FullName -ArgumentList @('/data=' + (Join-Path `$Root `$item[2]), '/nobrowser') }
    }
}
if (`$Bundle -ne 'Core') {
    `$node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
    if (-not `$node) {
        `$nodeMatch = Get-ChildItem -Path (Join-Path `$Root 'runtime\node') -Filter node.exe -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if (`$nodeMatch) { `$node = `$nodeMatch.FullName }
    }
    if (-not (Test-Path -LiteralPath `$node)) { throw 'Node is not available. Re-run Install-eMuleBBSuite.ps1 to install the pinned runtime.' }
    `$amutorrentServer = Join-Path `$Root 'apps\aMuTorrent\server\server.js'
    Start-ProcessIfMissing -FilePath `$node -ArgumentList @(`$amutorrentServer) -WorkingDirectory (Join-Path `$Root 'apps\aMuTorrent') -CommandLineContains `$amutorrentServer -Hidden
}
Wait-Json -Uri "`$EmuleUrl/api/v1/app" -Headers @{ 'X-API-Key' = `$EmuleKey }
if (`$Bundle -ne 'Core') {
    `$AmutorrentHost = Get-ClientHost `$Config.services.amutorrent.bindAddress
    `$AmutorrentUrl = "http://`$(`$AmutorrentHost):`$([int]`$Config.services.amutorrent.port)"
    Wait-Json -Uri "`$AmutorrentUrl/api/config/status"
    & (Join-Path `$Root 'apps\eMuleBB\scripts\Register-aMuTorrent.ps1') -AmutorrentUrl `$AmutorrentUrl -AmutorrentApiKey '' -EmulebbBaseUrl `$EmuleUrl -EmulebbApiKey `$EmuleKey -InstanceName 'eMuleBB Suite' -InstanceId 'emulebb-suite' -NoRetry
}
if (`$Bundle -eq 'Full') {
    `$ProwlarrUrl = "http://`$(Get-ClientHost `$Config.services.prowlarr.bindAddress):`$([int]`$Config.services.prowlarr.port)"
    `$RadarrUrl = "http://`$(Get-ClientHost `$Config.services.radarr.bindAddress):`$([int]`$Config.services.radarr.port)"
    `$SonarrUrl = "http://`$(Get-ClientHost `$Config.services.sonarr.bindAddress):`$([int]`$Config.services.sonarr.port)"
    `$ProwlarrKey = [string]`$Config.services.prowlarr.apiKey
    `$RadarrKey = [string]`$Config.services.radarr.apiKey
    `$SonarrKey = [string]`$Config.services.sonarr.apiKey
    Wait-Json -Uri "`$ProwlarrUrl/api/v1/system/status" -Headers @{ 'X-Api-Key' = `$ProwlarrKey }
    Wait-Json -Uri "`$RadarrUrl/api/v3/system/status" -Headers @{ 'X-Api-Key' = `$RadarrKey }
    Wait-Json -Uri "`$SonarrUrl/api/v3/system/status" -Headers @{ 'X-Api-Key' = `$SonarrKey }
    & (Join-Path `$Root 'apps\eMuleBB\scripts\Register-Prowlarr.ps1') -ProwlarrUrl `$ProwlarrUrl -ProwlarrApiKey `$ProwlarrKey -EmulebbBaseUrl `$EmuleUrl -EmulebbApiKey `$EmuleKey -IndexerName 'eMuleBB Suite' -NoRetry
    & (Join-Path `$Root 'apps\eMuleBB\scripts\Register-ArrStack.ps1') -Target Radarr -EmulebbBaseUrl `$EmuleUrl -EmulebbApiKey `$EmuleKey -ProwlarrUrl `$ProwlarrUrl -ProwlarrApiKey `$ProwlarrKey -RadarrUrl `$RadarrUrl -RadarrApiKey `$RadarrKey -DownloadClientName 'eMuleBB Suite' -NoRetry
    & (Join-Path `$Root 'apps\eMuleBB\scripts\Register-ArrStack.ps1') -Target Sonarr -EmulebbBaseUrl `$EmuleUrl -EmulebbApiKey `$EmuleKey -ProwlarrUrl `$ProwlarrUrl -ProwlarrApiKey `$ProwlarrKey -SonarrUrl `$SonarrUrl -SonarrApiKey `$SonarrKey -DownloadClientName 'eMuleBB Suite' -NoRetry
}
"@
    $startSuite | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $scriptsDir 'Start-Suite.ps1')
    @"
#Requires -Version 5.1
`$ErrorActionPreference = 'Stop'
`$Root = '$rootLiteral'
Get-Process | Where-Object { `$_.Path -and `$_.Path.StartsWith(`$Root, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force
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
Get-Process | Where-Object { `$_.Path -and `$_.Path.StartsWith(`$Root, [StringComparison]::OrdinalIgnoreCase) } | Select-Object Id, ProcessName, Path
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
$script:Root = [IO.Path]::GetFullPath([string]$script:SuiteConfig.installRoot)
$script:SuiteConfig.installRoot = $script:Root
Assert-NoSpaces -Path $script:Root
Assert-SuiteConfig -Config $script:SuiteConfig
Write-ConfigSummary -Config $script:SuiteConfig

if ((Test-Path -LiteralPath $script:Root) -and -not $Force -and -not $DryRun) {
    throw "InstallRoot already exists. Use -Force to refresh: $script:Root"
}
if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $script:Root | Out-Null
}

$script:SuiteConfig.services.emulebb.apiKey = Resolve-Secret $script:SuiteConfig.services.emulebb.apiKey
$script:SuiteConfig.services.prowlarr.apiKey = Resolve-Secret $script:SuiteConfig.services.prowlarr.apiKey
$script:SuiteConfig.services.radarr.apiKey = Resolve-Secret $script:SuiteConfig.services.radarr.apiKey
$script:SuiteConfig.services.sonarr.apiKey = Resolve-Secret $script:SuiteConfig.services.sonarr.apiKey

$releaseBase = Resolve-OptionalValue -Value $script:SuiteConfig.releaseBaseUrl -Default "https://github.com/emulebb/emulebb/releases/download/emulebb-v$($script:SuiteConfig.version)"
$amutorrentVersion = Resolve-OptionalValue -Value $script:SuiteConfig.amutorrentVersion -Default $script:SuiteConfig.version
$amutorrentReleaseBase = Resolve-OptionalValue -Value $script:SuiteConfig.amutorrentReleaseBaseUrl -Default $releaseBase
$nodeBase = Resolve-OptionalValue -Value $script:SuiteConfig.nodeBaseUrl -Default "https://nodejs.org/dist/$NodeVersion"
$dependencyManifestPayload = Load-DependencyManifestPayload -ManifestPath $script:SuiteConfig.dependencyManifest
$assetArch = if ($script:SuiteConfig.platform -eq 'ARM64') { 'arm64' } else { 'x64' }
$emulebbAssetSuffix = if ($script:SuiteConfig.emulebbPackageFlavor -eq 'diagnostics') { '-diagnostics' } else { '' }
$appRoot = Join-Path $script:Root 'apps'
$emulebbPackage = Save-ReleaseZip -Name 'eMuleBB' -ZipUrl "$releaseBase/emulebb-$($script:SuiteConfig.version)$emulebbAssetSuffix-$assetArch.zip" -ManifestUrl "$releaseBase/emulebb-$($script:SuiteConfig.version)$emulebbAssetSuffix-$assetArch.manifest.json"
$amutorrentPackage = $null
if ($script:SuiteConfig.bundle -ne 'Core') {
    $amutorrentPackage = Save-ReleaseZip -Name 'aMuTorrent' -ZipUrl "$amutorrentReleaseBase/emulebb-$amutorrentVersion-amutorrent-x64.zip" -ManifestUrl "$amutorrentReleaseBase/emulebb-$amutorrentVersion-amutorrent-x64.manifest.json"
}

Install-VerifiedReleaseZip -Name 'eMuleBB' -ArchivePath $emulebbPackage.ArchivePath -Destination $appRoot
Assert-EmulebbExecutableInstalled -Config $script:SuiteConfig

if ($script:SuiteConfig.bundle -ne 'Core') {
    Install-VerifiedReleaseZip -Name 'aMuTorrent' -ArchivePath $amutorrentPackage.ArchivePath -Destination $appRoot
    $nodeSpec = Load-NodeSpec -Payload $dependencyManifestPayload -Platform $script:SuiteConfig.platform
    $nodeArchive = Join-Path (Join-Path $script:Root 'downloads-cache') $nodeSpec.FileName
    $nodeUrl = if ([string]::IsNullOrWhiteSpace($nodeSpec.Url)) { "$nodeBase/$($nodeSpec.FileName)" } else { [string]$nodeSpec.Url }
    Invoke-Download -Url $nodeUrl -Destination $nodeArchive
    Assert-FileHash -Path $nodeArchive -ExpectedSha256 $nodeSpec.Sha256
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
    Write-ArrConfig -Name 'prowlarr' -Port $script:SuiteConfig.services.prowlarr.port -BindAddress $script:SuiteConfig.services.prowlarr.bindAddress -ApiKey $script:SuiteConfig.services.prowlarr.apiKey
    Write-ArrConfig -Name 'radarr' -Port $script:SuiteConfig.services.radarr.port -BindAddress $script:SuiteConfig.services.radarr.bindAddress -ApiKey $script:SuiteConfig.services.radarr.apiKey
    Write-ArrConfig -Name 'sonarr' -Port $script:SuiteConfig.services.sonarr.port -BindAddress $script:SuiteConfig.services.sonarr.bindAddress -ApiKey $script:SuiteConfig.services.sonarr.apiKey
}
Write-SuiteConfigFile -Config $script:SuiteConfig
Write-SuiteScripts -Config $script:SuiteConfig
Write-InstallManifest -Config $script:SuiteConfig -ProfileImport $script:ProfileImport -Symbols $script:Symbols

if (-not $KeepDownloads -and -not $DryRun) {
    Remove-Item -Recurse -Force -LiteralPath (Join-Path $script:Root 'downloads-cache') -ErrorAction SilentlyContinue
}
if (-not $NoStart -and -not $DryRun) {
    & (Join-Path $script:Root 'scripts\Start-Suite.ps1')
}
Write-Step "Installed $($script:SuiteConfig.bundle) bundle at $script:Root"
