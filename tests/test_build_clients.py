from __future__ import annotations

from pathlib import Path

import pytest

from emule_workspace import build
from emule_workspace.config import BuildClientsOptions, WorkspaceOptions
from emule_workspace.layout import TestTargets as LayoutTestTargets, WorkspaceLayout


def test_resolve_msys2_root_honors_explicit_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "msys64"
    bash = root / "usr" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_bytes(b"")
    monkeypatch.setenv("EMULE_MSYS2_ROOT", str(root))

    assert build.resolve_msys2_root() == root.resolve()


def test_msys2_mingw64_environment_prefers_mingw_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "C:\\Windows\\System32")

    env = build.msys2_mingw64_environment(tmp_path / "msys64")

    assert env["MSYSTEM"] == "MINGW64"
    assert env["WINDOWS_MSYSTEM"] == "MINGW64"
    assert env["PATH"].startswith(str(tmp_path / "msys64" / "mingw64" / "bin"))


def test_build_amule_msys2_command_enters_repo_and_runs_windows_recipe(tmp_path: Path) -> None:
    repo = tmp_path / "repos" / "amule"

    command = build.build_amule_msys2_command(repo)

    assert "pacman -Q" in command
    assert "mingw-w64-x86_64-wxwidgets3.2-msw" in command
    assert "./packaging/windows/build.sh" in command
    assert build.windows_path_to_msys(repo) in command


def test_build_clients_defaults_to_amule_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    layout = make_layout(tmp_path)
    options = WorkspaceOptions(workspace_root=layout.emule_workspace_root)
    monkeypatch.setattr(build, "build_amule_client", lambda _session, *, clean: calls.append(clean))

    build.build_clients(layout, options, BuildClientsOptions())

    assert calls == [False]


def test_build_clients_rejects_emuleai_target(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    options = WorkspaceOptions(workspace_root=layout.emule_workspace_root)

    with pytest.raises(ValueError):
        BuildClientsOptions(clients=("emuleai",))  # type: ignore[arg-type]


def make_layout(tmp_path: Path) -> WorkspaceLayout:
    emule_workspace_root = tmp_path / "workspace-root"
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    app_root = workspace_root / "app" / "eMule-main"
    return WorkspaceLayout(
        emule_workspace_root=emule_workspace_root,
        workspace_name="workspace",
        workspace_root=workspace_root,
        build_repo_root=emule_workspace_root / "repos" / "eMule-build",
        tests_repo_root=emule_workspace_root / "repos" / "eMule-build-tests",
        tooling_repo_root=emule_workspace_root / "repos" / "eMule-tooling",
        ed2k_server_repo_root=emule_workspace_root / "repos" / "goed2k-server",
        amule_repo_root=emule_workspace_root / "repos" / "amule",
        seed_repo_path=emule_workspace_root / "repos" / "eMule",
        seed_repo_branch="main",
        dependencies=(),
        app_variants=(),
        test_targets=LayoutTestTargets(test_build_variant="main", test_run_variant="main", baseline_variant="community"),
        toolset_override_variable="EMULE_V072_PLATFORM_TOOLSET",
    )
