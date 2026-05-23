from __future__ import annotations

import json
from pathlib import Path

import pytest

from emule_workspace import certification
from emule_workspace.config import CertificationOptions, WorkspaceOptions
from emule_workspace.layout import AppVariant, TestTargets as LayoutTestTargets, WorkspaceLayout


def make_layout(tmp_path: Path) -> WorkspaceLayout:
    emule_workspace_root = tmp_path
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    tests_repo_root = emule_workspace_root / "repos" / "emulebb-build-tests"
    app_root = workspace_root / "app" / "eMule-main"
    for path in (
        workspace_root / "state" / "test-reports",
        app_root,
        emule_workspace_root / "repos" / "emulebb-build",
        emule_workspace_root / "repos" / "emulebb-tooling",
    ):
        path.mkdir(parents=True)
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


def latest_certification_report(layout: WorkspaceLayout) -> Path:
    reports = sorted((layout.workspace_root / "state" / "certification").glob("*/result.json"))
    assert reports
    return reports[-1]


def test_certification_step_plan_is_two_tier() -> None:
    fast = certification.get_certification_step_plan("fast")
    overnight = certification.get_certification_step_plan("overnight")

    assert [step.name for step in fast] == [
        "validate",
        "build-app-debug-x64",
        "build-app-release-x64",
        "build-app-release-arm64",
        "build-tests-debug-x64",
        "build-tests-release-x64",
        "python-harness",
        "test-all-debug-x64",
        "test-all-release-x64",
        "live-fast-ui-rest",
    ]
    assert [step.name for step in overnight[: len(fast)]] == [step.name for step in fast]
    assert "protocol-parity" in [step.name for step in overnight]
    assert "community-core-coverage" in [step.name for step in overnight]
    assert "live-stabilization-stress" in [step.name for step in overnight]
    assert "live-release-expanded" in [step.name for step in overnight]
    assert "live-ui-resource-depth" in [step.name for step in overnight]
    assert "amutorrent-clean-startup" in [step.name for step in overnight]
    assert "amutorrent-emulebb-ui" in [step.name for step in overnight]
    assert "amutorrent-resilience" in [step.name for step in overnight]


def test_certification_writes_single_passing_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    calls: list[str] = []

    def fake_invoke_step(_layout, _options, _certification_options, name):
        calls.append(name)

    monkeypatch.setattr(certification, "_invoke_step", fake_invoke_step)

    certification.invoke_certification(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        CertificationOptions(profile="fast"),
    )

    report = json.loads(latest_certification_report(layout).read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["profile"] == "fast"
    assert calls == [step.name for step in certification.get_certification_step_plan("fast")]
    assert [step["status"] for step in report["steps"]] == ["passed"] * len(calls)
    assert report["options"]["pre_run_cleanup"] is True
    assert report["pre_run_cleanup"]["status"] == "passed"


def test_certification_records_pre_run_cleanup_before_first_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    calls: list[str] = []

    def fake_cleanup(_layout):
        calls.append("cleanup")
        return certification.CleanupRunSummary("routine", True, "passed", 0, 0, 0, {})

    def fake_invoke_step(_layout, _options, _certification_options, name):
        calls.append(name)

    monkeypatch.setattr(certification, "run_pre_test_cleanup", fake_cleanup)
    monkeypatch.setattr(certification, "_invoke_step", fake_invoke_step)

    certification.invoke_certification(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        CertificationOptions(profile="fast"),
    )

    assert calls[0] == "cleanup"
    assert calls[1:] == [step.name for step in certification.get_certification_step_plan("fast")]


def test_certification_records_failed_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    calls: list[str] = []

    def fake_invoke_step(_layout, _options, _certification_options, name):
        calls.append(name)
        if name == "build-tests-release-x64":
            raise RuntimeError("native test build failed")

    monkeypatch.setattr(certification, "_invoke_step", fake_invoke_step)

    with pytest.raises(RuntimeError, match="build-tests-release-x64"):
        certification.invoke_certification(
            layout,
            WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
            CertificationOptions(profile="fast"),
        )

    report = json.loads(latest_certification_report(layout).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    failed = [step for step in report["steps"] if step["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["name"] == "build-tests-release-x64"
    assert failed[0]["error"] == "native test build failed"
    assert calls[-1] == "build-tests-release-x64"


def test_certification_can_continue_after_failed_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    calls: list[str] = []

    def fake_invoke_step(_layout, _options, _certification_options, name):
        calls.append(name)
        if name == "build-tests-release-x64":
            raise RuntimeError("native test build failed")

    monkeypatch.setattr(certification, "_invoke_step", fake_invoke_step)

    with pytest.raises(RuntimeError, match="completed with status failed"):
        certification.invoke_certification(
            layout,
            WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
            CertificationOptions(profile="fast", continue_on_failure=True),
        )

    expected = [step.name for step in certification.get_certification_step_plan("fast")]
    report = json.loads(latest_certification_report(layout).read_text(encoding="utf-8"))
    assert calls == expected
    assert report["status"] == "failed"
    assert report["options"]["continue_on_failure"] is True
    assert report["steps"][-1]["name"] == "live-fast-ui-rest"
    assert [step["name"] for step in report["steps"]] == expected


def test_certification_preserves_inconclusive_child_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)

    def fake_invoke_step(_layout, _options, _certification_options, name):
        if name == "live-fast-ui-rest":
            child_report = layout.workspace_root / "state" / "test-reports" / "live-e2e-suite-latest"
            child_report.mkdir(parents=True)
            (child_report / "result.json").write_text(
                json.dumps({"status": "inconclusive", "has_inconclusive_suites": True}) + "\n",
                encoding="utf-8",
            )
            raise RuntimeError("live network evidence was inconclusive")

    monkeypatch.setattr(certification, "_invoke_step", fake_invoke_step)

    with pytest.raises(RuntimeError, match="live-fast-ui-rest"):
        certification.invoke_certification(
            layout,
            WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
            CertificationOptions(profile="fast"),
        )

    report = json.loads(latest_certification_report(layout).read_text(encoding="utf-8"))
    assert report["status"] == "inconclusive"
    assert report["steps"][-1]["name"] == "live-fast-ui-rest"
    assert report["steps"][-1]["status"] == "inconclusive"


def test_fast_live_step_uses_critical_ui_and_rest_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    captured: dict[str, object] = {}

    def fake_live_e2e(_layout, _options, live_options):
        captured["live_options"] = live_options

    monkeypatch.setattr(certification, "invoke_live_e2e_suite", fake_live_e2e)

    certification._invoke_step(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        CertificationOptions(profile="fast", live_wire_inputs_file="inputs.json"),
        "live-fast-ui-rest",
    )

    live_options = captured["live_options"]
    assert live_options.suites == (
        "preference-ui",
        "shared-files-ui",
        "config-stability-ui",
        "shared-hash-ui",
        "startup-profile",
        "shared-directories-rest",
        "rest-api",
    )
    assert live_options.fail_fast is True
    assert live_options.live_wire_inputs_file == "inputs.json"


def test_overnight_stress_step_enables_cpu_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    captured: dict[str, object] = {}

    def fake_live_e2e(_layout, _options, live_options):
        captured["live_options"] = live_options

    monkeypatch.setattr(certification, "invoke_live_e2e_suite", fake_live_e2e)

    certification._invoke_step(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        CertificationOptions(profile="overnight"),
        "live-stabilization-stress",
    )

    live_options = captured["live_options"]
    assert live_options.profile == "stabilization-stress"
    assert live_options.fail_fast is True
    assert live_options.profile_cpu is True
    assert live_options.profile_cpu_stack is True
    assert live_options.profile_memory is True
    assert live_options.rest_cold_start_dump_stress_cpu_profile is True
    assert live_options.rest_cold_start_dump_stress_cpu_profile_stack is True


def test_overnight_release_steps_use_broad_live_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = make_layout(tmp_path)
    captured: list[object] = []

    def fake_live_e2e(_layout, _options, live_options):
        captured.append(live_options)

    monkeypatch.setattr(certification, "invoke_live_e2e_suite", fake_live_e2e)

    for step_name in ("live-release-expanded", "live-ui-resource-depth"):
        certification._invoke_step(
            layout,
            WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
            CertificationOptions(profile="overnight"),
            step_name,
        )

    assert [item.profile for item in captured] == ["release-expanded", "ui-resource-depth"]
    assert [item.fail_fast for item in captured] == [True, True]
    assert [item.pre_run_cleanup for item in captured] == [False, False]
    assert captured[0].profile_cpu is True
    assert captured[0].profile_cpu_stack is True
    assert captured[0].profile_memory is True
    assert captured[0].admin_volume_fixtures is True
    assert captured[1].profile_cpu is False
    assert captured[1].profile_memory is False
