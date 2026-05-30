from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from emule_workspace.config import LiveE2eOptions, ReleaseCampaignOptions, WorkspaceOptions
from emule_workspace.layout import AppVariant, TestTargets as LayoutTestTargets, WorkspaceLayout
from emule_workspace import test_runs


def make_layout(tmp_path: Path) -> WorkspaceLayout:
    """Builds a minimal layout with the live E2E runner script present."""

    emule_workspace_root = tmp_path
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    tests_repo_root = emule_workspace_root / "repos" / "emulebb-build-tests"
    app_root = workspace_root / "app" / "emulebb-main"
    (tests_repo_root / "scripts").mkdir(parents=True)
    (tests_repo_root / "scripts" / "run-live-e2e-suite.py").write_text("# test runner\n", encoding="utf-8")
    (tests_repo_root / "scripts" / "show-release-campaigns.py").write_text("# campaign reporter\n", encoding="utf-8")
    app_root.mkdir(parents=True)
    return WorkspaceLayout(
        emule_workspace_root=emule_workspace_root,
        workspace_name="workspace",
        workspace_root=workspace_root,
        build_repo_root=emule_workspace_root / "repos" / "emulebb-build",
        tests_repo_root=tests_repo_root,
        tooling_repo_root=emule_workspace_root / "repos" / "emulebb-tooling",
        ed2k_server_repo_root=emule_workspace_root / "repos" / "goed2k-server",
        amule_repo_root=emule_workspace_root / "repos" / "amule",
        seed_repo_path=emule_workspace_root / "repos" / "emulebb",
        seed_repo_branch="main",
        dependencies=(),
        app_variants=(AppVariant(name="main", path=app_root, branch="main"),),
        test_targets=LayoutTestTargets(test_build_variant="main", test_run_variant="main", baseline_variant="community"),
        toolset_override_variable="",
    )


def option_values(command: list[str], option: str) -> list[str]:
    """Returns values that immediately follow an option in a captured command."""

    return [command[index + 1] for index, value in enumerate(command[:-1]) if value == option]


@pytest.fixture(autouse=True)
def fake_network_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(*, workspace_root, test_network, vpn_interface_name=None, require_vpn=False, require_lan=False):
        return SimpleNamespace(
            env=lambda: {
                "EMULEBB_TEST_NETWORK": test_network,
                "EMULEBB_TEST_NETWORK_CONTEXT_JSON": str(Path(workspace_root) / "state" / "network-context" / "fake.json"),
            }
        )

    monkeypatch.setattr(test_runs, "resolve_workspace_network_context", resolve)


def test_live_e2e_forwards_cold_stress_cpu_profile_options(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)
        captured["label"] = label
        captured["cwd"] = cwd
        captured["env"] = dict(env or {})

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("rest-cold-start-dump-stress",),
            profile_cpu=True,
            profile_cpu_max_file_mb=96,
            profile_cpu_stack=True,
            profile_cpu_stack_min_hits=15,
            profile_symbols_required=False,
            profile_memory=True,
            profile_resource_interval_seconds=1.5,
            rest_cold_start_dump_stress_enable_umdh=True,
            rest_cold_start_dump_stress_cpu_profile=True,
            rest_cold_start_dump_stress_cpu_profile_max_file_mb=64,
            rest_cold_start_dump_stress_cpu_profile_stack=True,
            rest_cold_start_dump_stress_cpu_profile_stack_min_hits=25,
            rest_cold_start_dump_stress_cpu_profile_symbols_required=False,
            rest_cold_start_dump_stress_max_missing_download_triggers=1,
            rest_cold_start_dump_stress_synthetic_queue_fill_count=5,
            rest_cold_start_dump_stress_synthetic_queue_fill_size_bytes=4096,
            rest_cold_start_dump_stress_synthetic_queue_fill_batch_size=3,
            rest_cold_start_dump_stress_search_observation_timeout_seconds=12.0,
            rest_cold_start_dump_stress_allow_required_zero_result_searches=True,
            rest_cold_start_dump_stress_skip_transfer_cleanup=True,
            rest_cold_start_dump_stress_skip_umdh_diffs=True,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--profile-cpu" in command
    assert option_values(command, "--profile-cpu-max-file-mb") == ["96"]
    assert "--profile-cpu-stack" in command
    assert option_values(command, "--profile-cpu-stack-min-hits") == ["15"]
    assert "--no-profile-symbols-required" in command
    assert "--profile-memory" in command
    assert option_values(command, "--profile-resource-interval-seconds") == ["1.5"]
    assert "--rest-cold-start-dump-stress-enable-umdh" in command
    assert "--rest-cold-start-dump-stress-cpu-profile" in command
    assert option_values(command, "--rest-cold-start-dump-stress-cpu-profile-max-file-mb") == ["64"]
    assert "--rest-cold-start-dump-stress-cpu-profile-stack" in command
    assert option_values(command, "--rest-cold-start-dump-stress-cpu-profile-stack-min-hits") == ["25"]
    assert option_values(command, "--rest-cold-start-dump-stress-max-missing-download-triggers") == ["1"]
    assert option_values(command, "--rest-cold-start-dump-stress-synthetic-queue-fill-count") == ["5"]
    assert option_values(command, "--rest-cold-start-dump-stress-synthetic-queue-fill-size-bytes") == ["4096"]
    assert option_values(command, "--rest-cold-start-dump-stress-synthetic-queue-fill-batch-size") == ["3"]
    assert option_values(command, "--rest-cold-start-dump-stress-search-observation-timeout-seconds") == ["12.0"]
    assert "--rest-cold-start-dump-stress-allow-required-zero-result-searches" in command
    assert "--rest-cold-start-dump-stress-skip-transfer-cleanup" in command
    assert "--rest-cold-start-dump-stress-skip-umdh-diffs" in command
    assert "--no-rest-cold-start-dump-stress-cpu-profile-symbols-required" in command
    assert "--rest-cold-start-dump-stress-skip-dumps" not in command
    assert captured["env"]["EMULEBB_WORKSPACE_ROOT"] == str(layout.emule_workspace_root)
    assert captured["env"]["EMULEBB_TEST_NETWORK"] == "default"


def test_live_e2e_forwards_preference_directory_tree_stress(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("preference-ui",),
            shared_root=r"C:\tmp\large-shared-root",
            preference_ui_directories_tree_stress=True,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--preference-ui-directories-tree-stress" in command
    assert option_values(command, "--shared-root") == [r"C:\tmp\large-shared-root"]


def test_live_e2e_forwards_local_kad_bootstrap_mode(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("local-kad-swarm",),
            local_kad_bootstrap_mode="preseed",
            local_kad_nodes_dat_fixture_mode="stale",
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--local-kad-bootstrap-mode") == ["preseed"]
    assert option_values(command, "--local-kad-nodes-dat-fixture-mode") == ["stale"]


def test_live_e2e_forwards_admin_volume_fixture_options(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("shared-cache-volume-identity",),
            admin_volume_fixtures=True,
            vhd_size_mb=384,
            mount_root=r"C:\tmp\emulebb-admin-mounts",
            keep_admin_fixtures=True,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--admin-volume-fixtures" in command
    assert option_values(command, "--vhd-size-mb") == ["384"]
    assert option_values(command, "--mount-root") == [r"C:\tmp\emulebb-admin-mounts"]
    assert "--keep-admin-fixtures" in command


def test_live_e2e_forwards_dependency_resolution_options(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    cache_root = r"state\arr-cache"
    prowlarr_exe = r"tools\Prowlarr\Prowlarr.exe"
    radarr_exe = r"tools\Radarr\Radarr.exe"
    sonarr_exe = r"tools\Sonarr\Sonarr.exe"
    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            profile="package-helpers",
            dependency_mode="auto-download",
            dependency_channel="latest",
            dependency_cache_root=cache_root,
            refresh_dependencies=True,
            prowlarr_exe=prowlarr_exe,
            radarr_exe=radarr_exe,
            sonarr_exe=sonarr_exe,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["package-helpers"]
    assert option_values(command, "--dependency-mode") == ["auto-download"]
    assert option_values(command, "--dependency-channel") == ["latest"]
    assert option_values(command, "--dependency-cache-root") == [str((layout.emule_workspace_root / cache_root).resolve())]
    assert "--refresh-dependencies" in command
    assert option_values(command, "--prowlarr-exe") == [str((layout.emule_workspace_root / prowlarr_exe).resolve())]
    assert option_values(command, "--radarr-exe") == [str((layout.emule_workspace_root / radarr_exe).resolve())]
    assert option_values(command, "--sonarr-exe") == [str((layout.emule_workspace_root / sonarr_exe).resolve())]


def test_live_e2e_forwards_search_ui_live_stress_options(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("search-ui-live",),
            search_ui_search_rounds=4,
            search_ui_download_lifecycle_count=3,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--search-ui-search-rounds") == ["4"]
    assert option_values(command, "--search-ui-download-lifecycle-count") == ["3"]


def test_live_e2e_forwards_godzilla_visible_ui_and_lan_bind(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("godzilla-local-swarm",),
            p2p_bind_interface_name="Ethernet",
            godzilla_p2p_bind_interface_address="192.168.1.210",
            godzilla_visible_ui=True,
            godzilla_cpu_profile=True,
            godzilla_stage="launch-scale",
            godzilla_vhd_runtime_root="drive-letter",
            godzilla_total_client_count=12,
            godzilla_peer_transfer_count=444,
            godzilla_harness_transfer_count=222,
            godzilla_emulebb_files=700,
            godzilla_extra_emulebb_files=70,
            godzilla_harness_files=500,
            godzilla_amule_files=120,
            godzilla_adverse_kill_cycles=3,
            godzilla_adverse_kill_warmup_seconds=0.5,
            godzilla_adverse_recovery_timeout_seconds=45.0,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--p2p-bind-interface-name") == ["Ethernet"]
    assert option_values(command, "--godzilla-p2p-bind-interface-address") == ["192.168.1.210"]
    assert option_values(command, "--godzilla-stage") == ["launch-scale"]
    assert option_values(command, "--godzilla-vhd-runtime-root") == ["drive-letter"]
    assert option_values(command, "--godzilla-total-client-count") == ["12"]
    assert option_values(command, "--godzilla-peer-transfer-count") == ["444"]
    assert option_values(command, "--godzilla-harness-transfer-count") == ["222"]
    assert option_values(command, "--godzilla-emulebb-files") == ["700"]
    assert option_values(command, "--godzilla-extra-emulebb-files") == ["70"]
    assert option_values(command, "--godzilla-harness-files") == ["500"]
    assert option_values(command, "--godzilla-amule-files") == ["120"]
    assert option_values(command, "--godzilla-adverse-kill-cycles") == ["3"]
    assert option_values(command, "--godzilla-adverse-kill-warmup-seconds") == ["0.5"]
    assert option_values(command, "--godzilla-adverse-recovery-timeout-seconds") == ["45.0"]
    assert "--godzilla-visible-ui" in command
    assert "--godzilla-cpu-profile" in command


def test_live_e2e_leaves_godzilla_stage_unset_for_profile_defaults(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="release-expanded"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--godzilla-stage" not in command


def test_live_e2e_can_run_against_materialized_installer_test_install(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    materialize_calls: list[object] = []

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    def fake_materialize(layout, workspace_options, install_options, *, run_id, suite_name, client_id):
        materialize_calls.append(
            SimpleNamespace(
                layout=layout,
                workspace_options=workspace_options,
                install_options=install_options,
                run_id=run_id,
                suite_name=suite_name,
                client_id=client_id,
            )
        )
        install_root = tmp_path / "workspaces" / "workspace" / "state" / "test-installs" / "run" / "live-e2e-suite" / "main"
        return SimpleNamespace(
            app_root=install_root / "apps" / "eMuleBB",
            app_exe=install_root / "apps" / "eMuleBB" / "emulebb.exe",
            profile_dir=install_root / "profiles" / "emulebb",
            profile_config_dir=install_root / "profiles" / "emulebb" / "config",
            profile_seed_config_dir=install_root / "harness-profile-seed" / "config",
        )

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)
    monkeypatch.setattr(test_runs, "materialize_test_local_install", fake_materialize)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("godzilla-local-swarm",),
            live_wire_inputs_file="repos/emulebb-build-tests/live-wire-inputs.local.json",
            materialize_test_install=True,
            materialize_test_install_release_version="0.7.4-rc.2",
            materialize_test_install_clean=True,
            materialize_test_install_skip_build=True,
        ),
    )

    command = captured["command"]
    call = materialize_calls[0]
    assert isinstance(command, list)
    assert call.install_options.live_wire_inputs_file == "repos/emulebb-build-tests/live-wire-inputs.local.json"
    assert call.install_options.release_version == "0.7.4-rc.2"
    assert call.install_options.clean is True
    assert call.install_options.skip_build is True
    assert call.suite_name == "live-e2e-suite"
    assert call.client_id == "main"
    assert call.run_id.endswith("-pid" + str(os.getpid()))
    install_root = call.layout.workspace_root / "state" / "test-installs" / "run" / "live-e2e-suite" / "main"
    assert option_values(command, "--app-root") == [str(install_root / "apps" / "eMuleBB")]
    assert option_values(command, "--app-exe") == [
        str(install_root / "apps" / "eMuleBB" / "emulebb.exe")
    ]
    assert option_values(command, "--profile-seed-dir") == [str(install_root / "harness-profile-seed" / "config")]
    assert option_values(command, "--live-process-monitor-profile-dir") == [str(install_root / "profiles" / "emulebb")]
    assert option_values(command, "--live-wire-inputs-file") == ["repos/emulebb-build-tests/live-wire-inputs.local.json"]


def test_live_e2e_forwards_explicit_live_process_monitor_profile_dir(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    profile_dir = r"F:\M\H06T01\dldz\EMULE_BIN"
    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("live-process-monitor",),
            test_network="vpn",
            live_process_monitor_profile_dir=profile_dir,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--live-process-monitor-profile-dir") == [profile_dir]


def test_live_e2e_registers_materialized_exe_for_developer_hide_me_split_tunnel(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    registered: list[Path] = []

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    def fake_materialize(layout_arg, workspace_options, install_options, *, run_id, suite_name, client_id):
        install_root = tmp_path / "workspaces" / "workspace" / "state" / "test-installs" / run_id / suite_name / client_id
        app_exe = install_root / "apps" / "eMuleBB" / "emulebb.exe"
        seed_config = install_root / "harness-profile-seed" / "config"
        profile_dir = install_root / "profiles" / "emulebb"
        app_exe.parent.mkdir(parents=True)
        seed_config.mkdir(parents=True)
        profile_dir.mkdir(parents=True)
        app_exe.write_bytes(b"exe")
        return SimpleNamespace(
            app_root=app_exe.parent,
            app_exe=app_exe,
            profile_dir=profile_dir,
            profile_config_dir=profile_dir / "config",
            profile_seed_config_dir=seed_config,
        )

    def fake_register(paths):
        registered.extend(paths)
        return {"enabled": True}

    layout = make_layout(tmp_path)
    node_exe = tmp_path / "runtime" / "node" / "node.exe"
    node_exe.parent.mkdir(parents=True)
    node_exe.write_bytes(b"node")
    browser_exe = tmp_path / "local-appdata" / "ms-playwright" / "chromium-1234" / "chrome-win64" / "chrome.exe"
    browser_exe.parent.mkdir(parents=True)
    browser_exe.write_bytes(b"chrome")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-appdata"))
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)
    monkeypatch.setattr(test_runs, "materialize_test_local_install", fake_materialize)
    monkeypatch.setattr(test_runs, "ensure_split_tunnel_apps", fake_register)
    monkeypatch.setattr(test_runs, "find_tool", lambda names: node_exe)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("prowlarr-emulebb",),
            test_network="vpn",
            materialize_test_install=True,
            materialize_test_install_skip_build=True,
        ),
    )

    assert registered[0] == Path(option_values(captured["command"], "--app-exe")[0])
    assert any(path.name.casefold() in {"python.exe", "python"} for path in registered[1:])
    assert node_exe in registered
    assert browser_exe in registered


def test_live_e2e_restarts_hide_me_when_failed_report_points_at_upnp(tmp_path: Path, monkeypatch) -> None:
    reports = tmp_path / "workspaces" / "workspace" / "state" / "test-reports" / "live-e2e-suite" / "run"
    reports.mkdir(parents=True)
    (reports / "rest-api-smoke-result.json").write_text(
        '{"status":"failed","failed_phase":"nat_backend_order","error":"Timed out waiting for UPnP NAT backend order"}',
        encoding="utf-8",
    )
    recovery_inputs: list[str] = []

    class Completed:
        returncode = 1

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        assert allow_failure is True
        return Completed()

    def fake_recover(failure_text):
        recovery_inputs.append(failure_text)
        return {"requested": True}

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)
    monkeypatch.setattr(test_runs, "ensure_split_tunnel_apps", lambda paths: {"enabled": False})
    monkeypatch.setattr(test_runs, "restart_hide_me_after_upnp_failure_if_requested", fake_recover)

    with pytest.raises(RuntimeError, match="live E2E suite failed with exit code 1"):
        test_runs.invoke_live_e2e_suite(
            layout,
            WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
            LiveE2eOptions(suites=("rest-api",), test_network="vpn"),
        )

    assert len(recovery_inputs) == 1
    assert "nat_backend_order" in recovery_inputs[0]


def test_live_e2e_restarts_hide_me_when_app_log_points_at_upnp(tmp_path: Path, monkeypatch) -> None:
    logs = tmp_path / "workspaces" / "workspace" / "state" / "test-reports" / "live-e2e-suite" / "run" / "rest-api" / "logs"
    logs.mkdir(parents=True)
    (logs / "emulebb-verbose.log").write_text(
        "UPnP failed to setup port forwarding\nAdding PortMapping failed for port 9447 (TCP), Error Code 501\n",
        encoding="utf-8",
    )
    recovery_inputs: list[str] = []

    class Completed:
        returncode = 1

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        assert allow_failure is True
        return Completed()

    def fake_recover(failure_text):
        recovery_inputs.append(failure_text)
        return {"requested": True}

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)
    monkeypatch.setattr(test_runs, "ensure_split_tunnel_apps", lambda paths: {"enabled": False})
    monkeypatch.setattr(test_runs, "restart_hide_me_after_upnp_failure_if_requested", fake_recover)

    with pytest.raises(RuntimeError, match="live E2E suite failed with exit code 1"):
        test_runs.invoke_live_e2e_suite(
            layout,
            WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
            LiveE2eOptions(suites=("rest-api",), test_network="vpn"),
        )

    assert len(recovery_inputs) == 1
    assert "PortMapping failed" in recovery_inputs[0]


def test_live_e2e_forwards_multi_client_required_optional_clients(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("multi-client-p2p-matrix",),
            multi_client_require_optional_clients=True,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--multi-client-require-optional-clients" in command


def test_live_e2e_forwards_radarr_movie_root_only_when_configured(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("radarr-sonarr-emulebb",)),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--radarr-movie-root" not in command

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("radarr-sonarr-emulebb",), radarr_movie_root="/media/radarr-import-root"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--radarr-movie-root") == ["/media/radarr-import-root"]


def test_live_e2e_forwards_sonarr_series_root_only_when_configured(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("sonarr-emulebb",)),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--sonarr-series-root" not in command

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("sonarr-emulebb",), sonarr_series_root="/media/sonarr-import-root"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--sonarr-series-root") == ["/media/sonarr-import-root"]


def test_live_e2e_forwards_acquisition_timeout_only_when_configured(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("sonarr-emulebb",)),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--media-acquisition-timeout-minutes" not in command

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("sonarr-emulebb",), acquisition_timeout_minutes=90.0),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--media-acquisition-timeout-minutes") == ["90.0"]


def test_live_e2e_forwards_arr_download_proof_mode(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("radarr-emulebb",), arr_download_proof_mode="handoff"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--arr-download-proof-mode") == ["handoff"]


def test_live_e2e_forwards_profile_only_when_configured(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--profile" not in command

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="controller-surface"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["controller-surface"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="release-expanded"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["release-expanded"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="release-expanded-quick"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["release-expanded-quick"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="stabilization-stress"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["stabilization-stress"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="stabilization-stress-quick"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["stabilization-stress-quick"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="cpu-heavy"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["cpu-heavy"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="cpu-heavy-quick"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["cpu-heavy-quick"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="ui-resource-depth"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["ui-resource-depth"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="multi-client-p2p-required"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["multi-client-p2p-required"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="controller-local"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["controller-local"]

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="diagnostics-soak"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["diagnostics-soak"]


def test_live_e2e_runs_pre_run_cleanup_when_requested(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        calls.append("run")

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_pre_test_cleanup", lambda _layout: calls.append("cleanup"))
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(profile="release-expanded", pre_run_cleanup=True),
    )

    assert calls == ["cleanup", "run"]


def test_live_e2e_uses_workspace_state_defaults(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("disk-space-guard-live",)),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--workspace-root") == [str(layout.workspace_root)]
    assert "--artifacts-dir" not in command


def test_live_e2e_forwards_live_wire_inputs_file_only_when_configured(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("prowlarr-emulebb",)),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--live-wire-inputs-file" not in command

    live_wire_inputs_file = str(tmp_path / "repos" / "emulebb-build-tests" / "live-wire-inputs.local.json")
    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(suites=("prowlarr-emulebb",), live_wire_inputs_file=live_wire_inputs_file),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--live-wire-inputs-file") == [live_wire_inputs_file]


def test_live_e2e_resolves_existing_workspace_relative_live_wire_inputs_file(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    inputs_file = layout.tests_repo_root / "live-wire-inputs.local.json"
    inputs_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_live_e2e_suite(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        LiveE2eOptions(
            suites=("rest-api",),
            live_wire_inputs_file=r"repos\emulebb-build-tests\live-wire-inputs.local.json",
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--live-wire-inputs-file") == [str(inputs_file.resolve())]


def test_release_campaign_report_forwards_campaign_phase_and_json_options(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)
        captured["label"] = label
        captured["cwd"] = cwd
        captured["env"] = dict(env or {})

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_release_campaign_report(
        layout,
        ReleaseCampaignOptions(
            campaign="emulebb-0.7.3",
            phase="live-wire-release",
            json_output=True,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert captured["label"] == "release campaign report"
    assert option_values(command, "--campaign") == ["emulebb-0.7.3"]
    assert option_values(command, "--phase") == ["live-wire-release"]
    assert option_values(command, "--test-repo-root") == [str(layout.tests_repo_root)]
    assert option_values(command, "--workspace-state-root") == [str(layout.workspace_root / "state")]
    assert "--json" in command
    assert captured["env"] == {"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root}
