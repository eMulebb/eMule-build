"""aMule Windows package orchestration."""

from __future__ import annotations

import re
from pathlib import Path

from .build import resolve_msys2_root
from .config import AmulePackageOptions, WorkspaceOptions
from .layout import WorkspaceLayout
from .process import get_python_invocation, run_native


def create_amule_package(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    package_options: AmulePackageOptions,
) -> None:
    """Builds an aMule Windows package via the aMule repo script."""

    if workspace_options.configuration != "Release":
        raise RuntimeError("package amule requires --config Release.")
    if not re.fullmatch(r"\d+\.\d+\.\d+-emulebb\.\d+", package_options.release_version):
        raise RuntimeError(
            "aMule release version must use MAJOR.MINOR.PATCH-emulebb.N format: "
            f"{package_options.release_version}"
        )

    amule_root = layout.amule_repo_root
    if amule_root is None:
        raise RuntimeError(
            "package amule requires a manual repos/amule checkout; "
            "it is no longer materialized by workspace setup."
        )
    package_script = amule_root / "tools" / "package_windows.py"
    if not package_script.is_file():
        raise RuntimeError(f"aMule package script is missing: {package_script}")

    release_root = layout.output_release_root / f"amule-{package_options.release_version}"
    _assert_under(release_root, layout.output_release_root)

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
            "--msys2-root",
            resolve_msys2_root(),
            "--require-clean",
            *(("--clean",) if package_options.clean else ()),
        ]
    )
    run_native(command, label="aMule package", cwd=amule_root)


def _assert_under(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())
