from __future__ import annotations

import json
from pathlib import Path

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
                "--multi-client-require-optional-clients --godzilla-stage launch-scale --fail-fast"
            ),
            "blocking": True,
        }
    ]
    write_campaign(layout, campaign)
    calls: list[tuple[str, tuple[str, ...], str, bool, str | None, bool]] = []

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
            )
        ),
    )

    release_campaign_runner.invoke_release_campaign(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        ReleaseCampaignOptions(campaign="test-campaign", phase="controller-surface", execute=True),
    )

    assert calls == [("default", ("live-process-monitor",), "default", True, "launch-scale", True)]


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
