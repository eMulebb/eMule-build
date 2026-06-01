from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    return _repo_root().parents[1]


def _app_workflow(name: str) -> Path:
    return _workspace_root() / "workspaces" / "workspace" / "app" / "emulebb-main" / ".github" / "workflows" / name


def test_reusable_workspace_command_owns_materialized_ci_setup() -> None:
    workflow = _repo_root() / ".github" / "workflows" / "reusable-workspace-command.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "workflow_call:" in text
    assert "python -m emule_workspace materialize --workspace-root $env:EMULEBB_WORKSPACE_ROOT" in text
    assert "python -m pip install \"click>=8.1\" \"pydantic>=2.0\" \"jinja2>=3\" \"jsonschema>=4\"" in text
    assert "Reset-RepoRef" in text
    assert "repos\\amutorrent" in text
    assert "workspaces\\workspace\\app\\emulebb-main" in text


def test_reusable_workspace_command_keeps_hyperv_local_only() -> None:
    workflow = _repo_root() / ".github" / "workflows" / "reusable-workspace-command.yml"
    text = workflow.read_text(encoding="utf-8").lower()

    assert "hyper-v" not in text
    assert "hyperv" not in text
    assert "windows-vm" not in text


def test_build_baseline_uses_supported_reusable_inputs() -> None:
    workflow = _repo_root() / ".github" / "workflows" / "baseline.yml"
    text = workflow.read_text(encoding="utf-8")
    script = _repo_root() / ".github" / "scripts" / "baseline-extra.cmd"
    script_text = script.read_text(encoding="utf-8")

    assert "uses: emulebb/emulebb-tooling/.github/workflows/reusable-baseline.yml@main" in text
    assert "repo_kind: emulebb-build" in text
    assert "extra_commands:" not in text
    assert "extra_step_script: .github\\scripts\\baseline-extra.cmd" in text
    assert "python -m pip install -e .[dev]" in script_text
    assert "python -m pytest" in script_text


def test_controlled_smoke_uses_reusable_core_offline_and_lan_suite() -> None:
    workflow = _app_workflow("controlled-smoke.yml")
    text = workflow.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert 'cron: "47 5 * * *"' in text
    assert "uses: emulebb/emulebb-build/.github/workflows/reusable-workspace-command.yml@main" in text
    assert "runs_on: windows-2025-vs2026" in text
    assert "app_ref: ${{ github.sha }}" in text
    assert "timeout_minutes: 360" in text
    assert "python -m emule_workspace package-release" in text
    assert "python -m emule_workspace build app" in text
    assert "--variant tracing-harness" in text
    assert "--materialize-test-install" in text
    assert "--materialize-test-install-skip-build" in text
    assert "--suite command-line-smoke" in text
    assert "--test-network offline" in text
    assert "--suite deterministic-two-client-transfer" in text
    assert "--test-network lan" in text
    assert "workspaces/workspace/state/test-reports/live-e2e-suite/**" in text
    assert "workspaces/workspace/state/test-artifacts/live-e2e-suite/**" in text
    assert "workspaces/workspace/state/build-logs/**" in text


def test_controlled_smoke_keeps_first_lane_narrow() -> None:
    workflow = _app_workflow("controlled-smoke.yml")
    text = workflow.read_text(encoding="utf-8").lower()

    assert "--fixture-size-bytes" not in text
    assert "package-helper-integration" not in text
    assert "amutorrent-local-ed2k-ui-live" not in text
    assert "--test-network vpn" not in text
    assert "--test-network all" not in text
    assert "hyper-v" not in text
    assert "hyperv" not in text
    assert "windows-vm" not in text
