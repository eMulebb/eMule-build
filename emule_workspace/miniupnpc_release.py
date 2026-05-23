"""MiniUPnP Windows package orchestration."""

from __future__ import annotations

import re
from pathlib import Path

from .config import MiniupnpcPackageOptions, WorkspaceOptions
from .layout import WorkspaceLayout
from .process import get_python_invocation, run_native
from .toolchain import get_msbuild_path


def create_miniupnpc_package(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    package_options: MiniupnpcPackageOptions,
) -> None:
    """Builds a MiniUPnP upnpc Windows package via the MiniUPnP repo script."""

    if workspace_options.configuration != "Release":
        raise RuntimeError("package miniupnpc requires --config Release.")
    if not re.fullmatch(r"\d+\.\d+\.\d+-emulebb\.\d+", package_options.release_version):
        raise RuntimeError(
            "MiniUPnP release version must use MAJOR.MINOR.PATCH-emulebb.N format: "
            f"{package_options.release_version}"
        )

    miniupnp_root = layout.resolve_workspace_path("repos/third_party/emulebb-miniupnp")
    package_script = miniupnp_root / "tools" / "package_windows.py"
    if not package_script.is_file():
        raise RuntimeError(f"MiniUPnP package script is missing: {package_script}")

    release_root = layout.workspace_root / "state" / "release" / f"miniupnpc-v{package_options.release_version}"
    _assert_under(release_root, layout.workspace_root / "state")

    command = get_python_invocation().command(
        [
            package_script,
            "--version",
            package_options.release_version,
            "--platform",
            workspace_options.platform,
            "--configuration",
            workspace_options.configuration,
            "--output-root",
            release_root,
            "--msbuild",
            get_msbuild_path(),
            "--require-clean",
            *(("--clean",) if package_options.clean else ()),
        ]
    )
    run_native(command, label="MiniUPnP package", cwd=miniupnp_root)


def _assert_under(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())
