"""Toolchain discovery for eMule workspace builds."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .process import find_tool, run_captured


@dataclass(frozen=True)
class VisualStudioInfo:
    """Resolved Visual Studio installation paths used by build orchestration."""

    root: Path
    msbuild: Path


def get_visual_studio_info() -> VisualStudioInfo | None:
    """Resolves Visual Studio 2022 with MSBuild."""

    install_path = _vswhere_install_path()
    if install_path is None:
        for base in _program_files_roots():
            root_2022 = base / "Microsoft Visual Studio" / "2022"
            if root_2022.is_dir():
                editions = sorted([path for path in root_2022.iterdir() if path.is_dir()])
                if editions:
                    install_path = editions[0]
                    break
    if install_path is None:
        return None
    msbuild = install_path / "MSBuild" / "Current" / "Bin" / "MSBuild.exe"
    return VisualStudioInfo(root=install_path.resolve(), msbuild=msbuild.resolve())


def get_msbuild_path() -> Path:
    """Returns the MSBuild executable path or raises an actionable error."""

    info = get_visual_studio_info()
    if info is None or not info.msbuild.is_file():
        raise RuntimeError("Visual Studio 2022 with MSBuild is required.")
    return info.msbuild


def get_cmake_path() -> Path:
    """Returns the CMake executable path."""

    path_cmake = find_tool(("cmake.exe", "cmake"))
    if path_cmake is not None:
        return path_cmake
    info = get_visual_studio_info()
    if info is not None:
        candidate = info.root / "Common7" / "IDE" / "CommonExtensions" / "Microsoft" / "CMake" / "CMake" / "bin" / "cmake.exe"
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("cmake.exe not found.")


def get_perl_path() -> Path:
    """Returns the Perl executable path used by the mbedTLS project."""

    path_perl = find_tool(("perl.exe", "perl"))
    if path_perl is not None:
        return path_perl
    for candidate in (
        Path("C:/Program Files/Git/usr/bin/perl.exe"),
        Path("C:/Program Files (x86)/Git/usr/bin/perl.exe"),
    ):
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("perl.exe not found.")


def get_dumpbin_path() -> Path:
    """Returns dumpbin.exe from PATH or the active Visual Studio toolchain."""

    path_dumpbin = find_tool(("dumpbin.exe", "dumpbin"))
    if path_dumpbin is not None:
        return path_dumpbin
    info = get_visual_studio_info()
    if info is None:
        raise RuntimeError("Visual Studio 2022 with dumpbin.exe is required.")
    msvc_root = info.root / "VC" / "Tools" / "MSVC"
    if not msvc_root.is_dir():
        raise RuntimeError(f"MSVC tools root not found: {msvc_root}")
    for toolset in sorted(msvc_root.iterdir(), reverse=True):
        # WHY: search both x64-hosted and native ARM64-hosted tool directories so
        # dumpbin (used for CFG verification) resolves on a native ARM64 build host
        # (e.g. the windows-11-arm CI runner), not only on x64 hosts. PATH lookup
        # above still takes priority.
        for relative in (
            Path("bin/Hostx64/x64/dumpbin.exe"),
            Path("bin/HostX64/x64/dumpbin.exe"),
            Path("bin/Hostx64/arm64/dumpbin.exe"),
            Path("bin/HostX64/arm64/dumpbin.exe"),
            Path("bin/HostARM64/arm64/dumpbin.exe"),
            Path("bin/Hostarm64/arm64/dumpbin.exe"),
            Path("bin/HostARM64/x64/dumpbin.exe"),
            Path("bin/Hostarm64/x64/dumpbin.exe"),
        ):
            candidate = toolset / relative
            if candidate.is_file():
                return candidate.resolve()
    raise RuntimeError("dumpbin.exe was not found in the active Visual Studio toolchain.")


def _vswhere_install_path() -> Path | None:
    vswhere = find_tool(("vswhere.exe", "vswhere"))
    if vswhere is None:
        for base in _program_files_roots():
            candidate = base / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
            if candidate.is_file():
                vswhere = candidate.resolve()
                break
    if vswhere is None:
        return None
    output = run_captured(
        [
            vswhere,
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.Component.MSBuild",
            "-property",
            "installationPath",
        ],
        label="vswhere",
        cwd=vswhere.parent,
    ).strip()
    if not output:
        return None
    return Path(output.splitlines()[0]).resolve()


def _program_files_roots() -> tuple[Path, ...]:
    roots = []
    for name in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(name)
        if value:
            roots.append(Path(value))
    return tuple(roots)
