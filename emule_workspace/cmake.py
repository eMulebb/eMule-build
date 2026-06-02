"""CMake dependency build helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Sequence

from .build_state import BuildSession, count_warnings
from .toolchain import get_cmake_path


def static_msvc_runtime_cmake_arguments() -> tuple[str, ...]:
    """Returns CMake arguments that enforce the workspace static CRT policy."""

    return (
        "-DCMAKE_POLICY_DEFAULT_CMP0091=NEW",
        "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded$<$<CONFIG:Debug>:Debug>",
    )


def cmake_generator_arguments(platform: str, *, toolset: str = "") -> tuple[str, ...]:
    """Returns CMake generator arguments for the active Visual Studio image."""

    args: list[str] = []
    generator = os.environ.get("EMULEBB_CMAKE_GENERATOR", "").strip()
    raw_platform = os.environ.get("EMULEBB_CMAKE_PLATFORM")
    generator_platform = platform if raw_platform is None else raw_platform.strip()
    if generator:
        args.extend(("-G", generator))
    if generator_platform:
        args.extend(("-A", generator_platform))
    if toolset and (not generator or generator.startswith("Visual Studio ")):
        args.extend(("-T", toolset))
    return tuple(args)


def invoke_cmake_dependency_build(
    session: BuildSession,
    *,
    source_directory: Path,
    build_directory: Path,
    step_name: str,
    target_name: str | None = None,
    configure_arguments: Sequence[str] = (),
) -> None:
    """Configures and builds one CMake-owned dependency."""

    log_path = session.cmake_log_path(source_directory)
    cmake_path = get_cmake_path()
    configure = [
        "-S",
        str(source_directory),
        "-B",
        str(build_directory),
        *cmake_generator_arguments(
            session.options.platform,
            toolset=os.environ.get(session.layout.toolset_override_variable, "").strip(),
        ),
        "-DBUILD_SHARED_LIBS=OFF",
        *configure_arguments,
    ]
    build = ["--build", str(build_directory), "--config", session.options.configuration]
    if target_name:
        build.extend(["--target", target_name])

    started_at = time.monotonic()
    try:
        build_directory.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "== Configure ==\n" + f"{cmake_path} {' '.join(configure)}\n\n",
            encoding="utf-8",
            newline="\n",
        )
        with log_path.open("a", encoding="utf-8", newline="\n") as stream:
            completed = subprocess.run([str(cmake_path), *configure], stdout=stream, stderr=subprocess.STDOUT, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"cmake configure failed with exit code {completed.returncode}.")

        with log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("\n== Build ==\n" + f"{cmake_path} {' '.join(build)}\n")
            completed = subprocess.run([str(cmake_path), *build], stdout=stream, stderr=subprocess.STDOUT, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"cmake build failed with exit code {completed.returncode}.")

        session.add_step(
            name=step_name,
            succeeded=True,
            log_path=log_path,
            duration_seconds=time.monotonic() - started_at,
            warning_count=count_warnings(log_path),
        )
    except Exception:
        session.add_step(
            name=step_name,
            succeeded=False,
            log_path=log_path,
            duration_seconds=time.monotonic() - started_at,
            warning_count=count_warnings(log_path),
        )
        raise


def remove_tree_if_present(path: Path) -> None:
    """Removes a generated build tree when present."""

    if path.exists():
        shutil.rmtree(path)
