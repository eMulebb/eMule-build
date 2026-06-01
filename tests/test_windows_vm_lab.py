from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from emule_workspace.config import WorkspaceOptions
from emule_workspace import windows_vm_lab


def _layout(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        emule_workspace_root=tmp_path,
        workspace_root=tmp_path / "workspaces" / "workspace",
        build_repo_root=tmp_path / "repos" / "emulebb-build",
        tests_repo_root=tmp_path / "repos" / "emulebb-build-tests",
    )


def _workspace_options(tmp_path: Path) -> WorkspaceOptions:
    return WorkspaceOptions(
        workspace_root=tmp_path,
        workspace_name="workspace",
        configuration="Release",
        platform="x64",
        build_output_mode="ErrorsOnly",
    )


def _write_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": windows_vm_lab.VM_LAB_SCHEMA,
                "hyperv": {
                    "switch_name": "emulebb-test-switch",
                    "checkpoint_name": "emulebb-clean",
                    "memory_mb": 2048,
                    "disk_gb": 40,
                    "processor_count": 2,
                },
                "guest": {
                    "username": "emulebbtest",
                    "password_env": "EMULEBB_TEST_VM_PASSWORD",
                },
                "targets": {
                    "win10": {
                        "vm_name": "emulebb-win10-test",
                        "iso_path": str(path.parent / "win10.iso"),
                        "edition": "Windows 10 Pro",
                    },
                    "win11": {
                        "vm_name": "emulebb-win11-test",
                        "iso_path": str(path.parent / "win11.iso"),
                        "edition": "Windows 11 Pro",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_parse_matrix_rejects_unknown_target() -> None:
    with pytest.raises(RuntimeError, match="Unsupported Windows VM matrix"):
        windows_vm_lab.parse_matrix("win10,win12")


def test_load_vm_lab_config_resolves_targets(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)

    config = windows_vm_lab.load_vm_lab_config(layout)

    assert config.config_path == config_path.resolve()
    assert config.hyperv.switch_name == "emulebb-test-switch"
    assert config.hyperv.memory_mb == 2048
    assert config.guest.password_env == "EMULEBB_TEST_VM_PASSWORD"
    assert config.targets["win10"].vm_name == "emulebb-win10-test"
    assert config.targets["win11"].edition == "Windows 11 Pro"


def test_preflight_requires_guest_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = _layout(tmp_path)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)
    config = windows_vm_lab.load_vm_lab_config(layout)
    monkeypatch.delenv("EMULEBB_TEST_VM_PASSWORD", raising=False)
    runner = windows_vm_lab.PowerShellRunner(cwd=tmp_path, dry_run=True)

    with pytest.raises(RuntimeError, match="EMULEBB_TEST_VM_PASSWORD"):
        windows_vm_lab.preflight_hyperv(config, runner=runner, require_password=True)


def test_powershell_subprocess_env_prefers_windows_powershell_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    module_path = os.pathsep.join(
        [
            r"C:\Program Files\PowerShell\Modules",
            r"c:\program files\powershell\7\Modules",
            r"C:\Program Files\WindowsPowerShell\Modules",
            r"C:\Windows\system32\WindowsPowerShell\v1.0\Modules",
        ]
    )
    monkeypatch.setenv("PSModulePath", module_path)

    env = windows_vm_lab._powershell_subprocess_env(
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )

    module_path_key = next(key for key in env if key.lower() == "psmodulepath")
    parts = env[module_path_key].split(os.pathsep)
    assert parts[0] == r"C:\Program Files\WindowsPowerShell\Modules"
    assert parts[1] == r"C:\Windows\system32\WindowsPowerShell\v1.0\Modules"


def test_prepare_vm_lab_dry_run_plans_targets(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)

    result = windows_vm_lab.prepare_vm_lab(
        layout,
        windows_vm_lab.VmPrepareOptions(config_file=str(config_path), matrix=("win10",), dry_run=True),
    )

    assert result["status"] == "planned"
    assert result["matrix"] == ["win10"]
    assert result["targets"][0]["vmName"] == "emulebb-win10-test"
    assert result["targets"][0]["checkpointName"] == "emulebb-clean"


def test_prepare_vm_target_script_skips_oobe_and_installs_efi_fallback() -> None:
    script = windows_vm_lab._prepare_vm_target_script()

    assert "<SkipMachineOOBE>true</SkipMachineOOBE>" in script
    assert "<SkipUserOOBE>true</SkipUserOOBE>" in script
    assert "<LogonCount>999</LogonCount>" in script
    assert "bootx64.efi" in script


def test_windows_vm_test_dry_run_writes_report(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)

    result = windows_vm_lab.invoke_windows_vm_tests(
        layout,
        _workspace_options(tmp_path),
        windows_vm_lab.WindowsVmTestOptions(
            config_file=str(config_path),
            matrix=("win10", "win11"),
            skip_build=True,
            dry_run=True,
        ),
    )

    report_root = layout.workspace_root / "state" / "test-reports" / "windows-vm"
    assert result["status"] == "planned"
    assert result["matrix"] == ["win10", "win11"]
    assert (report_root / "latest" / windows_vm_lab.WINDOWS_VM_RESULT_FILE_NAME).is_file()
    summary = json.loads((report_root / "latest" / windows_vm_lab.WINDOWS_VM_SUMMARY_FILE_NAME).read_text(encoding="utf-8"))
    assert summary["planned"] == ["win10", "win11"]
