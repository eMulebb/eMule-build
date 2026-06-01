"""Hyper-V based Windows guest package-smoke orchestration."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .artifact_names import utc_run_id
from .config import ReleasePackageOptions, WorkspaceOptions
from .layout import WorkspaceLayout, file_token
from .release import create_release_package

VM_LAB_SCHEMA = "emulebb.windows-vm-lab.v1"
DEFAULT_CONFIG_FILE_NAME = "vm-lab.local.json"
EXAMPLE_CONFIG_FILE_NAME = "vm-lab.example.json"
DEFAULT_SWITCH_NAME = "emulebb-vm-private"
DEFAULT_CHECKPOINT_NAME = "emulebb-clean"
DEFAULT_GUEST_USERNAME = "emulebbtest"
DEFAULT_GUEST_PASSWORD_ENV = "EMULEBB_VM_TEST_PASSWORD"
DEFAULT_MEMORY_MB = 4096
DEFAULT_DISK_GB = 64
DEFAULT_PROCESSOR_COUNT = 2
WINDOWS_VM_SUITE_NAME = "windows-vm"
WINDOWS_VM_RESULT_FILE_NAME = "windows-vm-result.json"
WINDOWS_VM_SUMMARY_FILE_NAME = "windows-vm-summary.json"
SUPPORTED_TARGETS = ("win10", "win11")


@dataclass(frozen=True)
class HyperVLabSettings:
    """Hyper-V resources used by the VM lab."""

    switch_name: str = DEFAULT_SWITCH_NAME
    checkpoint_name: str = DEFAULT_CHECKPOINT_NAME
    memory_mb: int = DEFAULT_MEMORY_MB
    disk_gb: int = DEFAULT_DISK_GB
    processor_count: int = DEFAULT_PROCESSOR_COUNT


@dataclass(frozen=True)
class GuestSettings:
    """Windows guest account settings."""

    username: str = DEFAULT_GUEST_USERNAME
    password_env: str = DEFAULT_GUEST_PASSWORD_ENV


@dataclass(frozen=True)
class VmTargetSettings:
    """One Windows VM target definition."""

    key: str
    vm_name: str
    iso_path: Path
    edition: str


@dataclass(frozen=True)
class VmLabConfig:
    """Resolved Windows VM lab configuration."""

    config_path: Path
    hyperv: HyperVLabSettings
    guest: GuestSettings
    targets: dict[str, VmTargetSettings]


@dataclass(frozen=True)
class VmPrepareOptions:
    """Options for preparing Windows Hyper-V lab images."""

    config_file: str | None = None
    matrix: tuple[str, ...] = SUPPORTED_TARGETS
    rebuild_images: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class WindowsVmTestOptions:
    """Options for running Windows VM package-smoke tests."""

    config_file: str | None = None
    matrix: tuple[str, ...] = SUPPORTED_TARGETS
    profile: str = "package-smoke"
    release_version: str = "0.7.3-rc.1"
    skip_build: bool = False
    keep_running: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class PowerShellResult:
    """Captured PowerShell command result."""

    command: list[str]
    stdout: str
    stderr: str
    returncode: int


class PowerShellRunner:
    """Runs host PowerShell snippets, with dry-run capture for tests and planning."""

    def __init__(self, *, cwd: Path, dry_run: bool = False) -> None:
        self.cwd = cwd
        self.dry_run = dry_run
        self.commands: list[str] = []

    def run(self, script: str, *, label: str, capture_json: bool = False) -> str:
        self.commands.append(script)
        if self.dry_run:
            return "null" if capture_json else ""
        executable = shutil.which("powershell.exe") or shutil.which("powershell") or "powershell.exe"
        command = [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
        completed = subprocess.run(
            command,
            cwd=str(self.cwd),
            env=_powershell_subprocess_env(executable),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            tail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"{label} failed with exit code {completed.returncode}.\n{tail}")
        return completed.stdout


def _powershell_subprocess_env(executable: str) -> dict[str, str]:
    """Builds an environment that keeps Windows PowerShell on Windows modules."""

    env = os.environ.copy()
    if Path(executable).name.lower() != "powershell.exe":
        return env
    module_path_key = next((key for key in env if key.lower() == "psmodulepath"), "PSModulePath")
    module_path = env.get(module_path_key)
    if not module_path:
        return env
    parts = [part for part in module_path.split(os.pathsep) if part]
    windows_parts = [part for part in parts if "windowspowershell" in part.lower()]
    other_parts = [part for part in parts if part not in windows_parts]
    if windows_parts:
        env[module_path_key] = os.pathsep.join(windows_parts + other_parts)
    return env


def parse_matrix(raw_matrix: str | Sequence[str] | None) -> tuple[str, ...]:
    """Parses a comma-separated Windows VM target matrix."""

    if raw_matrix is None:
        return SUPPORTED_TARGETS
    if isinstance(raw_matrix, str):
        parts = [part.strip() for part in raw_matrix.split(",")]
    else:
        parts = []
        for item in raw_matrix:
            parts.extend(part.strip() for part in str(item).split(","))
    matrix = tuple(part for part in parts if part)
    if not matrix:
        raise RuntimeError("Windows VM matrix must contain at least one target.")
    unknown = sorted(set(matrix) - set(SUPPORTED_TARGETS))
    if unknown:
        raise RuntimeError(f"Unsupported Windows VM matrix target(s): {', '.join(unknown)}.")
    return matrix


def load_vm_lab_config(layout: WorkspaceLayout, config_file: str | None = None) -> VmLabConfig:
    """Loads and validates the ignored local VM lab configuration."""

    config_path = _resolve_config_path(layout, config_file)
    payload = _load_json_object(config_path, "Windows VM lab config")
    if payload.get("schema") != VM_LAB_SCHEMA:
        raise RuntimeError(f"Windows VM lab config schema must be {VM_LAB_SCHEMA!r}: {config_path}")

    raw_hyperv = _optional_object(payload, "hyperv")
    raw_guest = _optional_object(payload, "guest")
    raw_targets = _required_object(payload, "targets")
    hyperv = HyperVLabSettings(
        switch_name=_optional_string(raw_hyperv, "switch_name", DEFAULT_SWITCH_NAME),
        checkpoint_name=_optional_string(raw_hyperv, "checkpoint_name", DEFAULT_CHECKPOINT_NAME),
        memory_mb=_optional_positive_int(raw_hyperv, "memory_mb", DEFAULT_MEMORY_MB),
        disk_gb=_optional_positive_int(raw_hyperv, "disk_gb", DEFAULT_DISK_GB),
        processor_count=_optional_positive_int(raw_hyperv, "processor_count", DEFAULT_PROCESSOR_COUNT),
    )
    guest = GuestSettings(
        username=_optional_string(raw_guest, "username", DEFAULT_GUEST_USERNAME),
        password_env=_optional_string(raw_guest, "password_env", DEFAULT_GUEST_PASSWORD_ENV),
    )
    targets = {
        key: _parse_target(config_path, key, raw_targets.get(key))
        for key in SUPPORTED_TARGETS
        if key in raw_targets
    }
    missing = [key for key in SUPPORTED_TARGETS if key not in targets]
    if missing:
        raise RuntimeError(f"Windows VM lab config is missing target(s): {', '.join(missing)}.")
    return VmLabConfig(config_path=config_path, hyperv=hyperv, guest=guest, targets=targets)


def prepare_vm_lab(layout: WorkspaceLayout, options: VmPrepareOptions) -> dict[str, object]:
    """Prepares Hyper-V Windows guest images and clean checkpoints."""

    config = load_vm_lab_config(layout, options.config_file)
    matrix = parse_matrix(options.matrix)
    runner = PowerShellRunner(cwd=layout.emule_workspace_root, dry_run=options.dry_run)
    preflight_hyperv(config, runner=runner, require_password=not options.dry_run)
    image_root = _vm_image_root(layout)
    image_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for key in matrix:
        target = config.targets[key]
        rows.append(
            prepare_vm_target(
                layout,
                config,
                target,
                runner=runner,
                rebuild_images=options.rebuild_images,
            )
        )
    result = {
        "schema": "emulebb.windows-vm-prepare-result.v1",
        "status": "planned" if options.dry_run else "passed",
        "generatedAtUtc": _now_utc(),
        "configFile": str(config.config_path),
        "matrix": list(matrix),
        "dryRun": options.dry_run,
        "targets": rows,
        "commandCount": len(runner.commands),
    }
    print(json.dumps(result, indent=2))
    return result


def invoke_windows_vm_tests(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    options: WindowsVmTestOptions,
) -> dict[str, object]:
    """Runs package-smoke tests inside clean Windows Hyper-V guests."""

    if workspace_options.platform != "x64":
        raise RuntimeError("test windows-vm supports x64 packages only in v1.")
    if workspace_options.configuration != "Release":
        raise RuntimeError("test windows-vm requires --config Release.")
    if options.profile != "package-smoke":
        raise RuntimeError(f"Unsupported Windows VM test profile: {options.profile!r}.")
    config = load_vm_lab_config(layout, options.config_file)
    matrix = parse_matrix(options.matrix)
    runner = PowerShellRunner(cwd=layout.emule_workspace_root, dry_run=options.dry_run)
    preflight_hyperv(config, runner=runner, require_password=not options.dry_run)
    if not options.skip_build and not options.dry_run:
        create_release_package(
            layout,
            workspace_options,
            ReleasePackageOptions(release_version=options.release_version, clean=False, require_signing=False),
        )
    package_zip = _release_package_zip(layout, options.release_version, workspace_options.platform)
    if not options.dry_run and not package_zip.is_file():
        raise RuntimeError(f"Windows VM package-smoke is missing release package: {package_zip}")

    run_id = utc_run_id()
    report_root = _windows_vm_report_root(layout)
    run_report_dir = report_root / run_id
    run_report_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for key in matrix:
        rows.append(
            run_windows_vm_package_smoke(
                layout,
                config,
                config.targets[key],
                package_zip=package_zip,
                run_id=run_id,
                run_report_dir=run_report_dir,
                keep_running=options.keep_running,
                runner=runner,
            )
        )
    status = "passed" if all(row.get("status") == "passed" for row in rows) else "failed"
    if options.dry_run:
        status = "planned"
    result = {
        "schema": "emulebb.windows-vm-result.v1",
        "status": status,
        "generatedAtUtc": _now_utc(),
        "profile": options.profile,
        "releaseVersion": options.release_version,
        "platform": workspace_options.platform,
        "configFile": str(config.config_path),
        "packageZip": str(package_zip),
        "packageSha256": _sha256(package_zip) if package_zip.is_file() else None,
        "matrix": list(matrix),
        "dryRun": options.dry_run,
        "targets": rows,
        "commandCount": len(runner.commands),
    }
    summary = {
        "schema": "emulebb.windows-vm-summary.v1",
        "status": status,
        "generatedAtUtc": result["generatedAtUtc"],
        "profile": options.profile,
        "matrix": list(matrix),
        "passed": [row["target"] for row in rows if row.get("status") == "passed"],
        "failed": [row["target"] for row in rows if row.get("status") not in {"passed", "planned"}],
        "planned": [row["target"] for row in rows if row.get("status") == "planned"],
    }
    _write_json(run_report_dir / WINDOWS_VM_RESULT_FILE_NAME, result)
    _write_json(run_report_dir / WINDOWS_VM_SUMMARY_FILE_NAME, summary)
    _refresh_latest(run_report_dir, report_root / "latest")
    print(json.dumps(summary, indent=2))
    if status == "failed":
        raise RuntimeError(f"Windows VM package-smoke failed. See {run_report_dir}.")
    return result


def preflight_hyperv(config: VmLabConfig, *, runner: PowerShellRunner, require_password: bool) -> None:
    """Verifies host prerequisites for Hyper-V VM automation."""

    if require_password and not os.environ.get(config.guest.password_env):
        raise RuntimeError(f"Guest password environment variable is required: {config.guest.password_env}")
    script = _ps_with_payload(
        {
            "cmdlets": [
                "Get-VM",
                "New-VM",
                "Start-VM",
                "Stop-VM",
                "Checkpoint-VM",
                "Get-VMSnapshot",
                "Restore-VMSnapshot",
                "New-VMSwitch",
                "Get-VMSwitch",
                "New-VHD",
                "Mount-VHD",
                "Dismount-VHD",
                "Mount-DiskImage",
                "Dismount-DiskImage",
                "Get-WindowsImage",
                "Invoke-Command",
                "New-PSSession",
                "Copy-Item",
            ]
        },
        r"""
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Windows VM lab requires an elevated PowerShell host.'
}
$missing = @()
foreach ($name in $payload.cmdlets) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    $missing += $name
  }
}
if ($missing.Count -gt 0) {
  throw ('Missing Hyper-V/Windows imaging command(s): ' + ($missing -join ', '))
}
$service = Get-Service vmms -ErrorAction Stop
if ($service.Status -ne 'Running') {
  throw ('Hyper-V Virtual Machine Management service is not running: ' + $service.Status)
}
""",
    )
    runner.run(script, label="Windows VM Hyper-V preflight")


def prepare_vm_target(
    layout: WorkspaceLayout,
    config: VmLabConfig,
    target: VmTargetSettings,
    *,
    runner: PowerShellRunner,
    rebuild_images: bool,
) -> dict[str, object]:
    """Prepares one Hyper-V VM and its clean checkpoint."""

    vhd_path = _vm_image_root(layout) / f"{file_token(target.key)}.vhdx"
    script = _ps_with_payload(
        {
            "target": target.key,
            "vmName": target.vm_name,
            "isoPath": str(target.iso_path),
            "edition": target.edition,
            "vhdPath": str(vhd_path),
            "switchName": config.hyperv.switch_name,
            "checkpointName": config.hyperv.checkpoint_name,
            "memoryBytes": config.hyperv.memory_mb * 1024 * 1024,
            "diskBytes": config.hyperv.disk_gb * 1024 * 1024 * 1024,
            "processorCount": config.hyperv.processor_count,
            "username": config.guest.username,
            "password": os.environ.get(config.guest.password_env, ""),
            "rebuildImages": rebuild_images,
        },
        _prepare_vm_target_script(),
    )
    runner.run(script, label=f"prepare Windows VM {target.key}")
    return {
        "target": target.key,
        "vmName": target.vm_name,
        "status": "planned" if runner.dry_run else "passed",
        "vhdPath": str(vhd_path),
        "isoPath": str(target.iso_path),
        "edition": target.edition,
        "checkpointName": config.hyperv.checkpoint_name,
    }


def run_windows_vm_package_smoke(
    layout: WorkspaceLayout,
    config: VmLabConfig,
    target: VmTargetSettings,
    *,
    package_zip: Path,
    run_id: str,
    run_report_dir: Path,
    keep_running: bool,
    runner: PowerShellRunner,
) -> dict[str, object]:
    """Runs the package-smoke profile inside one restored Windows guest."""

    target_report_dir = run_report_dir / target.key
    target_report_dir.mkdir(parents=True, exist_ok=True)
    if runner.dry_run:
        return {
            "target": target.key,
            "vmName": target.vm_name,
            "status": "planned",
            "checkpointName": config.hyperv.checkpoint_name,
            "reportDir": str(target_report_dir),
        }
    script = _ps_with_payload(
        {
            "target": target.key,
            "vmName": target.vm_name,
            "checkpointName": config.hyperv.checkpoint_name,
            "username": config.guest.username,
            "password": os.environ.get(config.guest.password_env, ""),
            "packageZip": str(package_zip),
            "runId": run_id,
            "hostReportDir": str(target_report_dir),
            "keepRunning": keep_running,
        },
        _load_guest_package_smoke_script(layout),
    )
    stdout = runner.run(script, label=f"Windows VM package-smoke {target.key}", capture_json=True)
    payload = _parse_json_output(stdout, f"Windows VM package-smoke {target.key}")
    _write_json(target_report_dir / f"{target.key}-result.json", payload)
    return {
        "target": target.key,
        "vmName": target.vm_name,
        "status": payload.get("status", "failed"),
        "checkpointName": config.hyperv.checkpoint_name,
        "reportDir": str(target_report_dir),
        "guest": payload.get("guest", {}),
        "checks": payload.get("checks", []),
        "errors": payload.get("errors", []),
    }


def _prepare_vm_target_script() -> str:
    return r"""
$ErrorActionPreference = 'Stop'
$secure = ConvertTo-SecureString $payload.password -AsPlainText -Force
$credential = [pscredential]::new($payload.username, $secure)
$vm = Get-VM -Name $payload.vmName -ErrorAction SilentlyContinue
if ($vm -and -not $payload.rebuildImages) {
  $snapshot = Get-VMSnapshot -VMName $payload.vmName -Name $payload.checkpointName -ErrorAction SilentlyContinue
  if ($snapshot) {
    Write-Output ('VM already prepared: ' + $payload.vmName)
    return
  }
}
if ($vm) {
  Stop-VM -Name $payload.vmName -TurnOff -Force -ErrorAction SilentlyContinue
  Remove-VM -Name $payload.vmName -Force
}
if (Test-Path -LiteralPath $payload.vhdPath) {
  Remove-Item -LiteralPath $payload.vhdPath -Force
}
if (-not (Test-Path -LiteralPath $payload.isoPath)) {
  throw ('Windows ISO is missing: ' + $payload.isoPath)
}
if (-not (Get-VMSwitch -Name $payload.switchName -ErrorAction SilentlyContinue)) {
  New-VMSwitch -Name $payload.switchName -SwitchType Private | Out-Null
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $payload.vhdPath) | Out-Null
New-VHD -Path $payload.vhdPath -SizeBytes ([int64] $payload.diskBytes) -Dynamic | Out-Null
$mountedVhd = Mount-VHD -Path $payload.vhdPath -Passthru
$disk = $mountedVhd | Get-Disk
try {
  Initialize-Disk -Number $disk.Number -PartitionStyle GPT
  $efi = New-Partition -DiskNumber $disk.Number -Size 260MB -GptType '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}'
  $windows = New-Partition -DiskNumber $disk.Number -UseMaximumSize
  Format-Volume -Partition $efi -FileSystem FAT32 -NewFileSystemLabel System -Confirm:$false | Out-Null
  Format-Volume -Partition $windows -FileSystem NTFS -NewFileSystemLabel Windows -Confirm:$false | Out-Null
  Add-PartitionAccessPath -DiskNumber $disk.Number -PartitionNumber $efi.PartitionNumber -AssignDriveLetter
  Add-PartitionAccessPath -DiskNumber $disk.Number -PartitionNumber $windows.PartitionNumber -AssignDriveLetter
  $efiVolume = Get-Partition -DiskNumber $disk.Number -PartitionNumber $efi.PartitionNumber | Get-Volume
  $windowsVolume = Get-Partition -DiskNumber $disk.Number -PartitionNumber $windows.PartitionNumber | Get-Volume
  if (-not $efiVolume.DriveLetter) {
    throw 'EFI partition did not receive a drive letter.'
  }
  if (-not $windowsVolume.DriveLetter) {
    throw 'Windows partition did not receive a drive letter.'
  }
  $efiRoot = "$($efiVolume.DriveLetter):"
  $windowsRoot = "$($windowsVolume.DriveLetter):"
  Mount-DiskImage -ImagePath $payload.isoPath | Out-Null
  $iso = Get-DiskImage -ImagePath $payload.isoPath | Get-Volume
  $isoRoot = "$($iso.DriveLetter):"
  $installImage = Join-Path $isoRoot 'sources\install.wim'
  if (-not (Test-Path -LiteralPath $installImage)) {
    $installImage = Join-Path $isoRoot 'sources\install.esd'
  }
  if (-not (Test-Path -LiteralPath $installImage)) {
    throw 'Windows ISO does not contain sources\install.wim or sources\install.esd.'
  }
  $image = Get-WindowsImage -ImagePath $installImage | Where-Object { $_.ImageName -eq $payload.edition } | Select-Object -First 1
  if (-not $image) {
    throw ('Windows edition not found in ISO: ' + $payload.edition)
  }
  dism.exe /Apply-Image /ImageFile:$installImage /Index:$($image.ImageIndex) /ApplyDir:$windowsRoot\ | Out-Host
  if ($LASTEXITCODE -ne 0) {
    throw ('DISM Apply-Image failed with exit code ' + $LASTEXITCODE)
  }
  $unattendDir = Join-Path $windowsRoot 'Windows\Panther\Unattend'
  New-Item -ItemType Directory -Force -Path $unattendDir | Out-Null
  $escapedPassword = [Security.SecurityElement]::Escape($payload.password)
  $escapedUser = [Security.SecurityElement]::Escape($payload.username)
$unattend = @"
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
  <settings pass="specialize">
    <component name="Microsoft-Windows-International-Core" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <InputLocale>en-US</InputLocale>
      <SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage>
      <UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <ComputerName>*</ComputerName>
      <RegisteredOwner>eMuleBB</RegisteredOwner>
      <TimeZone>UTC</TimeZone>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-International-Core" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <InputLocale>en-US</InputLocale>
      <SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage>
      <UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideLocalAccountScreen>true</HideLocalAccountScreen>
        <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <SkipMachineOOBE>true</SkipMachineOOBE>
        <SkipUserOOBE>true</SkipUserOOBE>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>
      <UserAccounts>
        <LocalAccounts>
          <LocalAccount wcm:action="add">
            <Name>$escapedUser</Name>
            <Group>Administrators</Group>
            <Password><Value>$escapedPassword</Value><PlainText>true</PlainText></Password>
          </LocalAccount>
        </LocalAccounts>
      </UserAccounts>
      <AutoLogon>
        <Enabled>true</Enabled>
        <LogonCount>999</LogonCount>
        <Username>$escapedUser</Username>
        <Password><Value>$escapedPassword</Value><PlainText>true</PlainText></Password>
      </AutoLogon>
    </component>
  </settings>
</unattend>
"@
  Set-Content -Path (Join-Path $unattendDir 'Unattend.xml') -Value $unattend -Encoding UTF8
  New-Item -ItemType Directory -Force -Path "$efiRoot\EFI\Microsoft\Boot" | Out-Null
  New-Item -ItemType Directory -Force -Path "$efiRoot\EFI\Microsoft\Recovery" | Out-Null
  bcdboot.exe "$windowsRoot\Windows" /s $efiRoot /f UEFI | Out-Host
  if ($LASTEXITCODE -ne 0) {
    throw ('BCDBoot failed with exit code ' + $LASTEXITCODE)
  }
  $sourceBootMgr = Join-Path $windowsRoot 'Windows\Boot\EFI\bootmgfw.efi'
  $microsoftBootMgr = Join-Path $efiRoot 'EFI\Microsoft\Boot\bootmgfw.efi'
  $fallbackBootMgr = Join-Path $efiRoot 'EFI\Boot\bootx64.efi'
  if (-not (Test-Path -LiteralPath $microsoftBootMgr)) {
    if (-not (Test-Path -LiteralPath $sourceBootMgr)) {
      throw ('Windows image is missing EFI boot manager: ' + $sourceBootMgr)
    }
    Copy-Item -LiteralPath $sourceBootMgr -Destination $microsoftBootMgr -Force
  }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $fallbackBootMgr) | Out-Null
  Copy-Item -LiteralPath $microsoftBootMgr -Destination $fallbackBootMgr -Force
}
finally {
  Dismount-DiskImage -ImagePath $payload.isoPath -ErrorAction SilentlyContinue
  Dismount-VHD -Path $payload.vhdPath -ErrorAction SilentlyContinue
}
New-VM -Name $payload.vmName -Generation 2 -MemoryStartupBytes ([int64] $payload.memoryBytes) -VHDPath $payload.vhdPath -SwitchName $payload.switchName | Out-Null
Set-VMProcessor -VMName $payload.vmName -Count ([int] $payload.processorCount)
Set-VMFirmware -VMName $payload.vmName -EnableSecureBoot On -SecureBootTemplate 'MicrosoftWindows'
Start-VM -Name $payload.vmName
$deadline = (Get-Date).AddMinutes(30)
do {
  Start-Sleep -Seconds 10
  try {
    $ready = Invoke-Command -VMName $payload.vmName -Credential $credential -ScriptBlock { 'ready' } -ErrorAction Stop
    if ($ready -eq 'ready') { break }
  } catch {
    if ((Get-Date) -gt $deadline) { throw }
  }
} while ((Get-Date) -lt $deadline)
Invoke-Command -VMName $payload.vmName -Credential $credential -ScriptBlock {
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine -Force
  New-Item -ItemType Directory -Force -Path C:\eMuleBBVmTest | Out-Null
} | Out-Null
Stop-VM -Name $payload.vmName -Force
Checkpoint-VM -Name $payload.vmName -SnapshotName $payload.checkpointName
"""


def _load_guest_package_smoke_script(layout: WorkspaceLayout) -> str:
    """Loads the guest package-smoke script template owned by emulebb-build-tests."""

    module_path = layout.tests_repo_root / "emule_test_harness" / "windows_vm_guest.py"
    if not module_path.is_file():
        raise RuntimeError(f"Windows VM guest harness module is missing: {module_path}")
    spec = importlib.util.spec_from_file_location("emulebb_windows_vm_guest", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Windows VM guest harness module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    script_factory = getattr(module, "package_smoke_script", None)
    if not callable(script_factory):
        raise RuntimeError(f"Windows VM guest harness module is missing package_smoke_script(): {module_path}")
    script = script_factory()
    if not isinstance(script, str) or not script.strip():
        raise RuntimeError(f"Windows VM guest harness package_smoke_script() returned an empty script: {module_path}")
    return script


def _release_package_zip(layout: WorkspaceLayout, release_version: str, platform: str) -> Path:
    arch = "arm64" if platform == "ARM64" else "x64"
    return layout.workspace_root / "state" / "release" / f"emulebb-v{release_version}" / f"emulebb-{release_version}-{arch}.zip"


def _vm_image_root(layout: WorkspaceLayout) -> Path:
    return layout.workspace_root / "state" / "vm-lab" / "images"


def _windows_vm_report_root(layout: WorkspaceLayout) -> Path:
    return layout.workspace_root / "state" / "test-reports" / WINDOWS_VM_SUITE_NAME


def _resolve_config_path(layout: WorkspaceLayout, config_file: str | None) -> Path:
    raw = config_file or DEFAULT_CONFIG_FILE_NAME
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.resolve()
    workspace_relative = (layout.emule_workspace_root / candidate).resolve()
    if workspace_relative.exists():
        return workspace_relative
    return (layout.build_repo_root / candidate).resolve()


def _parse_target(config_path: Path, key: str, raw: object) -> VmTargetSettings:
    if not isinstance(raw, dict):
        raise RuntimeError(f"Windows VM lab config target {key!r} must be an object: {config_path}")
    return VmTargetSettings(
        key=key,
        vm_name=_required_string(raw, "vm_name"),
        iso_path=Path(_required_string(raw, "iso_path")).expanduser().resolve(),
        edition=_required_string(raw, "edition"),
    )


def _ps_with_payload(payload: dict[str, object], body: str) -> str:
    payload_json = json.dumps(payload)
    return "$payload = @'\n" + payload_json + "\n'@ | ConvertFrom-Json\n" + body


def _parse_json_output(stdout: str, label: str) -> dict[str, object]:
    text = stdout.strip()
    if not text:
        raise RuntimeError(f"{label} did not return JSON output.")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"{label} did not return a JSON object:\n{text}")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned non-object JSON.")
    return payload


def _refresh_latest(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _load_json_object(path: Path, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(
            f"{description} is missing: {path}. "
            f"Copy {EXAMPLE_CONFIG_FILE_NAME} to {DEFAULT_CONFIG_FILE_NAME} and update local ISO paths."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{description} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{description} must contain one JSON object: {path}")
    return payload


def _required_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Windows VM lab config field {key!r} must be an object.")
    return value


def _optional_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise RuntimeError(f"Windows VM lab config field {key!r} must be an object.")
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Windows VM lab config field {key!r} must be a non-empty string.")
    return value.strip()


def _optional_string(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Windows VM lab config field {key!r} must be a non-empty string.")
    return value.strip()


def _optional_positive_int(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"Windows VM lab config field {key!r} must be a positive integer.")
    return value


def _sha256(path: Path) -> str:
    hasher = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
