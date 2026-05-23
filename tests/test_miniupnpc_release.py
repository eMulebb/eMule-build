from __future__ import annotations

from pathlib import Path

import pytest

from emule_workspace.config import MiniupnpcPackageOptions, WorkspaceOptions
from emule_workspace.process import PythonInvocation
from emule_workspace import miniupnpc_release


class FakeLayout:
    def __init__(self, root: Path) -> None:
        self.workspace_root = root / "workspaces" / "workspace"
        self.miniupnp_root = root / "repos" / "third_party" / "emulebb-miniupnp"
        self.workspace_root.mkdir(parents=True)
        (self.miniupnp_root / "tools").mkdir(parents=True)
        (self.miniupnp_root / "tools" / "package_windows.py").write_text("# test\n", encoding="utf-8")

    def resolve_workspace_path(self, relative_path: str) -> Path:
        assert relative_path == "repos/third_party/emulebb-miniupnp"
        return self.miniupnp_root


def test_package_miniupnpc_invokes_repo_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layout = FakeLayout(tmp_path)
    calls: list[tuple[list[str], Path]] = []
    msbuild = tmp_path / "MSBuild.exe"
    msbuild.write_text("", encoding="utf-8")
    monkeypatch.setattr(miniupnpc_release, "get_msbuild_path", lambda: msbuild)
    monkeypatch.setattr(miniupnpc_release, "get_python_invocation", lambda: PythonInvocation(Path("python")))
    monkeypatch.setattr(
        miniupnpc_release,
        "run_native",
        lambda command, *, label, cwd: calls.append(([str(part) for part in command], cwd)),
    )

    miniupnpc_release.create_miniupnpc_package(
        layout,  # type: ignore[arg-type]
        WorkspaceOptions(workspace_root=tmp_path, configuration="Release", platform="x64"),
        MiniupnpcPackageOptions(release_version="2.2.3-emulebb.1", clean=True),
    )

    assert calls
    command, cwd = calls[0]
    assert cwd == layout.miniupnp_root
    assert str(layout.miniupnp_root / "tools" / "package_windows.py") in command
    assert "--platform" in command
    assert "x64" in command
    assert "--require-clean" in command
    assert "--clean" in command
    assert str(layout.workspace_root / "state" / "release" / "miniupnpc-v2.2.3-emulebb.1") in command


def test_package_miniupnpc_rejects_debug_config(tmp_path: Path) -> None:
    layout = FakeLayout(tmp_path)

    with pytest.raises(RuntimeError, match="requires --config Release"):
        miniupnpc_release.create_miniupnpc_package(
            layout,  # type: ignore[arg-type]
            WorkspaceOptions(workspace_root=tmp_path, configuration="Debug", platform="x64"),
            MiniupnpcPackageOptions(),
        )
