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
                    "password": "a",
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
    assert config.guest.password == "a"
    assert config.targets["win10"].vm_name == "emulebb-win10-test"
    assert config.targets["win11"].edition == "Windows 11 Pro"


def test_preflight_requires_guest_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = _layout(tmp_path)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["guest"].pop("password")
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    config = windows_vm_lab.load_vm_lab_config(layout)
    monkeypatch.delenv("EMULEBB_TEST_VM_PASSWORD", raising=False)
    runner = windows_vm_lab.PowerShellRunner(cwd=tmp_path, dry_run=True)

    with pytest.raises(RuntimeError, match="EMULEBB_TEST_VM_PASSWORD"):
        windows_vm_lab.preflight_hyperv(config, runner=runner, require_password=True)


def test_resolve_guest_password_prefers_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = _layout(tmp_path)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)
    config = windows_vm_lab.load_vm_lab_config(layout)

    monkeypatch.setenv("EMULEBB_TEST_VM_PASSWORD", "from-env")

    assert windows_vm_lab.resolve_guest_password(config) == "from-env"


def test_resolve_guest_password_falls_back_to_local_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = _layout(tmp_path)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)
    config = windows_vm_lab.load_vm_lab_config(layout)

    monkeypatch.delenv("EMULEBB_TEST_VM_PASSWORD", raising=False)

    assert windows_vm_lab.resolve_guest_password(config) == "a"


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


def test_prepare_vm_target_script_installs_python_and_pip_in_guest() -> None:
    script = windows_vm_lab._prepare_vm_target_script()

    assert "python-installer.exe" in script
    assert "Include_pip=1" in script
    assert windows_vm_lab.PYTHON_INSTALL_DIR == r"C:\Python313"
    assert "Get-FileHash -Algorithm SHA256" in script
    assert "Copy-Item -ToSession" in script
    assert "Invoke-WebRequest" not in script


def test_prepare_vm_target_script_installs_hide_me_and_lean_baseline() -> None:
    script = windows_vm_lab._prepare_vm_target_script()

    assert "hide-me-installer.exe" in script
    assert "hide-me-vpn.settings" in script
    assert "Hide.me.exe" in script
    assert "[Diagnostics.Process]::Start" in script
    assert "Stop-Process -Force" in script
    assert windows_vm_lab.HIDE_ME_INSTALL_DIR == r"C:\Program Files (x86)\hide.me VPN"
    assert "Set-LabLeanBaseline" in script
    assert "Add-MpPreference -ExclusionPath" in script
    assert "DisableRealtimeMonitoring" in script
    assert "SysMain" in script
    assert "DoSvc" in script


def test_prepare_vm_target_script_enables_autologin_no_lock_and_debloat() -> None:
    script = windows_vm_lab._prepare_vm_target_script()

    assert "Set-LabAutoLogin" in script
    assert "AutoAdminLogon" in script
    assert "DefaultPassword" in script
    assert "Set-LabNoLock" in script
    assert "NoLockScreen" in script
    assert "InactivityTimeoutSecs" in script
    assert "Remove-LabAppxBloat" in script
    assert "Remove-AppxProvisionedPackage" in script
    assert "XblAuthManager" in script
    assert "Spooler" in script


def test_prepare_vm_target_script_installs_pwsh_in_guest() -> None:
    script = windows_vm_lab._prepare_vm_target_script()

    assert "pwsh-installer.msi" in script
    assert "Install-Pwsh" in script
    assert "msiexec.exe" in script
    assert "ADD_PATH=1" in script
    assert windows_vm_lab.PWSH_INSTALL_DIR == r"C:\Program Files\PowerShell\7"


def test_prepare_vm_target_script_installs_dotnet_desktop_runtime() -> None:
    script = windows_vm_lab._prepare_vm_target_script()

    assert "dotnet-desktop-runtime.exe" in script
    assert "Install-DotNetDesktopRuntime" in script
    assert "Microsoft.WindowsDesktop.App\\6.0.36" in windows_vm_lab.DOTNET_DESKTOP_RUNTIME_DIR


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


def test_windows_vm_local_ed2k_transfer_dry_run_plans_both_targets(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)

    result = windows_vm_lab.invoke_windows_vm_tests(
        layout,
        _workspace_options(tmp_path),
        windows_vm_lab.WindowsVmTestOptions(
            config_file=str(config_path),
            profile="local-ed2k-transfer",
            matrix=("win10", "win11"),
            skip_build=True,
            dry_run=True,
        ),
    )

    assert result["status"] == "planned"
    assert result["profile"] == "local-ed2k-transfer"
    assert [target["target"] for target in result["targets"]] == ["win10", "win11"]


def test_windows_vm_local_ed2k_transfer_requires_both_targets(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)

    with pytest.raises(RuntimeError, match="requires --matrix win10,win11"):
        windows_vm_lab.invoke_windows_vm_tests(
            layout,
            _workspace_options(tmp_path),
            windows_vm_lab.WindowsVmTestOptions(
                config_file=str(config_path),
                profile="local-ed2k-transfer",
                matrix=("win11",),
                skip_build=True,
                dry_run=True,
            ),
        )


def test_ensure_python_installer_uses_verified_cached_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = _layout(tmp_path)
    installer = layout.workspace_root / "state" / "tools" / "python" / windows_vm_lab.PYTHON_INSTALLER_FILE_NAME
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"installer")
    monkeypatch.setattr(windows_vm_lab, "PYTHON_INSTALLER_SHA256", windows_vm_lab._sha256(installer))

    assert windows_vm_lab.ensure_python_installer(layout) == installer


def test_ensure_hide_me_installer_uses_trusted_cached_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)
    installer = layout.workspace_root / "state" / "tools" / "hide-me" / windows_vm_lab.HIDE_ME_INSTALLER_FILE_NAME
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"installer")
    monkeypatch.setattr(windows_vm_lab, "_is_trusted_hide_me_installer", lambda path: path == installer)

    assert windows_vm_lab.ensure_hide_me_installer(layout) == installer


def test_extract_meta_refresh_url_handles_hide_me_download_page() -> None:
    html = '<meta http-equiv="refresh" content="2; url=https://hide.me/downloads/Hide.me-Setup-4.3.2.exe">'

    assert windows_vm_lab._extract_meta_refresh_url(html) == "https://hide.me/downloads/Hide.me-Setup-4.3.2.exe"


def test_latest_pwsh_asset_selects_stable_win_x64_msi(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "assets": [
                        {
                            "name": "PowerShell-7.6.2-win-x64.msi",
                            "browser_download_url": "https://example.invalid/pwsh-x64.msi",
                        },
                        {
                            "name": "PowerShell-7.6.2-preview-win-x64.msi",
                            "browser_download_url": "https://example.invalid/preview.msi",
                        },
                        {
                            "name": "PowerShell-7.6.2-win-arm64.msi",
                            "browser_download_url": "https://example.invalid/arm64.msi",
                        },
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr(windows_vm_lab.urllib.request, "urlopen", lambda request, timeout: Response())

    assert windows_vm_lab._latest_pwsh_win_x64_msi_asset() == {
        "name": "PowerShell-7.6.2-win-x64.msi",
        "browser_download_url": "https://example.invalid/pwsh-x64.msi",
    }


def test_ensure_pwsh_installer_uses_trusted_cached_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)
    installer = layout.workspace_root / "state" / "tools" / "pwsh" / windows_vm_lab.PWSH_INSTALLER_FILE_NAME
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"installer")
    monkeypatch.setattr(windows_vm_lab, "_is_trusted_pwsh_installer", lambda path: path == installer)

    assert windows_vm_lab.ensure_pwsh_installer(layout) == installer


def test_ensure_dotnet_desktop_runtime_installer_uses_trusted_cached_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)
    installer = (
        layout.workspace_root
        / "state"
        / "tools"
        / "dotnet"
        / windows_vm_lab.DOTNET_DESKTOP_RUNTIME_FILE_NAME
    )
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"installer")
    monkeypatch.setattr(windows_vm_lab, "_is_trusted_dotnet_installer", lambda path: path == installer)

    assert windows_vm_lab.ensure_dotnet_desktop_runtime_installer(layout) == installer
