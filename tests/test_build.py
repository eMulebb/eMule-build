from __future__ import annotations

from pathlib import Path

import pytest

from emule_workspace import build
from emule_workspace.config import WorkspaceOptions
from emule_workspace.layout import TestTargets as LayoutTestTargets, WorkspaceLayout


def test_build_libs_passes_default_toolset_to_msbuild_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = capture_build_libs_msbuild_calls(tmp_path, monkeypatch)

    assert captured
    for call in captured:
        assert "/p:PlatformToolset=v143" in call["extra_properties"]


def test_build_libs_honors_toolset_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMULEBB_VS_PLATFORM_TOOLSET", "v145")

    captured = capture_build_libs_msbuild_calls(tmp_path, monkeypatch)

    assert captured
    for call in captured:
        assert "/p:PlatformToolset=v145" in call["extra_properties"]
        assert "/p:PlatformToolset=v143" not in call["extra_properties"]


def test_build_libs_clean_release_x64_removes_generated_dependency_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[tuple[Path, str]] = []

    capture_build_libs_msbuild_calls(tmp_path, monkeypatch, clean=True, removed_generated=removed)

    assert [kind for _repo, kind in removed] == ["zlib", "mbedtls"]


def capture_build_libs_msbuild_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    clean: bool = False,
    removed_generated: list[tuple[Path, str]] | None = None,
) -> list[dict[str, object]]:
    layout = make_layout(tmp_path)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(build, "get_cmake_path", lambda: Path("cmake.exe"))
    monkeypatch.setattr(build, "get_perl_path", lambda: Path("perl.exe"))
    monkeypatch.setattr(build, "invoke_cmake_dependency_build", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build, "ensure_arm64_override_targets", lambda _layout: None)
    if removed_generated is not None:
        monkeypatch.setattr(
            build,
            "remove_stale_generated_artifacts",
            lambda repo_path, kind: removed_generated.append((repo_path, kind)),
        )

    def fake_invoke_msbuild_project(*_args, **kwargs):
        calls.append(
            {
                "project_path": kwargs["project_path"],
                "extra_properties": tuple(kwargs.get("extra_properties") or ()),
                "step_name": kwargs["step_name"],
            }
        )

    monkeypatch.setattr(build, "invoke_msbuild_project", fake_invoke_msbuild_project)

    build.build_libs(
        layout,
        WorkspaceOptions(workspace_root=layout.emule_workspace_root, configuration="Release", platform="x64"),
        clean=clean,
    )

    return calls


def make_layout(tmp_path: Path) -> WorkspaceLayout:
    emule_workspace_root = tmp_path / "workspace-root"
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    return WorkspaceLayout(
        emule_workspace_root=emule_workspace_root,
        workspace_name="workspace",
        workspace_root=workspace_root,
        build_repo_root=emule_workspace_root / "repos" / "emulebb-build",
        tests_repo_root=emule_workspace_root / "repos" / "emulebb-build-tests",
        tooling_repo_root=emule_workspace_root / "repos" / "emulebb-tooling",
        ed2k_server_repo_root=emule_workspace_root / "repos" / "goed2k-server",
        amule_repo_root=emule_workspace_root / "repos" / "amule",
        seed_repo_path=emule_workspace_root / "repos" / "emulebb",
        seed_repo_branch="main",
        dependencies=(),
        app_variants=(),
        test_targets=LayoutTestTargets(test_build_variant="main", test_run_variant="main", baseline_variant="community"),
        toolset_override_variable="EMULEBB_VS_PLATFORM_TOOLSET",
    )
