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

function Get-ReleaseTag {
    if ([string]::IsNullOrWhiteSpace($Version)) {
        return $null
    }
    if ($Version -match '^emulebb-(v|nightly-)') {
        return $Version
    }
    if ($Version -match '^\d+\.\d+\.\d+-nightly\.(\d{8})\.([0-9a-fA-F]+)$') {
        return "emulebb-nightly-$($Matches[1])-$($Matches[2])"
    }
    return "emulebb-v$Version"
}

function Test-SupportedReleaseTag {
    param([string]$Tag)
    return $Tag -match '^emulebb-v.+' -or $Tag -match '^emulebb-nightly-\d{8}-[0-9a-fA-F]+(-run\d+)?$'
}

function Get-Release {
    if (-not [string]::IsNullOrWhiteSpace($Version)) {
        $tag = Get-ReleaseTag
        return Invoke-RestMethod -Uri "$ApiBase/repos/$Repository/releases/tags/$tag" -Headers @{ 'User-Agent' = $UserAgent }
    }
    $releases = Invoke-RestMethod -Uri "$ApiBase/repos/$Repository/releases" -Headers @{ 'User-Agent' = $UserAgent }
    $nightlyFallback = $null
    foreach ($release in @($releases)) {
        if ($release.draft) {
            continue
        }
        $tag = [string]$release.tag_name
        if (-not (Test-SupportedReleaseTag -Tag $tag)) {
            continue
        }
        if ($release.prerelease -and -not $IncludePrerelease) {
            if ($tag -match '^emulebb-nightly-' -and $null -eq $nightlyFallback) {
                $nightlyFallback = $release
            }
            continue
        }
        return $release
    }
    if ($null -ne $nightlyFallback) {
        return $nightlyFallback
    }
    throw 'No matching eMuleBB release was found.'
}

function Get-ReleaseVersion {
    param([object]$Release, [string]$AssetArch)
    $tag = [string]$Release.tag_name
    if ($tag -match '^emulebb-v(.+)$') {
        return $Matches[1]
    }
    if ($tag -match '^emulebb-nightly-\d{8}-[0-9a-fA-F]+(-run\d+)?$') {
        if ([string]::IsNullOrWhiteSpace($AssetArch)) {
            throw "Cannot resolve nightly package version without an asset architecture."
        }
        $escapedAssetArch = [regex]::Escape($AssetArch)
        foreach ($asset in @($Release.assets)) {
            $name = [string]$asset.name
            if ($name -match "^emulebb-(.+)-$escapedAssetArch\.zip$") {
                return $Matches[1]
            }
        }
        throw "Nightly release $tag does not contain an eMuleBB $AssetArch ZIP asset."
    }
    throw "Unexpected release tag: $tag"
}

function Get-ReleaseBaseUrl {
    param([object]$Release)
    return "https://github.com/$Repository/releases/download/$($Release.tag_name)"
}

function Get-AssetUrl {
    param([object]$Release, [string]$Name)
    $url = Find-AssetUrl -Release $Release -Name $Name
    if (-not [string]::IsNullOrWhiteSpace($url)) {
        return $url
    }
    throw "Release $($Release.tag_name) does not contain asset $Name."
}

function Find-AssetUrl {
    param([object]$Release, [string]$Name)
    foreach ($asset in @($Release.assets)) {
        if ([string]$asset.name -eq $Name) {
            return [string]$asset.browser_download_url
        }
    }
    return ''
}

function Test-InteractiveConsole {
    try {
        return -not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected
    } catch {
        return $false
    }
}

function Resolve-EffectiveBundle {
    param([object]$Release, [string]$RequestedBundle, [string]$ResolvedPlatform, [string]$ResolvedVersion)
    if ($RequestedBundle -eq 'Core') {
        return 'Core'
    }
    if ($ResolvedPlatform -ne 'x64') {
        throw 'Controller and Full bundles are x64-only in v1 because aMuTorrent native node_modules are packaged for x64.'
    }
    $missing = @()
    foreach ($assetName in @(
        "emulebb-$ResolvedVersion-amutorrent-x64.manifest.json",
        "emulebb-$ResolvedVersion-amutorrent-x64.zip"
    )) {
        if ([string]::IsNullOrWhiteSpace((Find-AssetUrl -Release $Release -Name $assetName))) {
            $missing += $assetName
        }
    }
    if ($missing.Count -eq 0) {
        return $RequestedBundle
    }
    $message = "Release $($Release.tag_name) does not contain required $RequestedBundle asset(s): $($missing -join ', ')."
    if ($NonInteractive -or -not (Test-InteractiveConsole)) {
        throw "$message Re-run with -Bundle Core or choose a release/nightly with Full suite assets."
    }
    Write-Warning "$message Core can still be installed."
    $choice = Read-Host 'Install Core instead? [y/N]'
    if ($choice -match '^[Yy]') {
        return 'Core'
    }
    throw 'Bootstrap cancelled because required suite assets are missing.'
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
$assetArch = if ($resolvedPlatform -eq 'ARM64') { 'arm64' } else { 'x64' }
$resolvedVersion = Get-ReleaseVersion -Release $release -AssetArch $assetArch
$releaseBaseUrl = Get-ReleaseBaseUrl -Release $release
$zipName = "emulebb-$resolvedVersion-$assetArch.zip"
$manifestName = "emulebb-$resolvedVersion-$assetArch.manifest.json"
$zipUrl = Get-AssetUrl -Release $release -Name $zipName
$manifestUrl = Get-AssetUrl -Release $release -Name $manifestName
$effectiveBundle = Resolve-EffectiveBundle -Release $release -RequestedBundle $Bundle -ResolvedPlatform $resolvedPlatform -ResolvedVersion $resolvedVersion
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
$installerParams = [ordered]@{
    Bundle = $effectiveBundle
    InstallRoot = $InstallRoot
    Version = $resolvedVersion
    Platform = $resolvedPlatform
    ReleaseBaseUrl = $releaseBaseUrl
}
if ($NonInteractive) { $installerParams['NonInteractive'] = $true }
if ($NoStart) { $installerParams['NoStart'] = $true }
if ($Force) { $installerParams['Force'] = $true }
if ($KeepDownloads) { $installerParams['KeepDownloads'] = $true }
if (-not [string]::IsNullOrWhiteSpace($P2PBindInterface)) { $installerParams['P2PBindInterface'] = $P2PBindInterface }
if (-not [string]::IsNullOrWhiteSpace($ControlBindAddress)) { $installerParams['ControlBindAddress'] = $ControlBindAddress }
if (-not [string]::IsNullOrWhiteSpace($EmulebbBindAddress)) { $installerParams['EmulebbBindAddress'] = $EmulebbBindAddress }
if (-not [string]::IsNullOrWhiteSpace($AmutorrentBindAddress)) { $installerParams['AmutorrentBindAddress'] = $AmutorrentBindAddress }
if (-not [string]::IsNullOrWhiteSpace($ProwlarrBindAddress)) { $installerParams['ProwlarrBindAddress'] = $ProwlarrBindAddress }
if (-not [string]::IsNullOrWhiteSpace($RadarrBindAddress)) { $installerParams['RadarrBindAddress'] = $RadarrBindAddress }
if (-not [string]::IsNullOrWhiteSpace($SonarrBindAddress)) { $installerParams['SonarrBindAddress'] = $SonarrBindAddress }
if ($PSBoundParameters.ContainsKey('EmulebbPort')) { $installerParams['EmulebbPort'] = $EmulebbPort }
if ($PSBoundParameters.ContainsKey('AmutorrentPort')) { $installerParams['AmutorrentPort'] = $AmutorrentPort }
if ($PSBoundParameters.ContainsKey('ProwlarrPort')) { $installerParams['ProwlarrPort'] = $ProwlarrPort }
if ($PSBoundParameters.ContainsKey('RadarrPort')) { $installerParams['RadarrPort'] = $RadarrPort }
if ($PSBoundParameters.ContainsKey('SonarrPort')) { $installerParams['SonarrPort'] = $SonarrPort }
if ($AllowRemoteServiceBind) { $installerParams['AllowRemoteServiceBind'] = $true }
$displayArgs = @()
foreach ($name in $installerParams.Keys) {
    $value = $installerParams[$name]
    if ($value -is [bool]) {
        if ($value) {
            $displayArgs += "-$name"
        }
    } else {
        $displayArgs += @("-$name", [string]$value)
    }
}
if ($DryRun) {
    Write-Step "Would run $installer $($displayArgs -join ' ')"
} else {
    & $installer @installerParams
}
if (-not $KeepDownloads -and -not $DryRun) {
    Remove-Item -Recurse -Force -LiteralPath $workRoot -ErrorAction SilentlyContinue
}
