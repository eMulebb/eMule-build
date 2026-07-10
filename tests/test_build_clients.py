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


def test_build_clients_defaults_to_emulebb_rust(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bool, bool]] = []
    layout = make_layout(tmp_path)
    options = WorkspaceOptions(workspace_root=layout.emule_workspace_root)
    monkeypatch.setattr(
        build,
        "build_emulebb_rust_client",
        lambda _session, *, clean, diagnostics=False: calls.append((clean, diagnostics)),
    )

    build.build_clients(layout, options, BuildClientsOptions())

    assert calls == [(False, False)]


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
    staged_bin = layout.output_tools_root / "emulebb-rust" / "bin"
    staged_bin.mkdir(parents=True)
    (staged_bin / "emulebb-rust.exe").write_bytes(b"plain")

    def fake_run(command, *, cwd, stdout, stderr, text, check, env):
        commands.append(list(command))
        built = layout.output_rust_target_root / "x86_64-pc-windows-msvc" / "release"
        built.mkdir(parents=True)
        (built / "emulebb-rust-diagnostics.exe").write_bytes(b"diag")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build, "find_tool", lambda _names: cargo)
    monkeypatch.setattr(build.subprocess, "run", fake_run)
    session = build.BuildSession(
        layout=layout,
        options=WorkspaceOptions(workspace_root=layout.emule_workspace_root),
        command_name="build clients",
    )

    build.build_emulebb_rust_client(session, clean=False, diagnostics=True)

    assert "--bin" in commands[0]
    assert commands[0][commands[0].index("--bin") + 1] == "emulebb-rust-diagnostics"
    assert commands[0][-2:] == ["--features", "packet-diagnostics"]
    assert (staged_bin / "emulebb-rust.exe").read_bytes() == b"plain"
    assert (staged_bin / "emulebb-rust-diagnostics.exe").read_bytes() == b"diag"


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


def test_dynamic_qbittorrentbb_build_stages_runtime_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = make_layout(tmp_path)
    _prepare_qbittorrentbb_build_inputs(layout, tmp_path, monkeypatch)
    monkeypatch.setenv("EMULEBB_QT_PREFIX", str(tmp_path / "qt"))
    staged: list[dict[str, Path | list[Path]]] = []

    def fake_cmake_step(session, _command, *, log_name, step_name):
        if step_name == "CLIENT qBittorrentBB build":
            exe = session.layout.output_build_root / "qbittorrentbb" / session.options.configuration / "qbittorrent.exe"
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b"exe")

    def fake_stage_qbittorrentbb_runtime(**kwargs):
        staged.append(kwargs)

    monkeypatch.setattr(build, "_qbt_cmake_step", fake_cmake_step)
    monkeypatch.setattr(build, "stage_qbittorrentbb_runtime", fake_stage_qbittorrentbb_runtime)
    session = build.BuildSession(
        layout=layout,
        options=WorkspaceOptions(
            workspace_root=layout.emule_workspace_root,
            output_root=layout.output_root,
            configuration="Release",
        ),
        command_name="build clients",
    )

    build.build_qbittorrentbb_client(session, clean=False, static=False, stage="qbittorrent")

    exe = layout.output_build_root / "qbittorrentbb" / "Release" / "qbittorrent.exe"
    assert staged == [
        {
            "executable": exe,
            "target_root": exe.parent,
            "qt_prefix": tmp_path / "qt",
            "qbt_root": layout.resolve_workspace_path("repos/qbittorrentbb"),
            "search_dirs": [
                exe.parent,
                tmp_path / "qt" / "bin",
                layout.output_third_party_build_root / "deps" / "libtorrent" / "bin",
                layout.output_third_party_build_root / "emulebb-libtorrent" / "Release",
            ],
        }
    ]


def test_static_qbittorrentbb_build_does_not_stage_runtime_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = make_layout(tmp_path)
    _prepare_qbittorrentbb_build_inputs(layout, tmp_path, monkeypatch)
    staged: list[dict[str, object]] = []

    def fake_cmake_step(session, _command, *, log_name, step_name):
        if step_name == "CLIENT qBittorrentBB build":
            exe = session.layout.output_build_root / "qbittorrentbb" / session.options.configuration / "qbittorrent.exe"
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b"exe")

    monkeypatch.setattr(build, "_qbt_cmake_step", fake_cmake_step)
    monkeypatch.setattr(build, "stage_qbittorrentbb_runtime", lambda **kwargs: staged.append(kwargs))
    session = build.BuildSession(
        layout=layout,
        options=WorkspaceOptions(
            workspace_root=layout.emule_workspace_root,
            output_root=layout.output_root,
            configuration="Release",
        ),
        command_name="build qbittorrentbb-ci",
    )

    build.build_qbittorrentbb_client(session, clean=False, static=True, stage="qbittorrent")

    assert staged == []


def _prepare_qbittorrentbb_build_inputs(
    layout: WorkspaceLayout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout.resolve_workspace_path("repos/qbittorrentbb").mkdir(parents=True)
    layout.resolve_workspace_path("repos/third_party/emulebb-libtorrent").mkdir(parents=True)
    (layout.output_third_party_build_root / "deps" / "libtorrent").mkdir(parents=True)
    (tmp_path / "vcpkg.cmake").write_text("# toolchain\n", encoding="utf-8")
    monkeypatch.setattr(build, "_qbt_vcpkg_toolchain", lambda: tmp_path / "vcpkg.cmake")
    monkeypatch.setattr(build, "get_cmake_path", lambda: tmp_path / "cmake.exe")


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
