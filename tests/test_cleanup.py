from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from emule_workspace import cleanup
from emule_workspace.cleanup import plan_cleanup
from emule_workspace.config import CleanupOptions


def test_routine_cleanup_selects_old_generated_artifacts(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    old_payload = write_file(layout.workspace_root / "state" / "test-reports" / "rest-api-smoke" / "20260501-run" / "temp" / "001.part", 10)
    recent_payload = write_file(layout.workspace_root / "state" / "test-reports" / "rest-api-smoke-latest" / "temp" / "001.part", 10)
    old_build_log = write_file(layout.workspace_root / "state" / "build-logs" / "20260401-120000" / "summary.json", 10)
    old_arr_output = write_file(layout.workspace_root / "state" / "arr-acquisition" / "radarr" / "movie.mkv", 10)
    old_live_artifact = write_file(layout.workspace_root / "state" / "test-artifacts" / "live-e2e-suite" / "20260501-120000-100-release" / "result.json", 10)
    recent_live_artifact = write_file(layout.workspace_root / "state" / "test-artifacts" / "live-e2e-suite" / "20260521-120000-100-release" / "result.json", 10)
    cache_file = write_file(layout.build_repo_root / ".pytest_cache" / "README.md", 10)
    release_rehearsal = write_file(layout.workspace_root / "state" / "release" / "emulebb-v1.0.1" / "package.zip", 10)
    for path in (old_payload, old_build_log, old_arr_output, old_live_artifact, cache_file, release_rehearsal):
        make_old(path, tmp_path)

    candidates = plan_cleanup(layout, CleanupOptions(report_run_retention_days=3650.0, keep_build_log_runs=0))
    candidate_paths = {candidate.path for candidate in candidates}
    categories = {candidate.category for candidate in candidates}

    assert old_payload.parent in candidate_paths
    assert recent_payload.parent not in candidate_paths
    assert old_build_log.parent in candidate_paths
    assert old_arr_output.parent in candidate_paths
    assert old_live_artifact.parent in candidate_paths
    assert recent_live_artifact.parent not in candidate_paths
    assert cache_file.parent in candidate_paths
    assert release_rehearsal.parent not in candidate_paths
    assert categories == {"arr-acquisition", "build-logs", "caches", "report-payload", "test-artifacts"}


def test_release_state_cleanup_is_explicit(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    current_release = write_file(layout.workspace_root / "state" / "release" / "emulebb-v0.7.3" / "package.zip", 10)
    rehearsal_release = write_file(layout.workspace_root / "state" / "release" / "emulebb-v1.0.1" / "package.zip", 10)

    candidates = plan_cleanup(layout, CleanupOptions(include_release_state=True))
    candidate_paths = {candidate.path for candidate in candidates}

    assert current_release.parent not in candidate_paths
    assert rehearsal_release.parent in candidate_paths


def test_package_build_outputs_are_explicit_build_output_cleanup(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    package_build_output = write_file(layout.workspace_root / "state" / "package-build" / "emulebb-v0.7.3" / "x64" / "app" / "emulebb.exe", 10)

    routine_candidates = plan_cleanup(layout, CleanupOptions())
    build_candidates = plan_cleanup(layout, CleanupOptions(include_build_outputs=True))

    assert package_build_output.parents[3] not in {candidate.path for candidate in routine_candidates}
    assert package_build_output.parents[3] in {candidate.path for candidate in build_candidates}


def test_delete_candidate_uses_windows_long_path_prefix(tmp_path: Path, monkeypatch) -> None:
    layout = make_layout(tmp_path)
    edge_path = layout.workspace_root / "state" / "test-reports" / "shared-directories-rest" / "20260501-run" / "shared-rest-exact-names. "
    candidate = cleanup.CleanupCandidate(edge_path, "directory", "report-run", "windows path edge case", 10, 1)
    removed_paths: list[str] = []

    monkeypatch.setattr(cleanup.os, "name", "nt")
    monkeypatch.setattr(cleanup.shutil, "rmtree", lambda path: removed_paths.append(path))

    cleanup._delete_candidate(candidate)

    assert removed_paths
    assert removed_paths[0].startswith("\\\\?\\")
    assert "shared-rest-exact-names. " in removed_paths[0]


def write_file(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def make_old(path: Path, stop: Path) -> None:
    old_timestamp = 1_700_000_000
    os.utime(path, (old_timestamp, old_timestamp))
    current = path.parent
    while current != stop.parent:
        os.utime(current, (old_timestamp, old_timestamp))
        current = current.parent


def make_layout(tmp_path: Path):
    workspace_root = tmp_path / "workspaces" / "workspace"
    return SimpleNamespace(
        emule_workspace_root=tmp_path,
        workspace_root=workspace_root,
        build_repo_root=tmp_path / "repos" / "eMule-build",
        tests_repo_root=tmp_path / "repos" / "eMule-build-tests",
        tooling_repo_root=tmp_path / "repos" / "eMule-tooling",
        app_variants=(),
        dependencies=(),
    )
