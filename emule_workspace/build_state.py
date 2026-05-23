"""Build step summaries and log-path management."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .artifact_names import build_log_directory_name, build_result_file_name, utc_run_id
from .config import WorkspaceOptions
from .layout import WorkspaceLayout, file_token


@dataclass(frozen=True)
class BuildStepResult:
    """Result recorded for one build step."""

    name: str
    succeeded: bool
    log_path: Path | None
    binary_log_path: Path | None
    duration_seconds: float
    warning_count: int


@dataclass
class BuildSession:
    """Mutable state for one build command execution."""

    layout: WorkspaceLayout
    options: WorkspaceOptions
    command_name: str
    clean: bool = False
    stamp: str = field(default_factory=utc_run_id)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    steps: list[BuildStepResult] = field(default_factory=list)

    @property
    def log_directory(self) -> Path:
        """Returns and creates the per-command log directory."""

        return self.layout.build_log_directory(build_log_directory_name(self.stamp, self.command_name))

    def msbuild_log_paths(
        self,
        project_path: Path,
        target: str,
        *,
        configuration: str | None = None,
        platform: str | None = None,
    ) -> tuple[Path, Path]:
        """Returns text and binary MSBuild log paths for one project."""

        relative_project = project_path.resolve().relative_to(self.layout.emule_workspace_root)
        token = file_token(str(relative_project.with_suffix("")))
        suffix = f"{target.lower()}-{(configuration or self.options.configuration).lower()}-{(platform or self.options.platform).lower()}"
        return (
            self.log_directory / f"{token}-{suffix}.log",
            self.log_directory / f"{token}-{suffix}.binlog",
        )

    def cmake_log_path(self, source_directory: Path) -> Path:
        """Returns the CMake dependency build log path for one source root."""

        relative_source = source_directory.resolve().relative_to(self.layout.emule_workspace_root)
        token = file_token(f"{relative_source}-cmake")
        suffix = f"build-{self.options.configuration.lower()}-{self.options.platform.lower()}"
        return self.log_directory / f"{token}-{suffix}.log"

    def add_step(
        self,
        *,
        name: str,
        succeeded: bool,
        log_path: Path | None,
        binary_log_path: Path | None = None,
        duration_seconds: float,
        warning_count: int,
    ) -> None:
        """Records one build step result and prints a short status line."""

        self.steps.append(
            BuildStepResult(
                name=name,
                succeeded=succeeded,
                log_path=log_path,
                binary_log_path=binary_log_path,
                duration_seconds=duration_seconds,
                warning_count=warning_count,
            )
        )
        duration = format_duration(duration_seconds)
        if succeeded:
            if self.options.build_output_mode != "Full":
                print(f"OK   {name} ({duration})")
            return
        suffix = f" -> {log_path}" if log_path else ""
        print(f"FAIL {name} ({duration}){suffix}")

    def write_recap(self) -> None:
        """Writes the machine-readable build recap and prints a concise summary."""

        if not self.steps:
            return
        completed_at = datetime.now(timezone.utc)
        failed_count = sum(1 for step in self.steps if not step.succeeded)
        total_duration = sum(step.duration_seconds for step in self.steps)
        total_warnings = sum(step.warning_count for step in self.steps)
        summary = {
            "command": self.command_name,
            "workspace_root": str(self.layout.emule_workspace_root),
            "workspace_name": self.options.workspace_name,
            "config": self.options.configuration,
            "platform": self.options.platform,
            "clean": self.clean,
            "build_output_mode": self.options.build_output_mode,
            "started_utc": self.started_at.isoformat(),
            "updated_utc": completed_at.isoformat(),
            "total_duration_seconds": round(total_duration, 3),
            "total_warning_count": total_warnings,
            "log_directory": str(self.log_directory),
            "failed_steps": failed_count,
            "step_count": len(self.steps),
            "steps": [
                {
                    "name": step.name,
                    "succeeded": step.succeeded,
                    "duration_seconds": round(step.duration_seconds, 3),
                    "warning_count": step.warning_count,
                    "log_path": str(step.log_path) if step.log_path else "",
                    "binary_log_path": str(step.binary_log_path) if step.binary_log_path else "",
                }
                for step in self.steps
            ],
        }
        recap_path = self.log_directory / build_result_file_name()
        recap_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")

        print("")
        print(f"Build recap: {self.command_name}")
        for step in self.steps:
            status = "OK  " if step.succeeded else "FAIL"
            print(f"{status} {step.name} ({format_duration(step.duration_seconds)}, {step.warning_count} warnings)")
        print(f"Steps: {len(self.steps)}")
        print(f"Failures: {failed_count}")
        print(f"Warnings: {total_warnings}")
        print(f"Duration: {format_duration(total_duration)}")
        print(f"Logs: {self.log_directory}")
        print(f"Summary: {recap_path}")


def count_warnings(log_path: Path | None) -> int:
    """Counts meaningful warning lines in a build log."""

    if log_path is None or not log_path.is_file():
        return 0
    warning_pattern = re.compile(r"\bwarning\b", re.IGNORECASE)
    summary_pattern = re.compile(r"^\s*\d+\s+warning\(s\)\s*$", re.IGNORECASE)
    return sum(
        1
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if warning_pattern.search(line) and not summary_pattern.search(line)
    )


def format_duration(total_seconds: float) -> str:
    """Formats a duration like the legacy workspace script."""

    if total_seconds < 10:
        return f"{total_seconds:.1f}s"
    return f"{round(total_seconds):.0f}s"
