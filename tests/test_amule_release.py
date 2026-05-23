from __future__ import annotations

from pathlib import Path

import pytest

from emule_workspace import amule_release
from emule_workspace.config import AmulePackageOptions, WorkspaceOptions
from emule_workspace.process import PythonInvocation


class FakeLayout:
    def __init__(self, root: Path) -> None:
        self.workspace_root = root / "workspaces" / "workspace"
        self.amule_root = root / "repos" / "amule"
        self.workspace_root.mkdir(parents=True)
        (self.amule_root / "tools").mkdir(parents=True)
        (self.amule_root / "tools" / "package_windows.py").write_text("# test\n", encoding="utf-8")

    def resolve_workspace_path(self, relative_path: str) -> Path:
        assert relative_path == "repos/amule"
        return self.amule_root


def test_package_amule_invokes_repo_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = FakeLayout(tmp_path)
    calls: list[tuple[list[str], Path]] = []
    msys2_root = tmp_path / "msys64"
    (msys2_root / "usr" / "bin").mkdir(parents=True)
    (msys2_root / "usr" / "bin" / "bash.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(amule_release, "resolve_msys2_root", lambda: msys2_root)
    monkeypatch.setattr(amule_release, "get_python_invocation", lambda: PythonInvocation(Path("python")))
    monkeypatch.setattr(
        amule_release,
        "run_native",
        lambda command, *, label, cwd: calls.append(([str(part) for part in command], cwd)),
    )

    amule_release.create_amule_package(
        layout,  # type: ignore[arg-type]
        WorkspaceOptions(workspace_root=tmp_path, configuration="Release", platform="x64"),
        AmulePackageOptions(release_version="3.0.0-emulebb.1", clean=True),
    )

    assert calls
    command, cwd = calls[0]
    assert cwd == layout.amule_root
    assert str(layout.amule_root / "tools" / "package_windows.py") in command
    assert "--platform" in command
    assert "x64" in command
    assert "--require-clean" in command
    assert "--clean" in command
    assert str(layout.workspace_root / "state" / "release" / "amule-3.0.0-emulebb.1") in command
    assert str(msys2_root) in command


def test_package_amule_rejects_debug_config(tmp_path: Path) -> None:
    layout = FakeLayout(tmp_path)

    with pytest.raises(RuntimeError, match="requires --config Release"):
        amule_release.create_amule_package(
            layout,  # type: ignore[arg-type]
            WorkspaceOptions(workspace_root=tmp_path, configuration="Debug", platform="x64"),
            AmulePackageOptions(),
        )


def test_package_amule_rejects_non_emulebb_version(tmp_path: Path) -> None:
    layout = FakeLayout(tmp_path)

    with pytest.raises(RuntimeError, match="MAJOR.MINOR.PATCH-emulebb.N"):
        amule_release.create_amule_package(
            layout,  # type: ignore[arg-type]
            WorkspaceOptions(workspace_root=tmp_path, configuration="Release", platform="x64"),
            AmulePackageOptions(release_version="3.0.0"),
        )
