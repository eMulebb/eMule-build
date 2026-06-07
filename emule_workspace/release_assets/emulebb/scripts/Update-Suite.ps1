#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
& (Join-Path $Root 'scripts\Stop-Suite.ps1')
& (Join-Path $Root 'scripts\Install-eMuleBBSuite.ps1') -ConfigFile (Join-Path $Root 'manifests\suite-config.json') -NonInteractive -Force
