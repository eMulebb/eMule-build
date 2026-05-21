"""Typed command configuration for eMule workspace orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BuildConfiguration = Literal["Debug", "Release"]
BuildPlatform = Literal["x64", "ARM64"]
BuildOutputMode = Literal["Full", "Warnings", "ErrorsOnly"]
LiveE2eProfile = Literal[
    "default",
    "protocol-parity",
    "beta-green",
    "controller-surface",
    "beta-release",
    "release-expanded",
    "stabilization-stress",
    "cpu-heavy",
    "ui-resource-depth",
]
CertificationProfile = Literal["fast", "overnight"]
BROAD_LIVE_E2E_PRE_RUN_CLEANUP_PROFILES: tuple[LiveE2eProfile, ...] = (
    "controller-surface",
    "release-expanded",
    "stabilization-stress",
    "ui-resource-depth",
)


class WorkspaceOptions(BaseModel):
    """Common workspace command options resolved from CLI input and environment."""

    model_config = ConfigDict(frozen=True)

    workspace_root: Path = Field(description="Canonical EMULE_WORKSPACE_ROOT path.")
    workspace_name: str = Field(default="workspace")
    configuration: BuildConfiguration = "Release"
    platform: BuildPlatform = "x64"
    build_output_mode: BuildOutputMode = "ErrorsOnly"

    @field_validator("workspace_root")
    @classmethod
    def resolve_workspace_root(cls, value: Path) -> Path:
        """Stores the workspace root as an absolute path."""

        return value.expanduser().resolve()


class PythonTestOptions(BaseModel):
    """Options for running the fast Python harness tests."""

    model_config = ConfigDict(frozen=True)

    quiet: bool = False
    paths: tuple[str, ...] = ()
    expression: str | None = None
    extra_args: tuple[str, ...] = ()


class BuildTestsOptions(BaseModel):
    """Options for building the native eMule shared test executable."""

    model_config = ConfigDict(frozen=True)

    clean: bool = False
    test_run_variant: str | None = None


class VariantComparisonOptions(BaseModel):
    """Options for commands that compare two managed app variants."""

    model_config = ConfigDict(frozen=True)

    test_run_variant: str | None = None
    baseline_variant: str | None = None


class LiveE2eOptions(BaseModel):
    """Options forwarded to the aggregate live E2E suite runner."""

    model_config = ConfigDict(frozen=True)

    suites: tuple[str, ...] = ()
    profile: LiveE2eProfile = "default"
    pre_run_cleanup: bool = False
    fail_fast: bool = False
    skip_live_seed_refresh: bool = False
    startup_trace_mode: str = "required"
    shared_root: str | None = None
    preference_ui_directories_tree_stress: bool = False
    shared_files_ui_scenarios: tuple[str, ...] = ()
    shared_files_tree_stress_churn_cycles: int = -1
    admin_volume_fixtures: bool = False
    vhd_size_mb: int = 256
    mount_root: str | None = None
    keep_admin_fixtures: bool = False
    profile_cpu: bool = False
    profile_cpu_max_file_mb: int = 512
    profile_cpu_stack: bool = False
    profile_cpu_stack_min_hits: int = 10
    profile_symbols_required: bool = True
    profile_memory: bool = False
    profile_resource_interval_seconds: float = 2.0
    live_wire_inputs_file: str | None = None
    radarr_movie_root: str | None = None
    sonarr_series_root: str | None = None
    acquisition_timeout_minutes: float | None = None
    p2p_bind_interface_name: str = "hide.me"
    rest_server_search_count: int = 6
    rest_kad_search_count: int = 6
    rest_download_trigger_count: int = 1
    rest_search_method_override: str = ""
    rest_webserver_scheme: str = "http"
    rest_coverage_budget: str = "contract"
    rest_stress_budget: str = "smoke"
    rest_stress_duration_seconds: float = 30.0
    rest_stress_concurrency: int = 4
    rest_stress_max_failures: int = 1
    rest_stress_request_timeout_seconds: float = 5.0
    rest_socket_adversity_budget: str = "off"
    rest_tls_handshake_adversity_budget: str = "off"
    rest_leak_churn_budget: str = "off"
    rest_leak_churn_cycles: int = -1
    rest_stop_start_after_churn: bool = False
    search_ui_search_rounds: int = 1
    search_ui_download_lifecycle_count: int = 1
    rest_cold_start_dump_stress_waves: int = 4
    rest_cold_start_dump_stress_searches_per_wave: int = 12
    rest_cold_start_dump_stress_max_concurrent_searches: int = 8
    rest_cold_start_dump_stress_search_observation_timeout_seconds: float = 60.0
    rest_cold_start_dump_stress_downloads_per_wave: int = 600
    rest_cold_start_dump_stress_downloads_per_search: int = 50
    rest_cold_start_dump_stress_max_missing_download_triggers: int = 0
    rest_cold_start_dump_stress_synthetic_queue_fill_count: int = 0
    rest_cold_start_dump_stress_synthetic_queue_fill_size_bytes: int = 1024 * 1024
    rest_cold_start_dump_stress_synthetic_queue_fill_batch_size: int = 50
    rest_cold_start_dump_stress_target_completed_downloads: int = 0
    rest_cold_start_dump_stress_completion_timeout_seconds: float = 1800.0
    rest_cold_start_dump_stress_max_active_downloads: int = 512
    rest_cold_start_dump_stress_allow_required_zero_result_searches: bool = False
    rest_cold_start_dump_stress_skip_transfer_cleanup: bool = False
    rest_cold_start_dump_stress_download_churn_interval_seconds: float = 0.0
    rest_cold_start_dump_stress_download_remove_count_per_churn: int = 0
    rest_cold_start_dump_stress_resource_monitor_interval_seconds: float = 5.0
    rest_cold_start_dump_stress_post_drain_seconds: float = 30.0
    rest_cold_start_dump_stress_tool_timeout_seconds: float = 60.0
    rest_cold_start_dump_stress_enable_umdh: bool = False
    rest_cold_start_dump_stress_skip_umdh_diffs: bool = False
    rest_cold_start_dump_stress_cpu_profile: bool = False
    rest_cold_start_dump_stress_cpu_profile_max_file_mb: int = 512
    rest_cold_start_dump_stress_cpu_profile_stack: bool = False
    rest_cold_start_dump_stress_cpu_profile_stack_min_hits: int = 10
    rest_cold_start_dump_stress_cpu_profile_symbols_required: bool = True
    rest_cold_start_dump_stress_skip_dumps: bool = False


class AmutorrentSessionOptions(BaseModel):
    """Options forwarded to the aMuTorrent interactive session runner."""

    model_config = ConfigDict(frozen=True)

    live_network: bool = False


class FakeKadTrustSoakOptions(BaseModel):
    """Options forwarded to the focused fake-file/Kad trust live soak runner."""

    model_config = ConfigDict(frozen=True)

    live_wire_inputs_file: str | None = None
    keep_artifacts: bool = False
    keep_running: bool = False
    skip_live_seed_refresh: bool = False
    duration_seconds: float = 3 * 60 * 60
    cycle_pause_seconds: float = 10.0
    search_observation_timeout_seconds: float = 90.0
    resource_sample_interval_seconds: float = 60.0
    min_result_rows: int = 1
    min_kad_publish_info_rows: int = 1
    max_failed_cycles: int = 0
    require_kad_connected: bool = False
    p2p_bind_interface_name: str = "hide.me"


class AmutorrentCleanStartupOptions(BaseModel):
    """Options forwarded to the aMuTorrent clean-startup live E2E runner."""

    model_config = ConfigDict(frozen=True)

    live_wire_inputs_file: str | None = None
    keep_artifacts: bool = False
    ready_timeout_seconds: float = 60.0
    network_ready_timeout_seconds: float = 180.0
    search_observation_timeout_seconds: float = 120.0
    p2p_bind_interface_name: str = "hide.me"


class AmutorrentEmulebbUiOptions(BaseModel):
    """Options forwarded to the aMuTorrent eMule BB UI live E2E runner."""

    model_config = ConfigDict(frozen=True)

    live_wire_inputs_file: str | None = None
    keep_artifacts: bool = False
    ready_timeout_seconds: float = 60.0
    network_ready_timeout_seconds: float = 180.0
    search_observation_timeout_seconds: float = 120.0
    p2p_bind_interface_name: str = "hide.me"


class AmutorrentResilienceOptions(BaseModel):
    """Options forwarded to the aMuTorrent resilience live E2E runner."""

    model_config = ConfigDict(frozen=True)

    live_wire_inputs_file: str | None = None
    keep_artifacts: bool = False
    ready_timeout_seconds: float = 60.0
    network_ready_timeout_seconds: float = 180.0
    search_observation_timeout_seconds: float = 120.0
    reconnect_timeout_seconds: float = 120.0
    p2p_bind_interface_name: str = "hide.me"


class CommunityCoverageOptions(VariantComparisonOptions):
    """Options forwarded to the community-core coverage runner."""

    rest_coverage_budget: str = "contract"
    rest_stress_budget: str = "smoke"


class ReleaseCampaignOptions(BaseModel):
    """Options for reporting or executing release campaign matrices."""

    model_config = ConfigDict(frozen=True)

    campaign: str = "emule-bb-0.7.3"
    phase: str | None = None
    show_template: bool = False
    json_output: bool = False
    execute: bool = False
    include_nonblocking: bool = False
    continue_on_failure: bool = False
    dry_run: bool = False
    pre_run_cleanup: bool = True


class CertificationOptions(BaseModel):
    """Options for the release-certification test matrix."""

    model_config = ConfigDict(frozen=True)

    profile: CertificationProfile = "fast"
    pre_run_cleanup: bool = True
    continue_on_failure: bool = False
    live_wire_inputs_file: str | None = None
    radarr_movie_root: str | None = None
    sonarr_series_root: str | None = None
    acquisition_timeout_minutes: float | None = None
    p2p_bind_interface_name: str = "hide.me"
    skip_live_seed_refresh: bool = False


class ReleasePackageOptions(BaseModel):
    """Options for building a release package artifact."""

    model_config = ConfigDict(frozen=True)

    release_version: str = "0.7.3"
    clean: bool = False


class AmutorrentPackageOptions(BaseModel):
    """Options for building the optional aMuTorrent package artifact."""

    model_config = ConfigDict(frozen=True)

    release_version: str = "0.7.3"
    clean: bool = False


class CleanupOptions(BaseModel):
    """Options for pruning generated workspace artifacts."""

    model_config = ConfigDict(frozen=True)

    apply: bool = False
    profile: Literal["routine", "deep"] = "routine"
    report_payload_retention_hours: float = 24.0
    report_run_retention_days: float = 7.0
    arr_acquisition_retention_hours: float = 24.0
    build_log_retention_days: float = 14.0
    keep_build_log_runs: int = 25
    include_build_outputs: bool = False
    include_release_state: bool = False


def resolve_workspace_options(
    *,
    workspace_root: str | None,
    workspace_name: str | None,
    configuration: str,
    platform: str,
    build_output_mode: str,
) -> WorkspaceOptions:
    """Builds common workspace options from Click values and environment."""

    resolved_root = workspace_root or os.environ.get("EMULE_WORKSPACE_ROOT")
    if not resolved_root:
        raise ValueError("EMULE_WORKSPACE_ROOT or --workspace-root is required.")
    return WorkspaceOptions(
        workspace_root=Path(resolved_root),
        workspace_name=workspace_name or "workspace",
        configuration=configuration,
        platform=platform,
        build_output_mode=build_output_mode,
    )
