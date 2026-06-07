#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "Suite root: $Root"
Write-Host 'Config:' (Join-Path $Root 'manifests\suite-config.json')
Write-Host 'Manual reconfiguration: edit manifests\suite-config.json, profiles\emulebb\config\preferences.ini, and selected Arr config.xml files consistently.'
& (Join-Path $Root 'scripts\Get-SuiteStatus.ps1')
