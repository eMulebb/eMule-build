from __future__ import annotations

from pathlib import Path

from emule_workspace.config import LiveE2eOptions, ReleaseCampaignOptions, WorkspaceOptions
from emule_workspace.layout import AppVariant, TestTargets as LayoutTestTargets, WorkspaceLayout
from emule_workspace import test_runs


def make_layout(tmp_path: Path) -> WorkspaceLayout:
    """Builds a minimal layout with the live E2E runner script present."""

    emule_workspace_root = tmp_path
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    tests_repo_root = emule_workspace_root / "repos" / "eMule-build-tests"
    app_root = workspace_root / "app" / "eMule-main"
    (tests_repo_root / "scripts").mkdir(parents=True)
    (tests_repo_root / "scripts" / "run-live-e2e-suite.py").write_text("# test runner\n", encoding="utf-8")
    (tests_repo_root / "scripts" / "show-release-campaigns.py").write_text("# campaign reporter\n", encoding="utf-8")
    app_root.mkdir(parents=True)
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


def option_values(command: list[str], option: str) -> list[str]:
    """Returns values that immediately follow an option in a captured command."""

    return [command[index + 1] for index, value in enumerate(command[:-1]) if value == option]


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
    assert captured["env"] == {"EMULE_WORKSPACE_ROOT": layout.emule_workspace_root}


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
        LiveE2eOptions(profile="stabilization-stress"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["stabilization-stress"]

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
        LiveE2eOptions(profile="ui-resource-depth"),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert option_values(command, "--profile") == ["ui-resource-depth"]


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

    live_wire_inputs_file = str(tmp_path / "repos" / "eMule-build-tests" / "live-wire-inputs.local.json")
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
            live_wire_inputs_file=r"repos\eMule-build-tests\live-wire-inputs.local.json",
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
            campaign="emule-bb-0.7.3",
            phase="live-wire-release",
            json_output=True,
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert captured["label"] == "release campaign report"
    assert option_values(command, "--campaign") == ["emule-bb-0.7.3"]
    assert option_values(command, "--phase") == ["live-wire-release"]
    assert option_values(command, "--test-repo-root") == [str(layout.tests_repo_root)]
    assert option_values(command, "--workspace-state-root") == [str(layout.workspace_root / "state")]
    assert "--json" in command
    assert captured["env"] == {"EMULE_WORKSPACE_ROOT": layout.emule_workspace_root}
