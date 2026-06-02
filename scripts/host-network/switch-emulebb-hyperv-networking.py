"""Switches the local Hyper-V lab host between VM and LAN networking modes."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


SCRIPT_NAME = "Switch-EmuleBBHyperVNetworking.ps1"
DEFAULT_CONFIG_NAME = "Switch-EmuleBBHyperVNetworking.local.json"

POWERSHELL_PAYLOAD = r"""
#Requires -Version 5.1
#Requires -RunAsAdministrator

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Status', 'HyperV', 'LAN')]
    [string] $Mode,

    [Parameter(Mandatory = $true)]
    [string] $ConfigPath
)

$ErrorActionPreference = 'Stop'

function Write-Step([string] $Message) {
    Write-Host "==> $Message"
}

function Read-HostNetworkConfig([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        $example = Join-Path (Split-Path -Parent $Path) 'Switch-EmuleBBHyperVNetworking.local.example.json'
        throw "Missing config '$Path'. Copy '$example' to '$Path' and adjust the host-specific values."
    }

    $config = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $required = @(
        'physicalAdapter',
        'externalSwitchName',
        'parkingSwitchName',
        'vmNames',
        'hostIPv4',
        'prefixLength',
        'gateway',
        'dnsServers'
    )
    foreach ($name in $required) {
        if (-not $config.PSObject.Properties.Name.Contains($name) -or $null -eq $config.$name -or $config.$name -eq '') {
            throw "Config '$Path' is missing required value '$name'."
        }
    }
    return $config
}

$Config = Read-HostNetworkConfig $ConfigPath
$PhysicalAdapter = [string] $Config.physicalAdapter
$ExternalSwitchName = [string] $Config.externalSwitchName
$ParkingSwitchName = [string] $Config.parkingSwitchName
$VmNames = @($Config.vmNames | ForEach-Object { [string] $_ })
$HostIPv4 = [string] $Config.hostIPv4
$PrefixLength = [int] $Config.prefixLength
$Gateway = [string] $Config.gateway
$DnsServers = @($Config.dnsServers | ForEach-Object { [string] $_ })
$DisableIPv6 = if ($null -eq $Config.disableIPv6) { $true } else { [bool] $Config.disableIPv6 }

function Wait-NetAdapterPresent([string] $Name, [int] $TimeoutSeconds = 45) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $adapter = Get-NetAdapter -Name $Name -ErrorAction SilentlyContinue
        if ($adapter) {
            return $adapter
        }
        Start-Sleep -Seconds 1
    }
    throw "Network adapter '$Name' did not appear within $TimeoutSeconds seconds."
}

function Disable-IPv6IfConfigured([string] $Name) {
    if (-not $DisableIPv6) {
        return
    }
    $binding = Get-NetAdapterBinding -Name $Name -ComponentID ms_tcpip6 -ErrorAction SilentlyContinue
    if ($binding -and $binding.Enabled) {
        Disable-NetAdapterBinding -Name $Name -ComponentID ms_tcpip6
    }
}

function Enable-IPv4IfPresent([string] $Name) {
    $binding = Get-NetAdapterBinding -Name $Name -ComponentID ms_tcpip -ErrorAction SilentlyContinue
    if ($binding -and -not $binding.Enabled) {
        Enable-NetAdapterBinding -Name $Name -ComponentID ms_tcpip
    }
}

function Clear-IPv4([string] $Name) {
    Get-NetRoute -InterfaceAlias $Name -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
    Get-NetIPAddress -InterfaceAlias $Name -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -ne '127.0.0.1' } |
        Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
}

function Set-StaticIPv4([string] $Name) {
    Wait-NetAdapterPresent $Name | Out-Null
    Enable-NetAdapter -Name $Name -Confirm:$false -ErrorAction SilentlyContinue
    Enable-IPv4IfPresent $Name
    Disable-IPv6IfConfigured $Name
    Set-NetIPInterface -InterfaceAlias $Name -AddressFamily IPv4 -Dhcp Disabled
    Clear-IPv4 $Name
    New-NetIPAddress -InterfaceAlias $Name -IPAddress $HostIPv4 -PrefixLength $PrefixLength -DefaultGateway $Gateway | Out-Null
    Set-DnsClientServerAddress -InterfaceAlias $Name -ServerAddresses $DnsServers
    Set-NetIPInterface -InterfaceAlias $Name -AddressFamily IPv4 -InterfaceMetric 25
}

function Ensure-ParkingSwitch {
    $switch = Get-VMSwitch -Name $ParkingSwitchName -ErrorAction SilentlyContinue
    if (-not $switch) {
        New-VMSwitch -Name $ParkingSwitchName -SwitchType Private | Out-Null
        return
    }
    if ($switch.SwitchType -ne 'Private') {
        throw "Parking switch '$ParkingSwitchName' exists but is $($switch.SwitchType), not Private."
    }
}

function Connect-VMsToSwitch([string] $SwitchName) {
    foreach ($vm in $VmNames) {
        if (Get-VM -Name $vm -ErrorAction SilentlyContinue) {
            Connect-VMNetworkAdapter -VMName $vm -SwitchName $SwitchName
        }
    }
}

function Test-LAN {
    $gatewayOk = $false
    $internetOk = $false
    $dnsOk = $false
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        $gatewayOk = Test-NetConnection $Gateway -InformationLevel Quiet
        $internetOk = Test-NetConnection 1.1.1.1 -Port 53 -InformationLevel Quiet
        $dnsOk = [bool](Resolve-DnsName example.com -ErrorAction SilentlyContinue)
        if ($gatewayOk -and $internetOk -and $dnsOk) {
            break
        }
        Start-Sleep -Seconds 3
    }
    [pscustomobject]@{
        Gateway = $gatewayOk
        InternetIP = $internetOk
        DNS = $dnsOk
    }
}

function Show-Status {
    Write-Host ''
    Write-Host 'Config:'
    [pscustomobject]@{
        ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
        PhysicalAdapter = $PhysicalAdapter
        ExternalSwitchName = $ExternalSwitchName
        ParkingSwitchName = $ParkingSwitchName
        HostIPv4 = $HostIPv4
        PrefixLength = $PrefixLength
        Gateway = $Gateway
        DnsServers = $DnsServers -join ','
        DisableIPv6 = $DisableIPv6
    } | Format-List

    Write-Host ''
    Write-Host 'Switches:'
    Get-VMSwitch | Sort-Object Name |
        Select-Object Name, SwitchType, NetAdapterInterfaceDescription, AllowManagementOS |
        Format-Table -AutoSize

    Write-Host ''
    Write-Host 'Host adapters:'
    Get-NetAdapter | Where-Object { $_.Name -eq $PhysicalAdapter -or $_.Name -like 'vEthernet*' } |
        Sort-Object Name |
        Select-Object Name, InterfaceDescription, Status, MacAddress |
        Format-Table -AutoSize

    Write-Host ''
    Write-Host 'Host IPv4:'
    Get-NetIPConfiguration | Where-Object { $_.InterfaceAlias -eq $PhysicalAdapter -or $_.InterfaceAlias -like 'vEthernet*' } |
        Select-Object InterfaceAlias, IPv4Address, IPv4DefaultGateway, DNSServer |
        Format-List

    Write-Host ''
    Write-Host 'VM NICs:'
    foreach ($vm in $VmNames) {
        Get-VMNetworkAdapter -VMName $vm -ErrorAction SilentlyContinue |
            Select-Object VMName, Name, SwitchName, MacAddress |
            Format-Table -AutoSize
    }
}

function Set-LANMode {
    Write-Step "Parking VMs on private switch '$ParkingSwitchName'"
    Ensure-ParkingSwitch
    Connect-VMsToSwitch $ParkingSwitchName

    $external = Get-VMSwitch -Name $ExternalSwitchName -ErrorAction SilentlyContinue
    if ($external) {
        Write-Step "Removing Hyper-V external switch '$ExternalSwitchName'"
        Remove-VMSwitch -Name $ExternalSwitchName -Force
        Start-Sleep -Seconds 4
    }

    Write-Step "Restoring host LAN directly on '$PhysicalAdapter'"
    Set-StaticIPv4 $PhysicalAdapter

    Write-Step 'Verifying LAN'
    Test-LAN | Format-List
}

function Set-HyperVMode {
    $mgmtAdapter = "vEthernet ($ExternalSwitchName)"
    $physical = Get-NetAdapter -Name $PhysicalAdapter -ErrorAction Stop
    $physicalDescription = $physical.InterfaceDescription
    try {
        $existing = Get-VMSwitch -Name $ExternalSwitchName -ErrorAction SilentlyContinue
        if ($existing -and ($existing.SwitchType -ne 'External' -or $existing.NetAdapterInterfaceDescription -ne $physicalDescription)) {
            Write-Step "Removing stale switch '$ExternalSwitchName'"
            Ensure-ParkingSwitch
            Connect-VMsToSwitch $ParkingSwitchName
            Remove-VMSwitch -Name $ExternalSwitchName -Force
            $existing = $null
        }

        if (-not $existing) {
            Write-Step "Creating external switch '$ExternalSwitchName' on '$PhysicalAdapter'"
            New-VMSwitch -Name $ExternalSwitchName -NetAdapterName $PhysicalAdapter -AllowManagementOS $true | Out-Null
            Start-Sleep -Seconds 5
        }

        Write-Step "Moving host LAN identity to '$mgmtAdapter'"
        Wait-NetAdapterPresent $mgmtAdapter | Out-Null
        Enable-NetAdapter -Name $mgmtAdapter -Confirm:$false -ErrorAction SilentlyContinue
        Clear-IPv4 $PhysicalAdapter
        Disable-IPv6IfConfigured $PhysicalAdapter
        Set-StaticIPv4 $mgmtAdapter

        Write-Step "Connecting VMs to '$ExternalSwitchName'"
        Connect-VMsToSwitch $ExternalSwitchName

        Write-Step 'Verifying LAN'
        Test-LAN | Format-List
    } catch {
        Write-Warning "Hyper-V mode failed: $($_.Exception.Message)"
        Write-Warning "Attempting LAN rollback on '$PhysicalAdapter'."
        try {
            Set-StaticIPv4 $PhysicalAdapter
        } catch {
            Write-Warning "Rollback also failed: $($_.Exception.Message)"
        }
        throw
    }
}

switch ($Mode) {
    'Status' {
        Show-Status
    }
    'LAN' {
        Set-LANMode
        Show-Status
    }
    'HyperV' {
        Ensure-ParkingSwitch
        Set-HyperVMode
        Show-Status
    }
}
""".lstrip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("Status", "HyperV", "LAN"))
    parser.add_argument(
        "--config-path",
        default=str(Path(__file__).with_name(DEFAULT_CONFIG_NAME)),
        help="Host-specific network switcher JSON config.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config_path).resolve()

    with tempfile.TemporaryDirectory(prefix="emulebb-hyperv-network-") as temp_root:
        script_path = Path(temp_root) / SCRIPT_NAME
        script_path.write_text(POWERSHELL_PAYLOAD, encoding="utf-8-sig")
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-Mode",
                args.mode,
                "-ConfigPath",
                str(config_path),
            ],
            check=False,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
