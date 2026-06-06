#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ResultPath
)

$result = [ordered]@{
    ok = $false
    action = 'enable-long-paths'
    changed = $false
    error = $null
}

function Write-Result {
    param([int]$ExitCode)
    if ($ResultPath) {
        $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    }
    exit $ExitCode
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Windows long-path enable requires an elevated PowerShell window. Right-click Windows PowerShell and choose Run as administrator, then rerun this script.'
    }
}

try {
    Write-Host 'eMuleBB Windows Long Paths' -ForegroundColor Cyan
    Assert-Administrator
    $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem'
    $current = Get-ItemProperty -LiteralPath $key -Name LongPathsEnabled -ErrorAction SilentlyContinue
    $oldValue = if ($null -ne $current) { [int]$current.LongPathsEnabled } else { 0 }
    Set-ItemProperty -LiteralPath $key -Name LongPathsEnabled -Type DWord -Value 1 -ErrorAction Stop
    $result.changed = ($oldValue -ne 1)
    $result.ok = $true
    Write-Host 'Windows long paths are enabled.' -ForegroundColor Green
    Write-Result -ExitCode 0
} catch {
    $result.error = $_.Exception.Message
    Write-Host ('Windows long-path enable failed: {0}' -f $result.error) -ForegroundColor Red
    Write-Result -ExitCode 1
}
