from __future__ import annotations

import json
import os
import zipfile
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
        tooling_repo_root=tmp_path / "repos" / "emulebb-tooling",
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
                    "provisioning_switch_name": "emulebb-test-nat",
                    "provisioning_nat_prefix": "192.168.251.0/24",
                    "provisioning_gateway": "192.168.251.1",
                    "provisioning_prefix_length": 24,
                    "provisioning_dns": ["1.1.1.1", "8.8.8.8"],
                    "provisioning_guest_ips": {"win10": "192.168.251.10", "win11": "192.168.251.11"},
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
    SimpleNamespace(
        name="search-ui-local-swarm-vm",
        title="Windows VM search UI local swarm",
        network_scope="lan",
        release_phase="ui-resource-depth",
        required_targets=SUPPORTED_TARGETS,
        result_file_name=WINDOWS_VM_RESULT_FILE_NAME,
        scenario_id="emulebb.flow.ui.search.local-swarm.v1",
        local_profile="multi-client-p2p",
        local_suites=("local-ed2k-search-soak", "local-kad-swarm"),
        execution_modes=("local", "vm"),
        uses_local_swarm=True,
        control_bind_scope="lan",
        amutorrent_bind_scope="lan",
        p2p_mode="local-swarm",
        p2p_bind_scope="lan",
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
                "scenarioId": getattr(spec, "scenario_id", ""),
                "executionModes": list(getattr(spec, "execution_modes", ("vm",))),
                "localProfile": getattr(spec, "local_profile", ""),
                "localSuites": list(getattr(spec, "local_suites", ())),
                "usesLocalSwarm": bool(getattr(spec, "uses_local_swarm", False)),
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
    (module_dir / "__init__.py").write_text("", encoding="utf-8")
    (module_dir / "vm_host_fixture_contracts.py").write_text(
        """
from __future__ import annotations

SCRIPT_PREFIX = "# script for"
""".lstrip(),
        encoding="utf-8",
    )
    (module_dir / "windows_vm_host.py").write_text(
        """
from __future__ import annotations

from pathlib import Path

from emule_test_harness import vm_host_fixture_contracts

LOCAL_SWARM_VM_PROFILES = ("search-ui-local-swarm-vm",)


def load_guest_script(tests_repo_root, profile_name):
    return f"{vm_host_fixture_contracts.SCRIPT_PREFIX} {profile_name}"


def guest_runner_path(tests_repo_root, profile_name):
    return Path(tests_repo_root) / "emule_test_harness" / f"{profile_name}.py"


def profile_helper_path(tests_repo_root):
    return Path(tests_repo_root) / "emule_test_harness" / "vm_guest_profiles.py"


def local_swarm_payload_paths(tests_repo_root):
    return {
        "harnessPackage": Path(tests_repo_root) / "emule_test_harness",
        "manifests": Path(tests_repo_root) / "manifests",
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
    assert config.hyperv.provisioning_switch_name == "emulebb-test-nat"
    assert config.hyperv.provisioning_nat_prefix == "192.168.251.0/24"
    assert config.hyperv.provisioning_gateway == "192.168.251.1"
    assert config.hyperv.provisioning_prefix_length == 24
    assert config.hyperv.provisioning_dns == ("1.1.1.1", "8.8.8.8")
    assert config.hyperv.provisioning_guest_ips == {"win10": "192.168.251.10", "win11": "192.168.251.11"}
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
        "search-ui-local-swarm-vm",
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
    assert profiles["search-ui-local-swarm-vm"]["executionModes"] == ["local", "vm"]
    assert profiles["search-ui-local-swarm-vm"]["localSuites"] == ["local-ed2k-search-soak", "local-kad-swarm"]
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


def test_prepare_vm_target_script_uses_provisioning_switch_for_internet() -> None:
    script = windows_vm_lab._prepare_vm_target_script()

    assert windows_vm_lab.DEFAULT_PROVISIONING_SWITCH_NAME == "emulebb-vm-nat"
    assert windows_vm_lab.DEFAULT_PROVISIONING_NAT_PREFIX == "192.168.250.0/24"
    assert windows_vm_lab.DEFAULT_PROVISIONING_GATEWAY == "192.168.250.1"
    assert windows_vm_lab.DEFAULT_PROVISIONING_GUEST_IPS["win10"] == "192.168.250.10"
    assert "provisioningSwitchName" in script
    assert "Ensure-ProvisioningNatSwitch" in script
    assert "Remove-VMSwitch" in script
    assert "New-NetNat" in script
    assert "New-NetIPAddress" in script
    assert "-InterfaceIndex $adapter.InterfaceIndex" in script
    assert "Set-DnsClientServerAddress" in script
    assert "Resolve-DnsName -Name 'pypi.org'" in script
    assert "New-VM -Name $payload.vmName" in script
    assert "-SwitchName $provisioningSwitchName" in script


def test_prepare_vm_target_script_installs_python_and_pip_in_guest() -> None:
    script = windows_vm_lab._prepare_vm_target_script()

    assert "python-installer.exe" in script
    assert "Include_pip=1" in script
    assert windows_vm_lab.VM_GUEST_LIVE_PYTHON_PACKAGES == ("pywin32", "pywinauto", "jsonschema", "PyYAML", "playwright")
    assert windows_vm_lab.VM_GUEST_PLAYWRIGHT_BROWSER == "chromium"
    assert "Install-PythonLiveHarnessDependencies" in script
    assert "Install-PlaywrightBrowserRuntime" in script
    assert "-m playwright install $BrowserName" in script
    assert "Playwright browser runtime install failed" in script
    assert "--disable-pip-version-check" in script
    assert "2>&1" in script
    assert "Python live harness dependency install failed" in script
    assert "--no-index" not in script
    assert "python-wheels" not in script
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


def test_prepare_vm_target_script_installs_vc_redist_x64() -> None:
    script = windows_vm_lab._prepare_vm_target_script()

    assert "vc-redist-x64.exe" in script
    assert "Install-VcRedistX64" in script
    assert "/install" in script
    assert "/quiet" in script
    assert "1638" in script
    assert windows_vm_lab.VC_REDIST_X64_URL == "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    assert windows_vm_lab.VC_REDIST_X64_RUNTIME_DLL == r"C:\Windows\System32\MSVCP140.dll"


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


def test_windows_vm_reusable_campaign_summary_records_scenario_metadata(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_profiles(layout)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)

    result = windows_vm_lab.invoke_windows_vm_tests(
        layout,
        _workspace_options(tmp_path),
        windows_vm_lab.WindowsVmTestOptions(
            config_file=str(config_path),
            profile="search-ui-local-swarm-vm",
            matrix=("win10", "win11"),
            skip_build=True,
            dry_run=True,
            swarm_tier=2,
            local_swarm_mode="execute",
        ),
    )

    report_root = layout.workspace_root / "state" / "test-reports" / "windows-vm"
    summary = json.loads((report_root / "latest" / windows_vm_lab.WINDOWS_VM_SUMMARY_FILE_NAME).read_text(encoding="utf-8"))
    expected = {
        "scenarioId": "emulebb.flow.ui.search.local-swarm.v1",
        "vmProfile": "search-ui-local-swarm-vm",
        "localProfile": "multi-client-p2p",
        "localSuites": ["local-ed2k-search-soak", "local-kad-swarm"],
        "executionModes": ["local", "vm"],
        "usesLocalSwarm": True,
        "controlBindScope": "lan",
        "amutorrentBindScope": "lan",
        "p2pMode": "local-swarm",
        "p2pBindScope": "lan",
    }
    assert result["campaignScenario"] == expected
    assert summary["campaignScenario"] == expected


def test_windows_vm_local_swarm_plan_mode_does_not_execute_guest(tmp_path: Path, monkeypatch) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_profiles(layout)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)
    calls: list[str] = []

    def fake_profile_smoke(*args, **kwargs):
        runner = kwargs["runner"]
        target = kwargs["target"] if "target" in kwargs else args[2]
        calls.append(str(runner.dry_run))
        return {
            "target": target.key,
            "vmName": target.vm_name,
            "status": "planned",
            "profile": kwargs["profile"],
            "swarmTier": kwargs["swarm_tier"],
            "localSwarmMode": kwargs["local_swarm_mode"],
            "checkpointName": "emulebb-clean",
            "reportDir": str(tmp_path / "report"),
        }

    monkeypatch.setattr(
        windows_vm_lab,
        "run_windows_vm_profile_smoke",
        fake_profile_smoke,
    )

    result = windows_vm_lab.invoke_windows_vm_tests(
        layout,
        _workspace_options(tmp_path),
        windows_vm_lab.WindowsVmTestOptions(
            config_file=str(config_path),
            profile="search-ui-local-swarm-vm",
            matrix=("win10", "win11"),
            skip_build=True,
            local_swarm_mode="plan",
        ),
    )

    assert result["status"] == "planned"
    assert result["dryRun"] is True
    assert result["requestedDryRun"] is False
    assert result["localSwarmMode"] == "plan"
    assert calls == ["True", "True"]
    assert [target["status"] for target in result["targets"]] == ["planned", "planned"]


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
    tracing_harness_exe = (
        layout.workspace_root
        / "app"
        / "emulebb-community-tracing-harness"
        / "srchybrid"
        / "x64"
        / "Release"
        / "emule.exe"
    )
    amule_daemon_exe = layout.workspace_root / "state" / "tools" / "amule" / "bin" / "amuled.exe"
    amule_control_exe = layout.workspace_root / "state" / "tools" / "amule" / "bin" / "amulecmd.exe"
    release_asset_paths = windows_vm_lab._local_swarm_release_asset_paths(layout, "0.7.3-rc.1", "x64")
    for path in (tracing_harness_exe, amule_daemon_exe, amule_control_exe):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (layout.tests_repo_root / "scripts").mkdir(parents=True, exist_ok=True)
    (layout.tests_repo_root / "scripts" / "godzilla-local-swarm.py").write_text("# local swarm\n", encoding="utf-8")
    (layout.tests_repo_root / "manifests").mkdir(parents=True, exist_ok=True)
    (layout.tests_repo_root / "manifests" / "release-campaigns.v1.json").write_text("{}\n", encoding="utf-8")

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
            local_swarm_release_asset_paths=release_asset_paths,
            local_swarm_node_archive_path=windows_vm_lab._local_swarm_node_archive_path(layout, "x64"),
            release_version="0.7.3-rc.1",
            platform="x64",
            run_id="run",
            run_report_dir=tmp_path / "report",
            keep_running=False,
            fixture_size_bytes=4096,
            swarm_tier=3,
            local_swarm_mode="execute",
            runner=CaptureRunner(),
        )
    finally:
        monkeypatch.undo()

    assert result["status"] == "passed"
    assert result["swarmTier"] == 3
    assert result["localSwarmMode"] == "execute"
    assert "localSwarmHarnessArchivePath" in captured[0]
    assert "localSwarmHarnessPackagePath" not in captured[0]
    assert "localSwarmManifestsPath" not in captured[0]
    assert "localSwarmScriptPaths" not in captured[0]
    assert "localSwarmReleaseAssetPaths" in captured[0]
    assert "localSwarmNodeArchivePath" in captured[0]
    assert "localSwarmNodeSha256" in captured[0]
    assert "releaseVersion" in captured[0]
    assert "localSwarmRestOpenApiPath" in captured[0]
    assert "localSwarmAppSourcePaths" in captured[0]
    assert "localSwarmGoed2kServerExe" in captured[0]
    assert "localSwarmClient2AppExe" in captured[0]
    assert "localSwarmAmuleDaemonExe" in captured[0]
    assert "localSwarmAmuleControlExe" in captured[0]
    assert "localSwarmMode" in captured[0]
    assert "lanBindAddr" in captured[0]
    assert "localSwarmLanBindAddr" in captured[0]
    assert "192.168.251.10" in captured[0]
    assert "goed2k-server.exe" in captured[0]
    assert "emule.exe" in captured[0]
    assert "amuled.exe" in captured[0]
    assert "amulecmd.exe" in captured[0]
    assert "emulebb-0.7.3-rc.1-amutorrent-x64.zip" in captured[0]
    assert "repos\\\\amutorrent" not in captured[0]
    assert "REST-API-OPENAPI.yaml" in captured[0]
    assert "WebServerJsonSeams.h" in captured[0]
    assert "WebServerQBitCompatSeams.h" in captured[0]
    assert "WebServerArrCompatSeams.h" in captured[0]
    assert "WebServerArrCompat.cpp" in captured[0]


def test_windows_vm_profile_smoke_payload_stages_harness_for_plain_profiles(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_host(layout)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)
    config = windows_vm_lab.load_vm_lab_config(layout, config_file=str(config_path))
    captured: list[str] = []
    (layout.tests_repo_root / "scripts").mkdir(parents=True, exist_ok=True)
    (layout.tests_repo_root / "scripts" / "godzilla-local-swarm.py").write_text("# local swarm\n", encoding="utf-8")
    (layout.tests_repo_root / "manifests").mkdir(parents=True, exist_ok=True)
    (layout.tests_repo_root / "manifests" / "release-campaigns.v1.json").write_text("{}\n", encoding="utf-8")

    class CaptureRunner:
        dry_run = False

        def run(self, script: str, *, label: str, capture_json: bool = False) -> str:
            captured.append(script)
            return json.dumps({"status": "passed", "guest": {}, "checks": [], "errors": []})

    result = windows_vm_lab.run_windows_vm_profile_smoke(
        layout,
        config,
        config.targets["win10"],
        profile="rest-smoke-stress",
        package_zip=tmp_path / "package.zip",
        local_swarm_release_asset_paths=[],
        local_swarm_node_archive_path=None,
        release_version="0.7.3-rc.1",
        platform="x64",
        run_id="run",
        run_report_dir=tmp_path / "report",
        keep_running=False,
        fixture_size_bytes=4096,
        swarm_tier=1,
        local_swarm_mode="plan",
        runner=CaptureRunner(),
    )

    assert result["status"] == "passed"
    assert "localSwarmHarnessArchivePath" in captured[0]
    assert "local-swarm-harness-payload.zip" in captured[0]
    assert "@($guestHarnessRoot, $guestRoot)" in captured[0]


def test_windows_vm_package_smoke_payload_uses_lan_bind_addr(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_host(layout)
    config_path = layout.build_repo_root / "vm-lab.local.json"
    _write_config(config_path)
    config = windows_vm_lab.load_vm_lab_config(layout, config_file=str(config_path))
    captured: list[str] = []

    class CaptureRunner:
        dry_run = False

        def run(self, script: str, *, label: str, capture_json: bool = False) -> str:
            captured.append(script)
            return json.dumps({"status": "passed", "guest": {}, "checks": [], "errors": []})

    result = windows_vm_lab.run_windows_vm_package_smoke(
        layout,
        config,
        config.targets["win10"],
        package_zip=tmp_path / "package.zip",
        run_id="run",
        run_report_dir=tmp_path / "report",
        keep_running=False,
        runner=CaptureRunner(),
    )

    assert result["status"] == "passed"
    assert "lanBindAddr" in captured[0]
    assert "192.168.251.10" in captured[0]


def test_local_swarm_harness_payload_archive_is_curated(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _write_harness_vm_host(layout)
    harness_package = layout.tests_repo_root / "emule_test_harness"
    (harness_package / "__pycache__").mkdir()
    (harness_package / "__pycache__" / "ignored.pyc").write_bytes(b"pyc")
    (harness_package / "live_e2e_suite.py").write_text("# suite\n", encoding="utf-8")
    (layout.tests_repo_root / "scripts").mkdir(parents=True, exist_ok=True)
    (layout.tests_repo_root / "scripts" / "godzilla-local-swarm.py").write_text("# script\n", encoding="utf-8")
    (layout.tests_repo_root / "manifests").mkdir(parents=True, exist_ok=True)
    (layout.tests_repo_root / "manifests" / "release-campaigns.v1.json").write_text("{}\n", encoding="utf-8")
    host_contracts = windows_vm_lab.load_windows_vm_host_contracts(layout)

    archive_path = windows_vm_lab._stage_local_swarm_harness_payload_archive(
        layout,
        tmp_path / "report",
        host_contracts,
    )

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "emule_test_harness/live_e2e_suite.py" in names
    assert "scripts/godzilla-local-swarm.py" in names
    assert "manifests/release-campaigns.v1.json" in names
    assert not any("node_modules" in name or "/.git/" in name or "workspaces/" in name for name in names)
    assert not any(name.endswith(".pyc") or "__pycache__" in name for name in names)


def test_local_swarm_companion_exes_are_optional(tmp_path: Path) -> None:
    layout = _layout(tmp_path)

    assert windows_vm_lab.local_swarm_tracing_harness_app_exe(layout) is None
    assert windows_vm_lab.local_swarm_amule_exes(layout) == (None, None)


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
