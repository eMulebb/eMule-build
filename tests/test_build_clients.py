from __future__ import annotations

from pathlib import Path

import pytest

from emule_workspace import build


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
