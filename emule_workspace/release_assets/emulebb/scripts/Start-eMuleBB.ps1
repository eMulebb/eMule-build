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

function Test-ProcessRunning {
    param([string]$ExecutablePath, [string]$CommandLineContains = '')
    try {
        foreach ($process in @(Get-CimInstance Win32_Process -ErrorAction Stop)) {
            if ([string]::IsNullOrWhiteSpace($process.ExecutablePath)) { continue }
            if (-not [string]::Equals($process.ExecutablePath, $ExecutablePath, [StringComparison]::OrdinalIgnoreCase)) { continue }
            if ([string]::IsNullOrWhiteSpace($CommandLineContains) -or ([string]$process.CommandLine).IndexOf($CommandLineContains, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                return $true
            }
        }
    } catch {
        return [bool](Get-Process | Where-Object { $_.Path -and [string]::Equals($_.Path, $ExecutablePath, [StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1)
    }
    return $false
}

$config = Read-SuiteConfig
$exeName = if ([string]::IsNullOrWhiteSpace([string]$config.emulebbExecutableName)) { 'emulebb.exe' } else { [string]$config.emulebbExecutableName }
$emule = Join-Path (Join-Path $Root 'apps\eMuleBB') $exeName
if (-not (Test-Path -LiteralPath $emule)) {
    throw "eMuleBB executable is missing: $emule"
}
$profile = Join-Path $Root 'profiles\emulebb'
if (Test-ProcessRunning -ExecutablePath $emule -CommandLineContains $profile) {
    Write-Host "eMuleBB is already running: $emule"
    return
}
Write-Host "Starting eMuleBB: $emule"
try {
    Start-Process -FilePath $emule -ArgumentList @('-c', $profile) -ErrorAction Stop | Out-Null
} catch {
    throw "eMuleBB could not be started from $emule. Check $Root\profiles\emulebb\logs and $Root\profiles\emulebb\config\preferences.ini. $($_.Exception.Message)"
}
Start-Sleep -Seconds 2
if (-not (Test-ProcessRunning -ExecutablePath $emule -CommandLineContains $profile)) {
    throw "eMuleBB did not stay running after launch from $emule. Check $Root\profiles\emulebb\logs and $Root\profiles\emulebb\config\preferences.ini."
}
