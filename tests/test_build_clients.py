from __future__ import annotations

import subprocess
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
    monkeypatch.setenv("EMULEBB_MSYS2_ROOT", str(root))

    assert build.resolve_msys2_root() == root.resolve()


def test_msys2_mingw64_environment_prefers_mingw_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "C:\\Windows\\System32")

    env = build.msys2_mingw64_environment(tmp_path / "msys64")

    assert env["MSYSTEM"] == "MINGW64"
    assert env["WINDOWS_MSYSTEM"] == "MINGW64"
    assert env["PATH"].startswith(str(tmp_path / "msys64" / "mingw64" / "bin"))


def test_msys2_mingw64_environment_forwards_workspace_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "C:\\Windows\\System32")
    layout = make_layout(tmp_path)

    env = build.msys2_mingw64_environment(tmp_path / "msys64", layout)

    assert env["EMULEBB_WORKSPACE_ROOT"] == str(layout.emule_workspace_root)
    assert env["EMULEBB_WORKSPACE_OUTPUT_ROOT"] == str(layout.output_root)
    assert env["CARGO_TARGET_DIR"] == str(layout.output_rust_target_root)


def test_build_amule_msys2_command_enters_repo_and_runs_windows_recipe(tmp_path: Path) -> None:
    repo = tmp_path / "repos" / "amule"

    command = build.build_amule_msys2_command(repo)

    assert "pacman -Q" in command
    assert "mingw-w64-x86_64-wxwidgets3.2-msw" in command
    assert "./packaging/windows/build.sh" in command
    assert build.windows_path_to_msys(repo) in command


def test_stage_amule_runtime_uses_output_root_portable_tree(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    daemon = build.amule_build_output_root(layout) / "amule-portable-x64" / "bin" / "amuled.exe"
    control = daemon.parent / "amulecmd.exe"
    for executable in (daemon, control):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b"")

    build.stage_amule_runtime(layout)

    assert (layout.output_tools_root / "amule" / "bin" / "amuled.exe").is_file()
    assert (layout.output_tools_root / "amule" / "bin" / "amulecmd.exe").is_file()


def test_build_clients_defaults_to_amule_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    layout = make_layout(tmp_path)
    options = WorkspaceOptions(workspace_root=layout.emule_workspace_root)
    monkeypatch.setattr(build, "build_amule_client", lambda _session, *, clean: calls.append(clean))

    build.build_clients(layout, options, BuildClientsOptions())

    assert calls == [False]


def test_build_clients_builds_emulebb_rust_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bool, bool]] = []
    layout = make_layout(tmp_path)
    options = WorkspaceOptions(workspace_root=layout.emule_workspace_root)
    monkeypatch.setattr(
        build,
        "build_emulebb_rust_client",
        lambda _session, *, clean, diagnostics=False: calls.append((clean, diagnostics)),
    )

    build.build_clients(layout, options, BuildClientsOptions(clients=("emulebb-rust",), clean=True))

    assert calls == [(True, False)]


def test_build_clients_passes_emulebb_rust_diagnostics_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[bool, bool]] = []
    layout = make_layout(tmp_path)
    options = WorkspaceOptions(workspace_root=layout.emule_workspace_root)
    monkeypatch.setattr(
        build,
        "build_emulebb_rust_client",
        lambda _session, *, clean, diagnostics=False: calls.append((clean, diagnostics)),
    )

    build.build_clients(
        layout,
        options,
        BuildClientsOptions(clients=("emulebb-rust",), clean=True, diagnostics=True),
    )

    assert calls == [(True, True)]


def test_build_emulebb_rust_client_runs_cargo_and_stages_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    repo_root = layout.emulebb_rust_repo_root
    assert repo_root is not None
    repo_root.mkdir(parents=True)
    cargo = tmp_path / "cargo.exe"
    cargo.write_bytes(b"")
    commands: list[tuple[list[str], Path, dict[str, str]]] = []

    def fake_run(command, *, cwd, stdout, stderr, text, check, env):
        commands.append((list(command), Path(cwd), dict(env)))
        built = layout.output_rust_target_root / "x86_64-pc-windows-msvc" / "release"
        built.mkdir(parents=True)
        (built / "emulebb-rust.exe").write_bytes(b"exe")
        (built / "emulebb-rust.pdb").write_bytes(b"pdb")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build, "find_tool", lambda _names: cargo)
    monkeypatch.setattr(build.subprocess, "run", fake_run)
    session = build.BuildSession(
        layout=layout,
        options=WorkspaceOptions(workspace_root=layout.emule_workspace_root),
        command_name="build clients",
    )

    build.build_emulebb_rust_client(session, clean=True)

    command, cwd, env = commands[0]
    assert cwd == repo_root
    assert command == [
        "cargo.exe",
        "build",
        "-p",
        "emulebb-daemon",
        "--bin",
        "emulebb-rust",
        "--release",
        "--target",
        "x86_64-pc-windows-msvc",
    ]
    assert env["EMULEBB_WORKSPACE_OUTPUT_ROOT"] == str(layout.output_root)
    assert env["CARGO_TARGET_DIR"] == str(layout.output_rust_target_root)
    assert (layout.output_tools_root / "emulebb-rust" / "bin" / "emulebb-rust.exe").read_bytes() == b"exe"
    assert (layout.output_tools_root / "emulebb-rust" / "bin" / "emulebb-rust.pdb").read_bytes() == b"pdb"


def test_build_emulebb_rust_client_can_enable_packet_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    repo_root = layout.emulebb_rust_repo_root
    assert repo_root is not None
    repo_root.mkdir(parents=True)
    cargo = tmp_path / "cargo.exe"
    cargo.write_bytes(b"")
    commands: list[list[str]] = []

    def fake_run(command, *, cwd, stdout, stderr, text, check, env):
        commands.append(list(command))
        built = layout.output_rust_target_root / "x86_64-pc-windows-msvc" / "release"
        built.mkdir(parents=True)
        (built / "emulebb-rust.exe").write_bytes(b"exe")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build, "find_tool", lambda _names: cargo)
    monkeypatch.setattr(build.subprocess, "run", fake_run)
    session = build.BuildSession(
        layout=layout,
        options=WorkspaceOptions(workspace_root=layout.emule_workspace_root),
        command_name="build clients",
    )

    build.build_emulebb_rust_client(session, clean=False, diagnostics=True)

    assert commands[0][-2:] == ["--features", "packet-diagnostics"]


def test_stage_emulebb_rust_runtime_requires_built_executable(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)

    with pytest.raises(RuntimeError, match="executable was not found"):
        build.stage_emulebb_rust_runtime(layout, "x86_64-pc-windows-msvc")


def test_rust_client_target_maps_workspace_platforms() -> None:
    assert build.rust_client_target("x64") == "x86_64-pc-windows-msvc"
    assert build.rust_client_target("ARM64") == "aarch64-pc-windows-msvc"


def test_build_clients_rejects_emuleai_target(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    options = WorkspaceOptions(workspace_root=layout.emule_workspace_root)

    with pytest.raises(ValueError):
        BuildClientsOptions(clients=("emuleai",))  # type: ignore[arg-type]


def make_layout(tmp_path: Path) -> WorkspaceLayout:
    emule_workspace_root = tmp_path / "workspace-root"
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    app_root = workspace_root / "app" / "emulebb-main"
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
        emulebb_rust_repo_root=emule_workspace_root / "repos" / "emulebb-rust",
        output_root=tmp_path / "workspace-output",
    )
