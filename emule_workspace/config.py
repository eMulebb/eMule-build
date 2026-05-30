"""Typed command configuration for eMule workspace orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .network_context import TestNetwork, VpnTestNetwork

BuildConfiguration = Literal["Debug", "Release"]
BuildPlatform = Literal["x64", "ARM64"]
BuildOutputMode = Literal["Full", "Warnings", "ErrorsOnly"]
ClientBuildTarget = Literal["amule"]
LiveE2eProfile = Literal[
    "default",
    "multi-client-p2p",
    "multi-client-p2p-required",
    "protocol-parity",
    "beta-green",
    "controller-surface",
    "installer-controller-surface",
    "controller-local",
    "package-helpers",
    "beta-release",
    "release-expanded",
    "release-expanded-quick",
    "stabilization-stress",
    "stabilization-stress-quick",
    "cpu-heavy",
    "cpu-heavy-quick",
    "ui-resource-depth",
    "diagnostics-soak",
]
CertificationProfile = Literal["fast", "overnight"]
BROAD_LIVE_E2E_PRE_RUN_CLEANUP_PROFILES: tuple[LiveE2eProfile, ...] = (
    "controller-surface",
    "installer-controller-surface",
    "release-expanded",
    "release-expanded-quick",
    "stabilization-stress",
    "stabilization-stress-quick",
    "ui-resource-depth",
    "diagnostics-soak",
)


class WorkspaceOptions(BaseModel):
    """Common workspace command options resolved from CLI input and environment."""

    model_config = ConfigDict(frozen=True)

    workspace_root: Path = Field(description="Canonical EMULEBB_WORKSPACE_ROOT path.")
    workspace_name: str = Field(default="workspace")
    configuration: BuildConfiguration = "Release"
    platform: BuildPlatform = "x64"
    build_output_mode: BuildOutputMode = "ErrorsOnly"

    @field_validator("workspace_root")
    @classmethod
    def resolve_workspace_root(cls, value: Path) -> Path:
        """Stores the workspace root as an absolute path."""

        return value.expanduser().resolve()


class BuildClientsOptions(BaseModel):
    """Options for building opt-in third-party P2P client fixtures."""

    model_config = ConfigDict(frozen=True)

    clean: bool = False
    clients: tuple[ClientBuildTarget, ...] = ()


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
    test_network: TestNetwork = "default"
    pre_run_cleanup: bool = False
    fail_fast: bool = False
    skip_live_seed_refresh: bool = False
    materialize_test_install: bool = False
    materialize_test_install_release_version: str = "0.7.3-rc.1"
    materialize_test_install_clean: bool = False
    materialize_test_install_skip_build: bool = False
    live_process_monitor_profile_dir: str | None = None
    startup_trace_mode: str = "required"
    shared_root: str | None = None
    preference_ui_directories_tree_stress: bool = False
    shared_files_ui_scenarios: tuple[str, ...] = ()
    shared_files_tree_stress_churn_cycles: int = -1
    admin_volume_fixtures: bool = False
    vhd_size_mb: int = 256
    mount_root: str | None = None
    keep_admin_fixtures: bool = False
    dependency_mode: Literal["cache-only", "auto-download", "off"] = "cache-only"
    dependency_channel: Literal["pinned", "latest"] = "pinned"
    dependency_cache_root: str | None = None
    refresh_dependencies: bool = False
    prowlarr_exe: str | None = None
    radarr_exe: str | None = None
    sonarr_exe: str | None = None
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
    arr_download_proof_mode: str = "complete"
    p2p_bind_interface_name: str = "hide.me"
    rest_server_search_count: int = 6
    rest_kad_search_count: int = 6
    rest_download_trigger_count: int = 1
    rest_search_method_override: str = ""
    rest_webserver_scheme: str = "https"
    local_kad_bootstrap_mode: str = "rest"
    local_kad_nodes_dat_fixture_mode: str = "valid"
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
    multi_client_require_optional_clients: bool = False
    search_ui_search_rounds: int = 1
    search_ui_download_lifecycle_count: int = 1
    godzilla_visible_ui: bool = False
    godzilla_p2p_bind_interface_address: str | None = None
    godzilla_cpu_profile: bool = False
    godzilla_stage: Literal["full", "launch-scale"] | None = None
    godzilla_vhd_runtime_root: Literal["drive-letter"] = "drive-letter"
    godzilla_total_client_count: int = 30
    godzilla_peer_transfer_count: int = 300
    godzilla_harness_transfer_count: int = 300
    godzilla_emulebb_files: int = 600
    godzilla_extra_emulebb_files: int = 50
    godzilla_harness_files: int = 400
    godzilla_amule_files: int = 100
    godzilla_adverse_kill_cycles: int = 2
    godzilla_adverse_kill_warmup_seconds: float = 45.0
    godzilla_adverse_recovery_timeout_seconds: float = 300.0
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
    test_network: VpnTestNetwork = "vpn"
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
    test_network: VpnTestNetwork = "vpn"
    rest_webserver_scheme: str = "https"
    keep_artifacts: bool = False
    ready_timeout_seconds: float = 60.0
    network_ready_timeout_seconds: float = 180.0
    search_observation_timeout_seconds: float = 120.0
    p2p_bind_interface_name: str = "hide.me"


class AmutorrentEmulebbUiOptions(BaseModel):
    """Options forwarded to the aMuTorrent eMuleBB UI live E2E runner."""

    model_config = ConfigDict(frozen=True)

    live_wire_inputs_file: str | None = None
    test_network: VpnTestNetwork = "vpn"
    rest_webserver_scheme: str = "https"
    keep_artifacts: bool = False
    ready_timeout_seconds: float = 60.0
    network_ready_timeout_seconds: float = 180.0
    search_observation_timeout_seconds: float = 120.0
    p2p_bind_interface_name: str = "hide.me"


class AmutorrentResilienceOptions(BaseModel):
    """Options forwarded to the aMuTorrent resilience live E2E runner."""

    model_config = ConfigDict(frozen=True)

    live_wire_inputs_file: str | None = None
    test_network: VpnTestNetwork = "vpn"
    rest_webserver_scheme: str = "https"
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

    campaign: str = "emulebb-0.7.3"
    test_network: TestNetwork = "default"
    phase: str | None = None
    show_template: bool = False
    json_output: bool = False
    execute: bool = False
    include_nonblocking: bool = False
    continue_on_failure: bool = False
    dry_run: bool = False
    pre_run_cleanup: bool = True
    live_wire_inputs_file: str | None = None
    radarr_movie_root: str | None = None
    sonarr_series_root: str | None = None
    acquisition_timeout_minutes: float | None = None
    p2p_bind_interface_name: str = "hide.me"
    skip_live_seed_refresh: bool = False


class CertificationOptions(BaseModel):
    """Options for the release-certification test matrix."""

    model_config = ConfigDict(frozen=True)

    profile: CertificationProfile = "fast"
    test_network: TestNetwork = "default"
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

    release_version: str = "0.7.3-rc.1"
    clean: bool = False


class AmutorrentPackageOptions(BaseModel):
    """Options for building the optional aMuTorrent package artifact."""

    model_config = ConfigDict(frozen=True)

    release_version: str = "0.7.3-rc.1"
    clean: bool = False


class AmulePackageOptions(BaseModel):
    """Options for building the optional aMule Windows package artifact."""

    model_config = ConfigDict(frozen=True)

    release_version: str = "3.0.0-emulebb.1"
    clean: bool = False


class MiniupnpcPackageOptions(BaseModel):
    """Options for building the optional MiniUPnP CLI package artifact."""

    model_config = ConfigDict(frozen=True)

    release_version: str = "2.2.3-emulebb.1"
    clean: bool = False


class LocalPackageInstallOptions(BaseModel):
    """Options for refreshing a local package-style install."""

    model_config = ConfigDict(frozen=True)

    release_version: str = "0.7.3-rc.1"
    clean: bool = False
    skip_build: bool = False
    live_wire_inputs_file: str | None = None


class LocalHammerCampaignOptions(BaseModel):
    """Options for the installer-backed local heavy hammer campaign."""

    model_config = ConfigDict(frozen=True)

    until_local: str | None = None
    timezone_str: str = "Europe/Berlin"
    max_cycles: int = 0
    cycle_pause_seconds: float = 0.0
    dry_run: bool = False
    live_wire_inputs_file: str | None = None
    release_version: str = "0.7.3-rc.1"
    clean: bool = False
    skip_build: bool = False
    p2p_bind_interface_name: str = "hide.me"
    godzilla_p2p_bind_interface_address: str | None = None
    profile_symbols_required: bool = True


class CleanupOptions(BaseModel):
    """Options for pruning generated workspace artifacts."""

    model_config = ConfigDict(frozen=True)

    apply: bool = False
    profile: Literal["routine", "deep"] = "routine"
    report_payload_retention_hours: float = 24.0
    report_run_retention_days: float = 3.0
    arr_acquisition_retention_hours: float = 24.0
    build_log_retention_days: float = 7.0
    keep_build_log_runs: int = 25
    include_build_outputs: bool = False
    include_release_state: bool = False
    include_product_family_outputs: bool = False
    include_root_legacy_state: bool = False
    include_legacy_root_logs: bool = False
    include_profiling_artifacts: bool = True
    include_legacy_test_reports: bool = True


def resolve_workspace_options(
    *,
    workspace_root: str | None,
    workspace_name: str | None,
    configuration: str,
    platform: str,
    build_output_mode: str,
) -> WorkspaceOptions:
    """Builds common workspace options from Click values and environment."""

    resolved_root = workspace_root or os.environ.get("EMULEBB_WORKSPACE_ROOT")
    if not resolved_root:
        raise ValueError("EMULEBB_WORKSPACE_ROOT or --workspace-root is required.")
    return WorkspaceOptions(
        workspace_root=Path(resolved_root),
        workspace_name=workspace_name or "workspace",
        configuration=configuration,
        platform=platform,
        build_output_mode=build_output_mode,
    )
