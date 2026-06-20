"""Runtime staging helpers for qBittorrentBB folder builds."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QbittorrentbbRuntimeStageResult:
    """Files copied while staging a dynamic qBittorrentBB runtime folder."""

    bundled_runtime: list[str]
    copied_plugins: list[Path]


_QBT_SYSTEM_DLL_PREFIXES = ("api-ms-win-", "ext-ms-win-")
_QBT_SYSTEM_DLLS = frozenset(name.lower() for name in (
    "kernel32.dll", "user32.dll", "gdi32.dll", "gdi32full.dll", "advapi32.dll", "shell32.dll",
    "ole32.dll", "oleaut32.dll", "ws2_32.dll", "iphlpapi.dll", "powrprof.dll", "dbgeng.dll",
    "ntdll.dll", "crypt32.dll", "secur32.dll", "userenv.dll", "version.dll", "winmm.dll",
    "comdlg32.dll", "shlwapi.dll", "msvcrt.dll", "setupapi.dll", "dwmapi.dll", "uxtheme.dll",
    "imm32.dll", "d3d11.dll", "dxgi.dll", "opengl32.dll", "gdiplus.dll", "mpr.dll", "netapi32.dll",
    "rpcrt4.dll", "bcrypt.dll", "ncrypt.dll", "wtsapi32.dll", "propsys.dll", "comctl32.dll",
    "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll", "msvcp140_1.dll",
    "msvcp140_2.dll", "ucrtbase.dll", "authz.dll", "cryptbase.dll", "win32u.dll", "ws2help.dll",
))

_QBT_QT_PLUGINS = {
    "platforms": ("qwindows.dll",),
    "styles": ("qmodernwindowsstyle.dll", "qwindowsvistastyle.dll"),
    "sqldrivers": ("qsqlite.dll",),
    "tls": ("qschannelbackend.dll", "qopensslbackend.dll"),
    "iconengines": ("qsvgicon.dll",),
    "imageformats": (
        "qgif.dll", "qico.dll", "qjpeg.dll", "qsvg.dll", "qicns.dll",
        "qtga.dll", "qtiff.dll", "qwbmp.dll", "qwebp.dll",
    ),
}


def stage_qbittorrentbb_runtime(
    *,
    executable: Path,
    target_root: Path,
    qt_prefix: Path,
    qbt_root: Path,
    search_dirs: list[Path],
) -> QbittorrentbbRuntimeStageResult:
    """Stages DLLs, Qt plugins, and qt.conf next to a dynamic qBittorrentBB exe."""

    if not executable.is_file():
        raise RuntimeError(f"qBittorrentBB executable not found for runtime staging: {executable}")
    if not qt_prefix.is_dir():
        raise RuntimeError(f"qBittorrentBB Qt prefix is not a directory: {qt_prefix}")
    target_root.mkdir(parents=True, exist_ok=True)

    plugin_dlls = _qbt_copy_qt_plugins(qt_prefix, target_root)
    bundled_runtime = _qbt_bundle_runtime_dlls([executable, *plugin_dlls], target_root, search_dirs)
    _qbt_write_qt_conf(qbt_root, target_root)
    return QbittorrentbbRuntimeStageResult(
        bundled_runtime=bundled_runtime,
        copied_plugins=plugin_dlls,
    )


def _qbt_is_system_dll(name: str) -> bool:
    low = name.lower()
    return low in _QBT_SYSTEM_DLLS or low.startswith(_QBT_SYSTEM_DLL_PREFIXES)


def _qbt_find_dumpbin() -> str:
    found = shutil.which("dumpbin")
    if found:
        return found
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.is_file():
        result = subprocess.run([str(vswhere), "-latest", "-property", "installationPath"],
                                capture_output=True, text=True, check=False)
        root = result.stdout.strip()
        if root:
            candidates = sorted(Path(root).glob("VC/Tools/MSVC/*/bin/Hostx64/x64/dumpbin.exe"))
            if candidates:
                return str(candidates[-1])
    raise RuntimeError("dumpbin not found; the MSVC dev environment must be on PATH.")


def _qbt_dll_dependents(dumpbin: str, binary: Path) -> list[str]:
    result = subprocess.run([dumpbin, "/dependents", str(binary)],
                            capture_output=True, text=True, check=False)
    deps = []
    for line in result.stdout.splitlines():
        token = line.strip()
        if token.lower().endswith(".dll") and (" " not in token):
            deps.append(token)
    return deps


def _qbt_bundle_runtime_dlls(roots: list[Path], target_root: Path, search_dirs: list[Path]) -> list[str]:
    """Copies every non-system DLL the roots need transitively into target_root."""

    dumpbin = _qbt_find_dumpbin()
    seen: set[str] = set()
    bundled: list[str] = []
    queue: list[Path] = list(roots)
    while queue:
        binary = queue.pop()
        for dep in _qbt_dll_dependents(dumpbin, binary):
            low = dep.lower()
            if (low in seen) or _qbt_is_system_dll(dep):
                continue
            seen.add(low)
            for directory in search_dirs:
                src = directory / dep
                if src.is_file():
                    dst = target_root / dep
                    if not dst.exists():
                        shutil.copy2(src, dst)
                        bundled.append(dep)
                    queue.append(dst)
                    break
    return sorted(bundled)


def _qbt_copy_qt_plugins(qt_prefix: Path, target_root: Path) -> list[Path]:
    copied: list[Path] = []
    for subdir, names in _QBT_QT_PLUGINS.items():
        for name in names:
            src = qt_prefix / "plugins" / subdir / name
            if src.is_file():
                dst = target_root / "plugins" / subdir / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(dst)
    return copied


def _qbt_write_qt_conf(qbt_root: Path, target_root: Path) -> None:
    src = qbt_root / "dist" / "windows" / "qt.conf"
    if src.is_file():
        shutil.copy2(src, target_root / "qt.conf")
    else:
        (target_root / "qt.conf").write_text("[Paths]\nPlugins=plugins\n", encoding="utf-8", newline="\n")
