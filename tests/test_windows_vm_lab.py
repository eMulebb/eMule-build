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
                    "vpn_switch_name": "emulebb-test-vpn-switch",
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


def _write_harness_vm_profiles(layout: SimpleNamespace) -> None:
    module_dir = layout.tests_repo_root / "emule_test_harness"
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "windows_vm_profiles.py").write_text(
        """
from __future__ import annotations

from types import SimpleNamespace

SUPPORTED_TARGETS = ("win10", "win11")
WINDOWS_VM_RESULT_FILE_NAME = "windows-vm-result.json"
WINDOWS_VM_SUMMARY_FILE_NAME = "windows-vm-summary.json"
WINDOWS_VM_PROFILE_SPECS = (
    SimpleNamespace(
        name="package-smoke",
        title="Windows VM package smoke",
        network_scope="offline",
        release_phase="packaging-provenance",
        required_targets=SUPPORTED_TARGETS,
        result_file_name=WINDOWS_VM_RESULT_FILE_NAME,
    ),
    SimpleNamespace(
        name="local-ed2k-transfer",
        title="Windows VM local eD2K transfer",
        network_scope="lan",
        release_phase="protocol-parity",
        required_targets=SUPPORTED_TARGETS,
        result_file_name="local-ed2k-transfer-result.json",
    ),
    SimpleNamespace(
        name="hideme-live-wire",
        title="Windows VM hide.me live-wire",
        network_scope="vpn",
        release_phase="live-wire-release",
        required_targets=SUPPORTED_TARGETS,
        result_file_name="hideme-live-wire-result.json",
    ),
    SimpleNamespace(
        name="rest-smoke-stress",
        title="Windows VM REST smoke/stress",
        network_scope="offline",
        release_phase="controller-surface",
        required_targets=SUPPORTED_TARGETS,
        result_file_name=WINDOWS_VM_RESULT_FILE_NAME,
    ),
    SimpleNamespace(
        name="crash-dump-smoke",
        title="Windows VM crash/dump smoke",
        network_scope="offline",
        release_phase="stabilization-stress",
        required_targets=SUPPORTED_TARGETS,
        result_file_name=WINDOWS_VM_RESULT_FILE_NAME,
    ),
    SimpleNamespace(
        name="cpu-heavy-quick",
        title="Windows VM CPU-heavy quick smoke",
        network_scope="offline",
        release_phase="stabilization-stress",
        required_targets=SUPPORTED_TARGETS,
        result_file_name=WINDOWS_VM_RESULT_FILE_NAME,
    ),
    SimpleNamespace(
        name="resource-ui-smoke",
        title="Windows VM resource UI smoke",
        network_scope="offline",
        release_phase="ui-resource-depth",
        required_targets=SUPPORTED_TARGETS,
        result_file_name=WINDOWS_VM_RESULT_FILE_NAME,
    ),
    SimpleNamespace(
        name="release-expanded-ui",
        title="Windows VM release-expanded UI smoke",
        network_scope="offline",
        release_phase="live-wire-release",
        required_targets=SUPPORTED_TARGETS,
        result_file_name=WINDOWS_VM_RESULT_FILE_NAME,
    ),
)
WINDOWS_VM_PROFILE_BY_NAME = {spec.name: spec for spec in WINDOWS_VM_PROFILE_SPECS}
SUPPORTED_TEST_PROFILES = tuple(spec.name for spec in WINDOWS_VM_PROFILE_SPECS)
LOCAL_ED2K_REQUIRED_TARGETS = WINDOWS_VM_PROFILE_BY_NAME["local-ed2k-transfer"].required_targets
HIDEME_LIVE_REQUIRED_TARGETS = WINDOWS_VM_PROFILE_BY_NAME["hideme-live-wire"].required_targets


def build_windows_vm_profile_matrix():
    return {
        "schema": "emulebb.windows-vm-profile-matrix.fixture.v1",
        "profiles": [
            {
                "name": spec.name,
                "title": spec.title,
                "networkScope": spec.network_scope,
                "releasePhase": spec.release_phase,
                "requiredTargets": list(spec.required_targets),
                "resultFileName": spec.result_file_name,
            }
            for spec in WINDOWS_VM_PROFILE_SPECS
        ],
    }
""".lstrip(),
        encoding="utf-8",
    )


def _write_harness_vm_host(layout: SimpleNamespace) -> None:
    module_dir = layout.tests_repo_root / "emule_test_harness"
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "windows_vm_host.py").write_text(
        """
from __future__ import annotations

from pathlib import Path

LOCAL_SWARM_VM_PROFILES = ("search-ui-local-swarm-vm",)


def load_guest_script(tests_repo_root, profile_name):
    return f"# script for {profile_name}"


def guest_runner_path(tests_repo_root, profile_name):
    return Path(tests_repo_root) / "emule_test_harness" / f"{profile_name}.py"


def profile_helper_path(tests_repo_root):
    return Path(tests_repo_root) / "emule_test_harness" / "vm_guest_profiles.py"


def local_swarm_payload_paths(tests_repo_root):
    return {
        "harnessPackage": Path(tests_repo_root) / "emule_test_harness",
        "scripts": [Path(tests_repo_root) / "scripts" / "godzilla-local-swarm.py"],
    }


def build_local_ed2k_target_payloads(vm_names):
    return {key: {"target": key, "vmName": value, "tcpPort": 1, "udpPort": 2, "restPort": 3} for key, value in vm_names.items()}


def build_hideme_live_target_payloads(vm_names):
    return {key: {"target": key, "vmName": value, "tcpPort": 4, "udpPort": 5, "restPort": 6} for key, value in vm_names.items()}
""".lstrip(),
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
    assert config.hyperv.vpn_switch_name == "emulebb-test-vpn-switch"
    assert config.hyperv.memory_mb == 2048
    assert config.guest.password_env == "EMULEBB_TEST_VM_PASSWORD"
    assert config.guest.password == "a"
    assert config.targets["win10"].vm_name == "emulebb-win10-test"
    assert config.targets["win11"].edition == "Windows 11 Pro"


def test_windows_vm_profile_matrix_loads_harness_authority(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_profiles(layout)

    matrix = windows_vm_lab.build_windows_vm_profile_matrix(layout)
    profiles = {profile["name"]: profile for profile in matrix["profiles"]}

    assert tuple(profiles) == (
        "package-smoke",
        "local-ed2k-transfer",
        "hideme-live-wire",
        "rest-smoke-stress",
        "crash-dump-smoke",
        "cpu-heavy-quick",
        "resource-ui-smoke",
        "release-expanded-ui",
    )
    assert profiles["package-smoke"]["networkScope"] == "offline"
    assert profiles["package-smoke"]["releasePhase"] == "packaging-provenance"
    assert profiles["package-smoke"]["requiredTargets"] == ["win10", "win11"]
    assert profiles["local-ed2k-transfer"]["networkScope"] == "lan"
    assert profiles["local-ed2k-transfer"]["releasePhase"] == "protocol-parity"
    assert profiles["hideme-live-wire"]["networkScope"] == "vpn"
    assert profiles["hideme-live-wire"]["releasePhase"] == "live-wire-release"
    assert profiles["rest-smoke-stress"]["releasePhase"] == "controller-surface"
    assert profiles["crash-dump-smoke"]["releasePhase"] == "stabilization-stress"
    assert profiles["cpu-heavy-quick"]["releasePhase"] == "stabilization-stress"
    assert profiles["resource-ui-smoke"]["releasePhase"] == "ui-resource-depth"
    assert profiles["release-expanded-ui"]["releasePhase"] == "live-wire-release"
    json.dumps(matrix)


def test_windows_vm_host_contracts_load_from_harness(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_host(layout)

    host_contracts = windows_vm_lab.load_windows_vm_host_contracts(layout)

    assert host_contracts.load_guest_script(layout.tests_repo_root, "package-smoke") == "# script for package-smoke"
    assert host_contracts.guest_runner_path(layout.tests_repo_root, "local-ed2k-transfer").name == (
        "local-ed2k-transfer.py"
    )
    assert host_contracts.build_hideme_live_target_payloads({"win10": "vm"})["win10"]["tcpPort"] == 4


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
    assert "Set-LabWindowsUpdateContainment" in script
    assert "NoAutoUpdate" in script
    assert "DoNotConnectToWindowsUpdateInternetLocations" in script
    assert "wuauserv" in script
    assert "UsoSvc" in script
    assert "BITS" in script
    assert "UpdateOrchestrator" in script
    assert "Schedule Scan" in script


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
    assert "dotnet-desktop-runtime-x86.exe" in script
    assert "Install-DotNetDesktopRuntime" in script
    assert "Microsoft.WindowsDesktop.App\\6.0.36" in windows_vm_lab.DOTNET_DESKTOP_RUNTIME_DIR
    assert "Microsoft.WindowsDesktop.App\\6.0.36" in windows_vm_lab.DOTNET_DESKTOP_RUNTIME_X86_DIR
    assert "Program Files (x86)" in windows_vm_lab.DOTNET_DESKTOP_RUNTIME_X86_DIR


def test_windows_vm_test_dry_run_writes_report(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_profiles(layout)
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


def test_windows_vm_generic_profile_dry_run_plans_both_targets(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_profiles(layout)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)

    result = windows_vm_lab.invoke_windows_vm_tests(
        layout,
        _workspace_options(tmp_path),
        windows_vm_lab.WindowsVmTestOptions(
            config_file=str(config_path),
            profile="rest-smoke-stress",
            matrix=("win10", "win11"),
            skip_build=True,
            dry_run=True,
            swarm_tier=2,
        ),
    )

    assert result["status"] == "planned"
    assert result["profile"] == "rest-smoke-stress"
    assert result["swarmTier"] == 2
    assert [target["target"] for target in result["targets"]] == ["win10", "win11"]
    assert {target["swarmTier"] for target in result["targets"]} == {2}


def test_windows_vm_profile_smoke_payload_stages_local_swarm_harness(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_host(layout)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)
    config = windows_vm_lab.load_vm_lab_config(layout, config_file=str(config_path))
    captured: list[str] = []
    goed2k_server_exe = tmp_path / "tools" / "goed2k-server.exe"
    goed2k_server_exe.parent.mkdir()
    goed2k_server_exe.write_text("", encoding="utf-8")

    class CaptureRunner:
        dry_run = False

        def run(self, script: str, *, label: str, capture_json: bool = False) -> str:
            captured.append(script)
            return json.dumps({"status": "passed", "guest": {}, "checks": [], "errors": []})

    def fake_build_goed2k_server_exe(_layout: WorkspaceLayout) -> Path:
        return goed2k_server_exe

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(windows_vm_lab, "build_goed2k_server_exe", fake_build_goed2k_server_exe)
    try:
        result = windows_vm_lab.run_windows_vm_profile_smoke(
            layout,
            config,
            config.targets["win10"],
            profile="search-ui-local-swarm-vm",
            package_zip=tmp_path / "package.zip",
            run_id="run",
            run_report_dir=tmp_path / "report",
            keep_running=False,
            fixture_size_bytes=4096,
            swarm_tier=3,
            runner=CaptureRunner(),
        )
    finally:
        monkeypatch.undo()

    assert result["status"] == "passed"
    assert result["swarmTier"] == 3
    assert "localSwarmHarnessPackagePath" in captured[0]
    assert "localSwarmScriptPaths" in captured[0]
    assert "localSwarmGoed2kServerExe" in captured[0]
    assert "goed2k-server.exe" in captured[0]
    assert "godzilla-local-swarm.py" in captured[0]


def test_windows_vm_local_ed2k_transfer_dry_run_plans_both_targets(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_profiles(layout)
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
    _write_harness_vm_profiles(layout)
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


def test_windows_vm_hideme_live_wire_dry_run_plans_both_targets(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_profiles(layout)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)

    result = windows_vm_lab.invoke_windows_vm_tests(
        layout,
        _workspace_options(tmp_path),
        windows_vm_lab.WindowsVmTestOptions(
            config_file=str(config_path),
            profile="hideme-live-wire",
            matrix=("win10", "win11"),
            skip_build=True,
            dry_run=True,
        ),
    )

    assert result["status"] == "planned"
    assert result["profile"] == "hideme-live-wire"
    assert [target["target"] for target in result["targets"]] == ["win10", "win11"]


def test_windows_vm_hideme_live_wire_requires_both_targets(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_profiles(layout)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)

    with pytest.raises(RuntimeError, match="requires --matrix win10,win11"):
        windows_vm_lab.invoke_windows_vm_tests(
            layout,
            _workspace_options(tmp_path),
            windows_vm_lab.WindowsVmTestOptions(
                config_file=str(config_path),
                profile="hideme-live-wire",
                matrix=("win10",),
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


def test_ensure_dotnet_desktop_runtime_x86_installer_uses_trusted_cached_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path)
    installer = (
        layout.workspace_root
        / "state"
        / "tools"
        / "dotnet"
        / windows_vm_lab.DOTNET_DESKTOP_RUNTIME_X86_FILE_NAME
    )
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"installer")
    monkeypatch.setattr(windows_vm_lab, "_is_trusted_dotnet_installer", lambda path: path == installer)

    assert windows_vm_lab.ensure_dotnet_desktop_runtime_x86_installer(layout) == installer
