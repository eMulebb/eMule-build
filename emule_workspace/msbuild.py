"""MSBuild project invocation helpers."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Mapping, Sequence

from .build_state import BuildSession, count_warnings
from .process import run_native
from .toolchain import get_msbuild_path


def invoke_msbuild_project(
    session: BuildSession,
    *,
    project_path: Path,
    extra_properties: Sequence[str] = (),
    target: str = "Build",
    configuration: str | None = None,
    platform: str | None = None,
    environment_overrides: Mapping[str, str] | None = None,
    max_cpu_count: int | None = None,
    step_name: str | None = None,
) -> None:
    """Invokes MSBuild for one project and records a build step."""

    name = step_name or project_path.stem
    active_configuration = configuration or session.options.configuration
    active_platform = platform or session.options.platform
    log_path, binary_log_path = session.msbuild_log_paths(
        project_path,
        target,
        configuration=active_configuration,
        platform=active_platform,
    )
    arguments = [
        project_path,
        f"/m:{max_cpu_count}" if max_cpu_count is not None else "/m",
        "/nologo",
        f"/t:{target}",
        f"/p:Configuration={active_configuration}",
        f"/p:Platform={active_platform}",
        f"/flp:LogFile={log_path};Verbosity=normal;Encoding=UTF-8",
        f"/bl:{binary_log_path}",
        *extra_properties,
    ]
    if session.options.build_output_mode != "Full":
        clp_mode = "WarningsOnly" if session.options.build_output_mode == "Warnings" else "ErrorsOnly"
        arguments.append(f"/clp:{clp_mode}")

    started_at = time.monotonic()
    try:
        run_native(
            [get_msbuild_path(), *arguments],
            label=f"MSBuild {project_path.name}",
            cwd=session.layout.emule_workspace_root,
            env=environment_overrides,
        )
        session.add_step(
            name=name,
            succeeded=True,
            log_path=log_path,
            binary_log_path=binary_log_path,
            duration_seconds=time.monotonic() - started_at,
            warning_count=count_warnings(log_path),
        )
    except Exception:
        session.add_step(
            name=name,
            succeeded=False,
            log_path=log_path,
            binary_log_path=binary_log_path,
            duration_seconds=time.monotonic() - started_at,
            warning_count=count_warnings(log_path),
        )
        raise


def env_override(name: str) -> str | None:
    """Returns a non-empty environment override value."""

    value = os.environ.get(name)
    return value if value else None
