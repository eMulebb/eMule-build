#Requires -Version 5.1
[CmdletBinding()]
param(
    [string[]]$Path,
    [string]$ResultPath
)

$result = [ordered]@{
    ok = $false
    action = 'defender-exclusions'
    paths = @()
    error = $null
}

function Write-Result {
    param([int]$ExitCode)
    if ($ResultPath) {
        $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    }
    exit $ExitCode
}

try {
    Write-Host 'eMuleBB Microsoft Defender Exclusions' -ForegroundColor Cyan
    $uniquePaths = @($Path | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)
    if ($uniquePaths.Count -eq 0) {
        throw 'No folder paths were supplied.'
    }

    foreach ($folder in $uniquePaths) {
        if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
            $result.paths += [ordered]@{ path = $folder; added = $false; skipped = 'missing' }
            continue
        }

        Add-MpPreference -ExclusionPath $folder -ErrorAction Stop
        $result.paths += [ordered]@{ path = $folder; added = $true; skipped = $null }
    }

    $result.ok = $true
    Write-Host ('Microsoft Defender exclusions processed: {0}' -f $result.paths.Count) -ForegroundColor Green
    Write-Result -ExitCode 0
} catch {
    $result.error = $_.Exception.Message
    Write-Host ('Microsoft Defender exclusion update failed: {0}' -f $result.error) -ForegroundColor Red
    Write-Result -ExitCode 1
}
