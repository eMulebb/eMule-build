from __future__ import annotations

import json
from pathlib import Path

import pytest

from emule_workspace import release_campaign_runner
from emule_workspace.config import ReleaseCampaignOptions, WorkspaceOptions
from emule_workspace.layout import AppVariant, TestTargets as LayoutTestTargets, WorkspaceLayout


def make_layout(tmp_path: Path) -> WorkspaceLayout:
    emule_workspace_root = tmp_path
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    tests_repo_root = emule_workspace_root / "repos" / "eMule-build-tests"
    app_root = workspace_root / "app" / "eMule-main"
    for path in (
        tests_repo_root / "manifests" / "release-campaigns",
        workspace_root / "state" / "test-reports",
        app_root,
        emule_workspace_root / "repos" / "eMule-build",
        emule_workspace_root / "repos" / "eMule-tooling" / "ci",
    ):
        path.mkdir(parents=True, exist_ok=True)
    return WorkspaceLayout(
        emule_workspace_root=emule_workspace_root,
        workspace_name="workspace",
        workspace_root=workspace_root,
        build_repo_root=emule_workspace_root / "repos" / "eMule-build",
        tests_repo_root=tests_repo_root,
        tooling_repo_root=emule_workspace_root / "repos" / "eMule-tooling",
        seed_repo_path=emule_workspace_root / "repos" / "eMule",
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

    reports = sorted((layout.workspace_root / "state" / "release-campaign-runs").glob("*/result.json"))
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

    reports = sorted((layout.workspace_root / "state" / "release-campaign-runs").glob("*/result.json"))
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
