#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProgramPath,

    [string]$ResultPath
)

$result = [ordered]@{
    ok = $false
    action = 'repair-firewall'
    programPath = $ProgramPath
    rules = @()
    error = $null
}

function Write-Result {
    param([int]$ExitCode)
    if ($ResultPath) {
        $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    }
    exit $ExitCode
}

function Repair-Rule {
    param(
        [string]$Name,
        [ValidateSet('Inbound', 'Outbound')]
        [string]$Direction,
        [ValidateSet('TCP', 'UDP')]
        [string]$Protocol
    )

    $existing = @(Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        $existing | Remove-NetFirewallRule -ErrorAction Stop
    }

    New-NetFirewallRule -DisplayName $Name -Direction $Direction -Action Allow -Enabled True -Profile Domain,Private,Public -Program $ProgramPath -Protocol $Protocol -ErrorAction Stop | Out-Null
    return [ordered]@{
        name = $Name
        direction = $Direction
        protocol = $Protocol
        replaced = ($existing.Count -gt 0)
    }
}

try {
    Write-Host 'eMuleBB Windows Firewall Repair' -ForegroundColor Cyan
    if (-not (Test-Path -LiteralPath $ProgramPath -PathType Leaf)) {
        throw "Program path does not exist: $ProgramPath"
    }

    $specs = @(
        @{ Name = 'eMuleBB Inbound TCP'; Direction = 'Inbound'; Protocol = 'TCP' },
        @{ Name = 'eMuleBB Inbound UDP'; Direction = 'Inbound'; Protocol = 'UDP' },
        @{ Name = 'eMuleBB Outbound TCP'; Direction = 'Outbound'; Protocol = 'TCP' },
        @{ Name = 'eMuleBB Outbound UDP'; Direction = 'Outbound'; Protocol = 'UDP' }
    )

    foreach ($spec in $specs) {
        $result.rules += Repair-Rule -Name $spec.Name -Direction $spec.Direction -Protocol $spec.Protocol
    }

    $result.ok = $true
    Write-Host 'Windows Firewall rules repaired.' -ForegroundColor Green
    Write-Result -ExitCode 0
} catch {
    $result.error = $_.Exception.Message
    Write-Host ('Windows Firewall repair failed: {0}' -f $result.error) -ForegroundColor Red
    Write-Result -ExitCode 1
}
