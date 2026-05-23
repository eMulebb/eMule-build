"""Canonical build and release-test artifact names."""

from __future__ import annotations

from datetime import datetime, timezone

from .layout import file_token


def utc_run_id() -> str:
    """Returns the sortable UTC run id used in generated artifact paths."""

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_log_directory_name(run_id: str, command_name: str) -> str:
    """Returns the per-command build log directory name."""

    return f"{run_id}-{file_token(command_name).lower()}"


def build_result_file_name() -> str:
    """Returns the canonical build recap filename."""

    return "build-result.json"


def certification_result_file_name() -> str:
    """Returns the canonical certification report filename."""

    return "certification-result.json"


def release_campaign_result_file_name() -> str:
    """Returns the canonical release campaign execution report filename."""

    return "release-campaign-run-result.json"
