from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from emule_workspace import release_campaign_runner
from emule_workspace.artifact_names import release_campaign_result_file_name
from emule_workspace.config import ReleaseCampaignOptions, WorkspaceOptions
from emule_workspace.layout import AppVariant, TestTargets as LayoutTestTargets, WorkspaceLayout


def make_layout(tmp_path: Path) -> WorkspaceLayout:
    emule_workspace_root = tmp_path
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    tests_repo_root = emule_workspace_root / "repos" / "emulebb-build-tests"
    app_root = workspace_root / "app" / "emulebb-main"
    for path in (
        tests_repo_root / "manifests" / "release-campaigns",
        workspace_root / "state" / "test-reports",
        app_root,
        emule_workspace_root / "repos" / "emulebb-build",
        emule_workspace_root / "repos" / "emulebb-tooling" / "ci",
    ):
        path.mkdir(parents=True, exist_ok=True)
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


def write_campaign(layout: WorkspaceLayout, campaign: dict[str, object]) -> None:
    manifest_path = layout.tests_repo_root / "manifests" / "release-campaigns" / "test-campaign.json"
    manifest_path.write_text(json.dumps(campaign), encoding="utf-8")


def write_campaign_scenario_catalog(layout: WorkspaceLayout) -> None:
    module_dir = layout.tests_repo_root / "emule_test_harness"
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / "campaign_scenarios.py").write_text(
        """
from dataclasses import dataclass

@dataclass(frozen=True)
class Spec:
    key: str
    scenario_id: str
    local_profile: str
    local_suites: tuple[str, ...]
    vm_profile: str
    uses_local_swarm: bool = True

SPEC = Spec(
    key="search-ui-local-swarm",
    scenario_id="emulebb.flow.ui.search.local-swarm.v1",
    local_profile="multi-client-p2p",
    local_suites=("local-ed2k-search-soak", "local-kad-swarm"),
    vm_profile="search-ui-local-swarm-vm",
)
REUSABLE_CAMPAIGN_SCENARIO_BY_KEY = {SPEC.key: SPEC}
REUSABLE_CAMPAIGN_SCENARIO_BY_SCENARIO_ID = {SPEC.scenario_id: SPEC}
REUSABLE_CAMPAIGN_SCENARIO_BY_VM_PROFILE = {SPEC.vm_profile: SPEC}
LOCAL_SWARM_TIER_OPTIONS = {
    1: {
        "stage": "launch-scale",
        "total_client_count": 4,
        "peer_transfer_count": 24,
        "harness_transfer_count": 24,
        "emulebb_files": 80,
        "extra_emulebb_files": 8,
        "harness_files": 60,
        "amule_files": 20,
        "adverse_kill_cycles": 0,
        "adverse_kill_warmup_seconds": 0.0,
        "adverse_recovery_timeout_seconds": 180.0,
        "cpu_profile": False,
        "fail_fast": True,
    },
    2: {
        "stage": "launch-scale",
        "total_client_count": 12,
        "peer_transfer_count": 144,
        "harness_transfer_count": 144,
        "emulebb_files": 288,
        "extra_emulebb_files": 28,
        "harness_files": 216,
        "amule_files": 66,
        "adverse_kill_cycles": 1,
        "adverse_kill_warmup_seconds": 5.0,
        "adverse_recovery_timeout_seconds": 210.0,
        "cpu_profile": True,
        "fail_fast": False,
    },
    3: {
        "stage": "full",
        "total_client_count": 18,
        "peer_transfer_count": 360,
        "harness_transfer_count": 360,
        "emulebb_files": 720,
        "extra_emulebb_files": 72,
        "harness_files": 480,
        "amule_files": 120,
        "adverse_kill_cycles": 2,
        "adverse_kill_warmup_seconds": 20.0,
        "adverse_recovery_timeout_seconds": 180.0,
        "cpu_profile": True,
        "fail_fast": False,
    },
}
""".lstrip(),
        encoding="utf-8",
    )


def campaign_payload() -> dict[str, object]:
    return {
        "kind": "instance",
        "campaignId": "test-campaign",
        "releaseVersion": "0.0.0",
        "phases": [
            {
                "id": "preflight",
                "scenarios": [
                    {
                        "id": "validate",
                        "command": "python -m emule_workspace validate",
                        "blocking": True,
                    },
                    {
                        "id": "python",
                        "command": "python -m emule_workspace test python --quiet",
                        "blocking": True,
                    },
                ],
            },
            {
                "id": "controller-surface",
                "scenarios": [
                    {
                        "id": "rest",
                        "command": "python -m emule_workspace test live-e2e --profile controller-surface",
                        "blocking": True,
                    },
                    {
                        "id": "amutorrent",
                        "command": "python -m emule_workspace test live-e2e --profile controller-surface",
                        "blocking": True,
                    },
                ],
            },
            {
                "id": "stabilization-stress",
                "scenarios": [
                    {
                        "id": "optional",
                        "command": "python -m emule_workspace test certification --profile overnight",
                        "blocking": False,
                    },
                ],
            },
        ],
    }


def test_campaign_execution_plan_dedupes_shared_commands_and_skips_nonblocking() -> None:
    campaign = campaign_payload()

    plan = release_campaign_runner.build_release_campaign_execution_plan(
        campaign,
        ReleaseCampaignOptions(campaign="test-campaign", execute=True),
    )

    assert [item.command for item in plan] == [
        "python -m emule_workspace validate",
        "python -m emule_workspace test python --quiet",
        "python -m emule_workspace test live-e2e --profile controller-surface",
    ]
    assert plan[2].scenario_ids == ("amutorrent", "rest")


def test_campaign_execution_plan_can_include_nonblocking_optional_commands() -> None:
    plan = release_campaign_runner.build_release_campaign_execution_plan(
        campaign_payload(),
        ReleaseCampaignOptions(campaign="test-campaign", execute=True, include_nonblocking=True),
    )

    assert plan[-1].command == "python -m emule_workspace test certification --profile overnight"


def test_campaign_execute_dry_run_writes_planned_report(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    write_campaign(layout, campaign_payload())

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(campaign="test-campaign", execute=True, dry_run=True),
    )

    reports = sorted((layout.workspace_root / "state" / "release-campaign-runs").glob(f"*/{release_campaign_result_file_name()}"))
    assert reports
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["status"] == "planned"
    assert payload["options"]["localVmSwarmExecutionMode"] == "manifest"
    assert len(payload["plannedCommands"]) == 3
    assert all(row["status"] == "planned" for row in payload["commands"])


def test_campaign_execute_dispatches_supported_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    write_campaign(layout, campaign_payload())
    calls: list[str] = []

    monkeypatch.setattr(release_campaign_runner, "validate_workspace", lambda _layout: calls.append("validate"))
    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: calls.append("cleanup") or release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(release_campaign_runner, "invoke_python_tests", lambda _layout, _options: calls.append("python"))
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_live_e2e_suite",
        lambda _layout, _workspace_options, live_options: calls.append(f"live:{live_options.profile}"),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(campaign="test-campaign", execute=True),
    )

    assert calls == ["cleanup", "validate", "python", "live:controller-surface"]


def test_campaign_execute_forwards_live_e2e_suite_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    campaign = campaign_payload()
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "live-monitor",
            "command": (
                "python -m emule_workspace test live-e2e --suite live-process-monitor "
                "--multi-client-require-optional-clients --godzilla-stage launch-scale --fail-fast "
                "--materialize-test-install --materialize-test-install-release-version 0.7.4-rc.2 "
                "--materialize-test-install-clean --materialize-test-install-skip-build"
            ),
            "blocking": True,
        }
    ]
    write_campaign(layout, campaign)
    calls: list[tuple[str, tuple[str, ...], str, bool, str | None, bool, bool, str, bool, bool]] = []

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_live_e2e_suite",
        lambda _layout, _workspace_options, live_options: calls.append(
            (
                live_options.profile,
                live_options.suites,
                live_options.test_network,
                live_options.multi_client_require_optional_clients,
                live_options.godzilla_stage,
                live_options.fail_fast,
                live_options.materialize_test_install,
                live_options.materialize_test_install_release_version,
                live_options.materialize_test_install_clean,
                live_options.materialize_test_install_skip_build,
            )
        ),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(campaign="test-campaign", phase="controller-surface", execute=True),
    )

    assert calls == [
        ("default", ("live-process-monitor",), "default", True, "launch-scale", True, True, "0.7.4-rc.2", True, True)
    ]


def test_campaign_execute_applies_campaign_runtime_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    campaign = campaign_payload()
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "live",
            "command": "python -m emule_workspace test live-e2e --profile controller-surface",
            "blocking": True,
        },
        {
            "id": "cert",
            "command": "python -m emule_workspace test certification --profile overnight",
            "blocking": True,
        },
    ]
    write_campaign(layout, campaign)
    live_calls: list[tuple[str | None, str | None, str | None, float | None, str, bool, str]] = []
    certification_calls: list[tuple[str | None, str | None, str | None, float | None, str, bool, str]] = []

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_live_e2e_suite",
        lambda _layout, _workspace_options, options: live_calls.append(
            (
                options.live_wire_inputs_file,
                options.radarr_movie_root,
                options.sonarr_series_root,
                options.acquisition_timeout_minutes,
                options.p2p_bind_interface_name,
                options.skip_live_seed_refresh,
                options.test_network,
            )
        ),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_certification",
        lambda _layout, _workspace_options, options: certification_calls.append(
            (
                options.live_wire_inputs_file,
                options.radarr_movie_root,
                options.sonarr_series_root,
                options.acquisition_timeout_minutes,
                options.p2p_bind_interface_name,
                options.skip_live_seed_refresh,
                options.test_network,
            )
        ),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(
            campaign="test-campaign",
            phase="controller-surface",
            execute=True,
            live_wire_inputs_file="inputs.local.json",
            radarr_movie_root="R:/movies",
            sonarr_series_root="S:/series",
            acquisition_timeout_minutes=12.5,
            p2p_bind_interface_name="hide.me",
            skip_live_seed_refresh=True,
            test_network="all",
        ),
    )

    expected = [("inputs.local.json", "R:/movies", "S:/series", 12.5, "hide.me", True, "all")]
    assert live_calls == expected
    assert certification_calls == expected


def test_campaign_execute_dispatches_amutorrent_live_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    campaign = campaign_payload()
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "clean",
            "command": (
                "python -m emule_workspace test amutorrent-clean-startup "
                "--live-wire-inputs-file inputs.json --rest-webserver-scheme https --keep-artifacts"
            ),
            "blocking": True,
        },
        {
            "id": "ui",
            "command": (
                "python -m emule_workspace test amutorrent-emulebb-ui "
                "--live-wire-inputs-file inputs.json --rest-webserver-scheme https --keep-artifacts"
            ),
            "blocking": True,
        },
        {
            "id": "resilience",
            "command": (
                "python -m emule_workspace test amutorrent-resilience "
                "--live-wire-inputs-file inputs.json --rest-webserver-scheme https --keep-artifacts"
            ),
            "blocking": True,
        },
    ]
    write_campaign(layout, campaign)
    calls: list[tuple[str, str | None, str, bool, str]] = []

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_amutorrent_clean_startup",
        lambda _layout, _workspace_options, options: calls.append(
            ("clean", options.live_wire_inputs_file, options.rest_webserver_scheme, options.keep_artifacts, options.test_network)
        ),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_amutorrent_emulebb_ui",
        lambda _layout, _workspace_options, options: calls.append(
            ("ui", options.live_wire_inputs_file, options.rest_webserver_scheme, options.keep_artifacts, options.test_network)
        ),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_amutorrent_resilience",
        lambda _layout, _workspace_options, options: calls.append(
            ("resilience", options.live_wire_inputs_file, options.rest_webserver_scheme, options.keep_artifacts, options.test_network)
        ),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(campaign="test-campaign", phase="controller-surface", execute=True),
    )

    assert calls == [
        ("clean", "inputs.json", "https", True, "vpn"),
        ("ui", "inputs.json", "https", True, "vpn"),
        ("resilience", "inputs.json", "https", True, "vpn"),
    ]


def test_campaign_execute_dispatches_windows_vm_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    campaign = campaign_payload()
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "windows-vm",
            "command": (
                "python -m emule_workspace test windows-vm --matrix win10,win11 "
                "--profile hideme-live-wire --release-version 0.7.3-rc.1 --skip-build --keep-running "
                "--fixture-size-bytes 4096 --local-swarm-mode execute"
            ),
            "blocking": True,
        }
    ]
    write_campaign(layout, campaign)
    calls: list[tuple[tuple[str, ...], str, str, bool, bool, int, str]] = []

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_windows_vm_tests",
        lambda _layout, _workspace_options, options: calls.append(
            (
                options.matrix,
                options.profile,
                options.release_version,
                options.skip_build,
                options.keep_running,
                options.fixture_size_bytes,
                options.local_swarm_mode,
            )
        ),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(campaign="test-campaign", phase="controller-surface", execute=True),
    )

    assert calls == [(("win10", "win11"), "hideme-live-wire", "0.7.3-rc.1", True, True, 4096, "execute")]


def test_campaign_execute_dispatches_shared_campaign_scenario_local_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    campaign = campaign_payload()
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "shared-local",
            "command": (
                "python -m emule_workspace test campaign-scenario "
                "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode local --swarm-tier 1"
            ),
            "blocking": True,
        }
    ]
    write_campaign(layout, campaign)
    calls: list[tuple[str, tuple[str, ...], str]] = []

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_campaign_scenario",
        lambda _layout, _workspace_options, options: calls.append((options.scenario, (), options.mode)),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(campaign="test-campaign", phase="controller-surface", execute=True),
    )

    assert calls == [("emulebb.flow.ui.search.local-swarm.v1", (), "local")]


def test_campaign_execute_dispatches_shared_campaign_scenario_vm_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    campaign = campaign_payload()
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "shared-vm",
            "command": (
                "python -m emule_workspace test campaign-scenario "
                "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode vm "
                "--release-version 0.7.4-rc.2 --skip-build --dry-run --fixture-size-bytes 4096 "
                "--matrix win10 --swarm-tier 2 --local-swarm-mode execute"
            ),
            "blocking": True,
        }
    ]
    write_campaign(layout, campaign)
    calls: list[tuple[str, str, str, bool, bool, int, tuple[str, ...], int, str]] = []

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_campaign_scenario",
        lambda _layout, _workspace_options, options: calls.append(
            (
                options.scenario,
                options.mode,
                options.release_version,
                options.skip_build,
                options.dry_run,
                options.fixture_size_bytes,
                options.vm_matrix,
                options.swarm_tier,
                options.local_swarm_mode,
            )
        ),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(campaign="test-campaign", phase="controller-surface", execute=True),
    )

    assert calls == [("emulebb.flow.ui.search.local-swarm.v1", "vm", "0.7.4-rc.2", True, True, 4096, ("win10",), 2, "execute")]


def test_campaign_execute_can_override_shared_campaign_scenario_to_local_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    campaign = campaign_payload()
    local_command = (
        "python -m emule_workspace test campaign-scenario "
        "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode local --swarm-tier 1"
    )
    vm_command = (
        "python -m emule_workspace test campaign-scenario "
        "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode vm "
        "--release-version 0.7.4-rc.2 --skip-build --swarm-tier 2 --dry-run"
    )
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "shared-vm",
            "flowCategory": "local-vm-swarm",
            "command": vm_command,
            "localCommand": local_command,
            "vmCommand": vm_command,
            "executionMode": "vm",
            "blocking": True,
        }
    ]
    write_campaign(layout, campaign)
    calls: list[tuple[str, str, int]] = []

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_campaign_scenario",
        lambda _layout, _workspace_options, options: calls.append((options.scenario, options.mode, options.swarm_tier)),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(
            campaign="test-campaign",
            phase="controller-surface",
            execute=True,
            local_vm_swarm_mode="local",
        ),
    )

    assert calls == [("emulebb.flow.ui.search.local-swarm.v1", "local", 1)]


def test_campaign_execute_can_override_shared_campaign_scenario_to_vm_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    campaign = campaign_payload()
    local_command = (
        "python -m emule_workspace test campaign-scenario "
        "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode local --swarm-tier 1"
    )
    vm_command = (
        "python -m emule_workspace test campaign-scenario "
        "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode vm "
        "--release-version 0.7.4-rc.2 --skip-build --swarm-tier 2"
    )
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "shared-local",
            "flowCategory": "local-vm-swarm",
            "command": local_command,
            "localCommand": local_command,
            "vmCommand": vm_command,
            "executionMode": "local",
            "blocking": True,
        }
    ]
    write_campaign(layout, campaign)
    calls: list[tuple[str, str, str, bool, int, str]] = []

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_campaign_scenario",
        lambda _layout, _workspace_options, options: calls.append(
            (
                options.scenario,
                options.mode,
                options.release_version,
                options.skip_build,
                options.swarm_tier,
                options.local_swarm_mode,
            )
        ),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(
            campaign="test-campaign",
            phase="controller-surface",
            execute=True,
            local_vm_swarm_mode="vm",
        ),
    )

    assert calls == [("emulebb.flow.ui.search.local-swarm.v1", "vm", "0.7.4-rc.2", True, 2, "plan")]


def test_campaign_execute_can_force_shared_vm_campaign_scenario_to_execute_swarm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    campaign = campaign_payload()
    vm_command = (
        "python -m emule_workspace test campaign-scenario "
        "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode vm "
        "--release-version 0.7.4-rc.2 --skip-build --swarm-tier 2"
    )
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "shared-vm",
            "flowCategory": "local-vm-swarm",
            "command": vm_command,
            "localCommand": (
                "python -m emule_workspace test campaign-scenario "
                "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode local --swarm-tier 1"
            ),
            "vmCommand": vm_command,
            "executionMode": "vm",
            "blocking": True,
        }
    ]
    write_campaign(layout, campaign)
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {}),
    )
    monkeypatch.setattr(
        release_campaign_runner,
        "invoke_campaign_scenario",
        lambda _layout, _workspace_options, options: calls.append((options.local_swarm_mode, options.dry_run)),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(
            campaign="test-campaign",
            phase="controller-surface",
            execute=True,
            local_vm_swarm_mode="vm",
            local_vm_swarm_execution_mode="execute",
        ),
    )

    assert calls == [("execute", False)]


def test_campaign_plan_replaces_existing_shared_vm_swarm_execution_mode() -> None:
    campaign = campaign_payload()
    vm_command = (
        "python -m emule_workspace test campaign-scenario "
        "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode vm "
        "--release-version 0.7.4-rc.2 --skip-build --swarm-tier 2 --local-swarm-mode plan"
    )
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "shared-vm",
            "flowCategory": "local-vm-swarm",
            "command": vm_command,
            "localCommand": (
                "python -m emule_workspace test campaign-scenario "
                "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode local --swarm-tier 1"
            ),
            "vmCommand": vm_command,
            "executionMode": "vm",
            "blocking": True,
        }
    ]

    plan = release_campaign_runner.build_release_campaign_execution_plan(
        campaign,
        ReleaseCampaignOptions(
            campaign="test-campaign",
            phase="controller-surface",
            execute=True,
            local_vm_swarm_execution_mode="execute",
        ),
    )

    assert len(plan) == 1
    assert "--local-swarm-mode execute" in plan[0].command
    assert "--local-swarm-mode plan" not in plan[0].command
    assert "--dry-run" not in plan[0].command


def test_campaign_plan_forces_shared_vm_swarm_plan_to_dry_run() -> None:
    campaign = campaign_payload()
    vm_command = (
        "python -m emule_workspace test campaign-scenario "
        "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode vm "
        "--release-version 0.7.4-rc.2 --skip-build --swarm-tier 2 --local-swarm-mode execute"
    )
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "shared-vm",
            "flowCategory": "local-vm-swarm",
            "command": vm_command,
            "localCommand": (
                "python -m emule_workspace test campaign-scenario "
                "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode local --swarm-tier 1"
            ),
            "vmCommand": vm_command,
            "executionMode": "vm",
            "blocking": True,
        }
    ]

    plan = release_campaign_runner.build_release_campaign_execution_plan(
        campaign,
        ReleaseCampaignOptions(
            campaign="test-campaign",
            phase="controller-surface",
            execute=True,
            local_vm_swarm_execution_mode="plan",
        ),
    )

    assert len(plan) == 1
    assert "--dry-run" in plan[0].command
    assert "--local-swarm-mode execute" not in plan[0].command


def test_campaign_plan_rejects_missing_local_vm_swarm_local_override_command() -> None:
    campaign = campaign_payload()
    vm_command = (
        "python -m emule_workspace test campaign-scenario "
        "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode vm "
        "--release-version 0.7.4-rc.2 --skip-build --swarm-tier 2"
    )
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "shared-vm",
            "flowCategory": "local-vm-swarm",
            "command": vm_command,
            "vmCommand": vm_command,
            "executionMode": "vm",
            "blocking": True,
        }
    ]

    with pytest.raises(ValueError, match="shared-vm.*missing localCommand"):
        release_campaign_runner.build_release_campaign_execution_plan(
            campaign,
            ReleaseCampaignOptions(
                campaign="test-campaign",
                phase="controller-surface",
                execute=True,
                local_vm_swarm_mode="local",
            ),
        )


def test_campaign_plan_rejects_missing_local_vm_swarm_vm_override_command() -> None:
    campaign = campaign_payload()
    local_command = (
        "python -m emule_workspace test campaign-scenario "
        "--scenario emulebb.flow.ui.search.local-swarm.v1 --mode local --swarm-tier 1"
    )
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "shared-local",
            "flowCategory": "local-vm-swarm",
            "command": local_command,
            "localCommand": local_command,
            "executionMode": "local",
            "blocking": True,
        }
    ]

    with pytest.raises(ValueError, match="shared-local.*missing vmCommand"):
        release_campaign_runner.build_release_campaign_execution_plan(
            campaign,
            ReleaseCampaignOptions(
                campaign="test-campaign",
                phase="controller-surface",
                execute=True,
                local_vm_swarm_mode="vm",
            ),
        )


def test_campaign_execute_records_pre_run_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    write_campaign(layout, campaign_payload())

    monkeypatch.setattr(
        release_campaign_runner,
        "run_pre_test_cleanup",
        lambda _layout: release_campaign_runner.CleanupRunSummary(
            "routine",
            True,
            "passed",
            2,
            128,
            4,
            {"report-run": {"items": 2, "files": 4, "bytes": 128}},
        ),
    )
    monkeypatch.setattr(release_campaign_runner, "_dispatch_supported_command", lambda *_args: None)

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(campaign="test-campaign", execute=True),
    )

    reports = sorted((layout.workspace_root / "state" / "release-campaign-runs").glob(f"*/{release_campaign_result_file_name()}"))
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["options"]["preRunCleanup"] is True
    assert payload["preRunCleanup"]["status"] == "passed"
    assert payload["preRunCleanup"]["categories"]["report-run"]["items"] == 2


def test_campaign_execution_rejects_shell_commands() -> None:
    campaign = campaign_payload()
    campaign["phases"][0]["scenarios"][0]["command"] = "cmd /c echo nope"  # type: ignore[index]

    with pytest.raises(ValueError, match="Unsupported release campaign command"):
        release_campaign_runner.build_release_campaign_execution_plan(
            campaign,
            ReleaseCampaignOptions(campaign="test-campaign", execute=True),
        )


def test_campaign_execution_rejects_unsupported_emule_workspace_command() -> None:
    campaign = campaign_payload()
    campaign["phases"][0]["scenarios"][0]["command"] = "python -m emule_workspace test nope"  # type: ignore[index]

    with pytest.raises(ValueError, match="Unsupported emule_workspace release campaign command"):
        release_campaign_runner.build_release_campaign_execution_plan(
            campaign,
            ReleaseCampaignOptions(campaign="test-campaign", execute=True),
        )


def test_campaign_execution_rejects_unsupported_emule_workspace_option() -> None:
    campaign = campaign_payload()
    campaign["phases"][1]["scenarios"][0]["command"] = (
        "python -m emule_workspace test live-e2e --profile controller-surface --unknown"
    )

    with pytest.raises(ValueError, match="Unsupported release campaign option"):
        release_campaign_runner.build_release_campaign_execution_plan(
            campaign,
            ReleaseCampaignOptions(campaign="test-campaign", execute=True),
        )


def fake_live_e2e_suite_module():
    specs = {
        "rest-api": SimpleNamespace(name="rest-api", category="rest", network_scope="vpn"),
    }

    def resolve_suite_specs(names):
        return tuple(specs[name] for name in names)

    def filter_suite_specs_for_network(resolved_specs, test_network):
        if test_network in {"vpn", "all"}:
            return tuple(resolved_specs), []
        return (), [
            {
                "name": spec.name,
                "category": spec.category,
                "network_scope": spec.network_scope,
                "reason": f"excluded by test_network={test_network}",
            }
            for spec in resolved_specs
        ]

    return SimpleNamespace(
        PROFILE_SUITE_NAMES={"controller-surface": ("rest-api",)},
        resolve_suite_specs=resolve_suite_specs,
        filter_suite_specs_for_network=filter_suite_specs_for_network,
    )


def live_e2e_requirement_campaign() -> dict[str, object]:
    campaign = campaign_payload()
    campaign["phases"][1]["scenarios"] = [
        {
            "id": "rest",
            "command": "python -m emule_workspace test live-e2e --profile controller-surface",
            "blocking": True,
            "liveE2eProfile": "controller-surface",
            "liveE2eSuite": "rest-api",
        }
    ]
    return campaign


def test_campaign_dry_run_fails_required_live_suite_skipped_by_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = make_layout(tmp_path)
    write_campaign(layout, live_e2e_requirement_campaign())
    monkeypatch.setattr(
        release_campaign_runner,
        "_load_live_e2e_suite_module",
        lambda _layout: fake_live_e2e_suite_module(),
    )

    with pytest.raises(release_campaign_runner.ReleaseCampaignExecutionError, match="required live E2E suite"):
        release_campaign_runner.invoke_release_campaign(
            layout,
            WorkspaceOptions(workspace_root=tmp_path),
            ReleaseCampaignOptions(campaign="test-campaign", phase="controller-surface", execute=True, dry_run=True),
        )

    reports = sorted((layout.workspace_root / "state" / "release-campaign-runs").glob(f"*/{release_campaign_result_file_name()}"))
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert "required live E2E suite(s) skipped" in payload["commands"][0]["error"]


def test_campaign_dry_run_accepts_required_live_suite_with_vpn_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = make_layout(tmp_path)
    write_campaign(layout, live_e2e_requirement_campaign())
    monkeypatch.setattr(
        release_campaign_runner,
        "_load_live_e2e_suite_module",
        lambda _layout: fake_live_e2e_suite_module(),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(
            campaign="test-campaign",
            phase="controller-surface",
            execute=True,
            dry_run=True,
            test_network="vpn",
        ),
    )

    reports = sorted((layout.workspace_root / "state" / "release-campaign-runs").glob(f"*/{release_campaign_result_file_name()}"))
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["status"] == "planned"
    assert payload["commands"][0]["status"] == "planned"
