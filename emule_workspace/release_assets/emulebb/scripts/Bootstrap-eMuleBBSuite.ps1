#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Core', 'Controller', 'Full')]
    [string]$Bundle = 'Full',

    [string]$InstallRoot = 'C:\eMuleBBSuite',

    [string]$Version,

    [ValidateSet('x64', 'ARM64')]
    [string]$Platform,

    [string]$P2PBindInterface,
    [string]$ControlBindAddress,
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

    [switch]$IncludePrerelease,
    [switch]$AllowRemoteServiceBind,
    [switch]$NonInteractive,
    [switch]$NoStart,
    [switch]$Force,
    [switch]$DryRun,
    [switch]$KeepDownloads
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Repository = 'emulebb/emulebb'
$ApiBase = 'https://api.github.com'
$UserAgent = 'emulebb-suite-bootstrapper'

function Write-Step {
    param([string]$Message)
    Write-Host "[eMuleBB bootstrap] $Message"
}

function Get-DefaultPlatform {
    if ([string]::IsNullOrWhiteSpace($Platform)) {
        if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
            return 'ARM64'
        }
        return 'x64'
    }
    return $Platform
}

function Get-Release {
    if (-not [string]::IsNullOrWhiteSpace($Version)) {
        return Invoke-RestMethod -Uri "$ApiBase/repos/$Repository/releases/tags/emulebb-v$Version" -Headers @{ 'User-Agent' = $UserAgent }
    }
    $releases = Invoke-RestMethod -Uri "$ApiBase/repos/$Repository/releases" -Headers @{ 'User-Agent' = $UserAgent }
    foreach ($release in @($releases)) {
        if ($release.draft) {
            continue
        }
        if ($release.prerelease -and -not $IncludePrerelease) {
            continue
        }
        return $release
    }
    throw 'No matching eMuleBB release was found.'
}

function Get-ReleaseVersion {
    param([object]$Release)
    $tag = [string]$Release.tag_name
    if ($tag -notmatch '^emulebb-v(.+)$') {
        throw "Unexpected release tag: $tag"
    }
    return $Matches[1]
}

function Get-AssetUrl {
    param([object]$Release, [string]$Name)
    foreach ($asset in @($Release.assets)) {
        if ([string]$asset.name -eq $Name) {
            return [string]$asset.browser_download_url
        }
    }
    throw "Release $($Release.tag_name) does not contain asset $Name."
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
    $previousProgressPreference = $ProgressPreference
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $tmp -Headers @{ 'User-Agent' = $UserAgent }
        Move-Item -Force -LiteralPath $tmp -Destination $Destination
    } finally {
        $ProgressPreference = $previousProgressPreference
        Remove-Item -Force -LiteralPath $tmp -ErrorAction SilentlyContinue
    }
}

function Get-Sha256 {
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
        } finally {
            $sha.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

function Assert-FileHash {
    param([string]$Path, [string]$ExpectedSha256)
    if ($DryRun) {
        return
    }
    $actual = Get-Sha256 -Path $Path
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "SHA256 mismatch for $Path. Expected $ExpectedSha256, got $actual."
    }
}

function Expand-Installer {
    param([string]$Archive, [string]$Destination)
    if ($DryRun) {
        Write-Step "Would extract suite installer from $Archive -> $Destination"
        return (Join-Path $Destination 'Install-eMuleBBSuite.ps1')
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $entry = $zip.GetEntry('eMuleBB/scripts/Install-eMuleBBSuite.ps1')
        if ($null -eq $entry) {
            throw 'Release ZIP does not contain eMuleBB/scripts/Install-eMuleBBSuite.ps1.'
        }
        $target = Join-Path $Destination 'Install-eMuleBBSuite.ps1'
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
        return $target
    } finally {
        $zip.Dispose()
    }
}

$resolvedPlatform = Get-DefaultPlatform
$release = Get-Release
$resolvedVersion = Get-ReleaseVersion -Release $release
$assetArch = if ($resolvedPlatform -eq 'ARM64') { 'arm64' } else { 'x64' }
$zipName = "emulebb-$resolvedVersion-$assetArch.zip"
$manifestName = "emulebb-$resolvedVersion-$assetArch.manifest.json"
$zipUrl = Get-AssetUrl -Release $release -Name $zipName
$manifestUrl = Get-AssetUrl -Release $release -Name $manifestName
$workRoot = Join-Path $env:TEMP "emulebb-suite-bootstrap-$resolvedVersion-$assetArch"
$zipPath = Join-Path $workRoot $zipName
$manifestPath = Join-Path $workRoot $manifestName
$extractRoot = Join-Path $workRoot 'installer'

Write-Step "Resolved release $($release.tag_name) for $resolvedPlatform"
Invoke-Download -Url $manifestUrl -Destination $manifestPath
Invoke-Download -Url $zipUrl -Destination $zipPath
if (-not $DryRun) {
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    Assert-FileHash -Path $zipPath -ExpectedSha256 ([string]$manifest.sha256)
}
$installer = Expand-Installer -Archive $zipPath -Destination $extractRoot
$args = @(
    '-Bundle', $Bundle,
    '-InstallRoot', $InstallRoot,
    '-Version', $resolvedVersion,
    '-Platform', $resolvedPlatform
)
if ($NonInteractive) { $args += '-NonInteractive' }
if ($NoStart) { $args += '-NoStart' }
if ($Force) { $args += '-Force' }
if ($KeepDownloads) { $args += '-KeepDownloads' }
if (-not [string]::IsNullOrWhiteSpace($P2PBindInterface)) { $args += @('-P2PBindInterface', $P2PBindInterface) }
if (-not [string]::IsNullOrWhiteSpace($ControlBindAddress)) { $args += @('-ControlBindAddress', $ControlBindAddress) }
if (-not [string]::IsNullOrWhiteSpace($EmulebbBindAddress)) { $args += @('-EmulebbBindAddress', $EmulebbBindAddress) }
if (-not [string]::IsNullOrWhiteSpace($AmutorrentBindAddress)) { $args += @('-AmutorrentBindAddress', $AmutorrentBindAddress) }
if (-not [string]::IsNullOrWhiteSpace($ProwlarrBindAddress)) { $args += @('-ProwlarrBindAddress', $ProwlarrBindAddress) }
if (-not [string]::IsNullOrWhiteSpace($RadarrBindAddress)) { $args += @('-RadarrBindAddress', $RadarrBindAddress) }
if (-not [string]::IsNullOrWhiteSpace($SonarrBindAddress)) { $args += @('-SonarrBindAddress', $SonarrBindAddress) }
if ($PSBoundParameters.ContainsKey('EmulebbPort')) { $args += @('-EmulebbPort', $EmulebbPort) }
if ($PSBoundParameters.ContainsKey('AmutorrentPort')) { $args += @('-AmutorrentPort', $AmutorrentPort) }
if ($PSBoundParameters.ContainsKey('ProwlarrPort')) { $args += @('-ProwlarrPort', $ProwlarrPort) }
if ($PSBoundParameters.ContainsKey('RadarrPort')) { $args += @('-RadarrPort', $RadarrPort) }
if ($PSBoundParameters.ContainsKey('SonarrPort')) { $args += @('-SonarrPort', $SonarrPort) }
if ($AllowRemoteServiceBind) { $args += '-AllowRemoteServiceBind' }
if ($DryRun) {
    Write-Step "Would run $installer $($args -join ' ')"
} else {
    & $installer @args
}
if (-not $KeepDownloads -and -not $DryRun) {
    Remove-Item -Recurse -Force -LiteralPath $workRoot -ErrorAction SilentlyContinue
}
