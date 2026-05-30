"""Workspace test and live-test orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import os
from pathlib import Path

from .config import (
    AmutorrentCleanStartupOptions,
    AmutorrentEmulebbUiOptions,
    AmutorrentResilienceOptions,
    AmutorrentSessionOptions,
    CommunityCoverageOptions,
    FakeKadTrustSoakOptions,
    LiveE2eOptions,
    LocalPackageInstallOptions,
    ReleaseCampaignOptions,
    VariantComparisonOptions,
    WorkspaceOptions,
)
from .cleanup import run_pre_test_cleanup
from .hide_me_split_tunnel import ensure_split_tunnel_apps, restart_hide_me_after_upnp_failure_if_requested
from .layout import WorkspaceLayout, get_test_build_tag
from .local_package_install import materialize_test_local_install
from .network_context import TestNetwork, resolve_workspace_network_context
from .process import find_tool, get_python_invocation, run_native


def invoke_test_runs(layout: WorkspaceLayout, options: WorkspaceOptions) -> None:
    """Runs native parity/web_api suites, coverage, and live-diff."""

    invoke_native_test_suites(layout, options, None, ("parity", "protocol-parity", "web_api"))

    python = get_python_invocation()
    test_run_variant = layout.test_targets.test_run_variant
    app_root = layout.get_app_variant(test_run_variant).path
    run_native(
        python.command(
            [
                layout.tests_repo_root / "scripts" / "run-native-coverage.py",
                "--test-repo-root",
                layout.tests_repo_root,
                "--workspace-root",
                layout.workspace_root,
                "--app-root",
                app_root,
                "--configuration",
                options.configuration,
                "--platform",
                options.platform,
                "--suite-name",
                "parity",
                "--suite-name",
                "protocol-parity",
                "--suite-name",
                "web_api",
            ]
        ),
        label="native coverage",
        cwd=layout.emule_workspace_root,
        env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
    )
    invoke_live_diff_runs(layout, options, VariantComparisonOptions())


def invoke_native_test_suites(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    test_run_variant: str | None,
    suite_names: Sequence[str],
) -> None:
    """Runs the native emule-tests executable without live-diff or live E2E work."""

    _assert_test_execution_platform_supported(options)
    selected_variant = test_run_variant or layout.test_targets.test_run_variant
    app_root = layout.get_app_variant(selected_variant).path
    build_tag = get_test_build_tag(layout.workspace_root, app_root)
    binary_path = layout.tests_repo_root / "build" / build_tag / options.platform / options.configuration / "emule-tests.exe"
    if not binary_path.is_file():
        raise RuntimeError(f"Built test executable not found: {binary_path}")

    suites = tuple(suite_names) if suite_names else ("parity", "web_api")
    for suite_name in suites:
        run_native(
            [binary_path, f"--test-suite={suite_name}"],
            label=f"{suite_name} tests {selected_variant} {options.configuration}/{options.platform}",
            cwd=layout.tests_repo_root,
        )


def invoke_live_diff_runs(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    comparison_options: VariantComparisonOptions,
) -> None:
    """Runs live-diff between two configured app variants."""

    _assert_test_execution_platform_supported(options)
    test_run_variant = comparison_options.test_run_variant or layout.test_targets.test_run_variant
    baseline_variant = comparison_options.baseline_variant or layout.test_targets.baseline_variant
    test_run_app_root = layout.get_app_variant(test_run_variant).path
    baseline_app_root = layout.get_app_variant(baseline_variant).path
    python = get_python_invocation()
    run_native(
        python.command(
            [
                layout.tests_repo_root / "scripts" / "run-live-diff.py",
                "--test-repo-root",
                layout.tests_repo_root,
                "--test-run-workspace-root",
                layout.workspace_root,
                "--baseline-workspace-root",
                layout.workspace_root,
                "--test-run-app-root",
                test_run_app_root,
                "--baseline-app-root",
                baseline_app_root,
                "--configuration",
                options.configuration,
                "--platform",
                options.platform,
            ]
        ),
        label=f"live diff {test_run_variant} vs {baseline_variant}",
        cwd=layout.emule_workspace_root,
        env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
    )


def invoke_protocol_parity(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    comparison_options: VariantComparisonOptions,
) -> None:
    """Runs the focused Kad/eD2K protocol parity gate."""

    _assert_test_execution_platform_supported(options)
    test_run_variant = comparison_options.test_run_variant or layout.test_targets.test_run_variant
    baseline_variant = comparison_options.baseline_variant or layout.test_targets.baseline_variant
    test_run_app_root = layout.get_app_variant(test_run_variant).path
    baseline_app_root = layout.get_app_variant(baseline_variant).path
    python = get_python_invocation()

    run_native(
        python.command(
            [
                layout.tests_repo_root / "scripts" / "run-protocol-surface-diff.py",
                "--test-repo-root",
                layout.tests_repo_root,
                "--workspace-root",
                layout.workspace_root,
                "--test-run-app-root",
                test_run_app_root,
                "--baseline-app-root",
                baseline_app_root,
            ]
        ),
        label=f"protocol surface diff {test_run_variant} vs {baseline_variant}",
        cwd=layout.emule_workspace_root,
        env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
    )
    run_native(
        python.command(
            [
                layout.tests_repo_root / "scripts" / "validate-protocol-goldens.py",
                "--test-repo-root",
                layout.tests_repo_root,
            ]
        ),
        label="protocol oracle golden validation",
        cwd=layout.emule_workspace_root,
        env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
    )
    run_native(
        python.command(
            [
                layout.tests_repo_root / "scripts" / "run-live-diff.py",
                "--test-repo-root",
                layout.tests_repo_root,
                "--test-run-workspace-root",
                layout.workspace_root,
                "--baseline-workspace-root",
                layout.workspace_root,
                "--test-run-app-root",
                test_run_app_root,
                "--baseline-app-root",
                baseline_app_root,
                "--configuration",
                options.configuration,
                "--platform",
                options.platform,
                "--suite-name",
                "protocol-parity",
            ]
        ),
        label=f"protocol parity live diff {test_run_variant} vs {baseline_variant}",
        cwd=layout.emule_workspace_root,
        env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
    )


def invoke_community_core_coverage(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    coverage_options: CommunityCoverageOptions,
) -> None:
    """Runs community-core coverage checks between two variants."""

    _assert_test_execution_platform_supported(options)
    test_run_variant = coverage_options.test_run_variant or layout.test_targets.test_run_variant
    baseline_variant = coverage_options.baseline_variant or layout.test_targets.baseline_variant
    test_run_app_root = layout.get_app_variant(test_run_variant).path
    baseline_app_root = layout.get_app_variant(baseline_variant).path
    python = get_python_invocation()
    run_native(
        python.command(
            [
                layout.tests_repo_root / "scripts" / "run-community-core-coverage.py",
                "--test-repo-root",
                layout.tests_repo_root,
                "--workspace-root",
                layout.workspace_root,
                "--main-app-root",
                test_run_app_root,
                "--community-app-root",
                baseline_app_root,
                "--configuration",
                options.configuration,
                "--platform",
                options.platform,
                "--include-live-rest-e2e",
                "--rest-coverage-budget",
                coverage_options.rest_coverage_budget,
                "--rest-stress-budget",
                coverage_options.rest_stress_budget,
            ]
        ),
        label=f"community core coverage {test_run_variant} vs {baseline_variant}",
        cwd=layout.emule_workspace_root,
        env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
    )


def invoke_live_e2e_suite(layout: WorkspaceLayout, options: WorkspaceOptions, live_options: LiveE2eOptions) -> None:
    """Runs the aggregate live E2E suite."""

    _assert_test_execution_platform_supported(options)
    if live_options.pre_run_cleanup:
        run_pre_test_cleanup(layout)
    app_root = layout.get_app_variant(layout.test_targets.test_run_variant).path
    app_exe: Path | None = None
    profile_seed_config_dir: Path | None = None
    live_process_monitor_profile_dir: Path | None = None
    if live_options.materialize_test_install:
        materialized = materialize_test_local_install(
            layout,
            options,
            LocalPackageInstallOptions(
                live_wire_inputs_file=live_options.live_wire_inputs_file,
                release_version=live_options.materialize_test_install_release_version,
                clean=live_options.materialize_test_install_clean,
                skip_build=live_options.materialize_test_install_skip_build,
            ),
            run_id=_live_e2e_test_install_run_id(),
            suite_name="live-e2e-suite",
            client_id=layout.test_targets.test_run_variant,
        )
        app_root = materialized.app_root
        app_exe = materialized.app_exe
        profile_seed_config_dir = materialized.profile_seed_config_dir
        live_process_monitor_profile_dir = materialized.profile_dir
    if live_options.live_process_monitor_profile_dir:
        live_process_monitor_profile_dir = Path(
            _resolve_workspace_path_argument(layout, live_options.live_process_monitor_profile_dir)
        )
    if live_options.test_network in {"vpn", "all"}:
        ensure_split_tunnel_apps(_hide_me_registration_paths(_resolve_live_e2e_app_exe(app_root, app_exe, options)))
    script_path = layout.tests_repo_root / "scripts" / "run-live-e2e-suite.py"
    if not script_path.is_file():
        raise RuntimeError(f"Missing live E2E suite runner: {script_path}")

    args: list[str | Path | int | float] = [
        script_path,
        "--workspace-root",
        layout.workspace_root,
        "--app-root",
        app_root,
        "--configuration",
        options.configuration,
        "--startup-trace-mode",
        live_options.startup_trace_mode,
        "--test-network",
        live_options.test_network,
        "--profile-cpu-max-file-mb",
        live_options.profile_cpu_max_file_mb,
        "--profile-cpu-stack-min-hits",
        live_options.profile_cpu_stack_min_hits,
        "--profile-resource-interval-seconds",
        live_options.profile_resource_interval_seconds,
        "--rest-server-search-count",
        live_options.rest_server_search_count,
        "--rest-kad-search-count",
        live_options.rest_kad_search_count,
        "--rest-download-trigger-count",
        live_options.rest_download_trigger_count,
        "--rest-coverage-budget",
        live_options.rest_coverage_budget,
        "--rest-stress-budget",
        live_options.rest_stress_budget,
        "--rest-stress-duration-seconds",
        live_options.rest_stress_duration_seconds,
        "--rest-stress-concurrency",
        live_options.rest_stress_concurrency,
        "--rest-stress-max-failures",
        live_options.rest_stress_max_failures,
        "--rest-stress-request-timeout-seconds",
        live_options.rest_stress_request_timeout_seconds,
        "--rest-socket-adversity-budget",
        live_options.rest_socket_adversity_budget,
        "--rest-tls-handshake-adversity-budget",
        live_options.rest_tls_handshake_adversity_budget,
        "--rest-leak-churn-budget",
        live_options.rest_leak_churn_budget,
        "--search-ui-search-rounds",
        live_options.search_ui_search_rounds,
        "--search-ui-download-lifecycle-count",
        live_options.search_ui_download_lifecycle_count,
        "--p2p-bind-interface-name",
        live_options.p2p_bind_interface_name,
        "--rest-cold-start-dump-stress-waves",
        live_options.rest_cold_start_dump_stress_waves,
        "--rest-cold-start-dump-stress-searches-per-wave",
        live_options.rest_cold_start_dump_stress_searches_per_wave,
        "--rest-cold-start-dump-stress-max-concurrent-searches",
        live_options.rest_cold_start_dump_stress_max_concurrent_searches,
        "--rest-cold-start-dump-stress-search-observation-timeout-seconds",
        live_options.rest_cold_start_dump_stress_search_observation_timeout_seconds,
        "--rest-cold-start-dump-stress-downloads-per-wave",
        live_options.rest_cold_start_dump_stress_downloads_per_wave,
        "--rest-cold-start-dump-stress-downloads-per-search",
        live_options.rest_cold_start_dump_stress_downloads_per_search,
        "--rest-cold-start-dump-stress-max-missing-download-triggers",
        live_options.rest_cold_start_dump_stress_max_missing_download_triggers,
        "--rest-cold-start-dump-stress-synthetic-queue-fill-count",
        live_options.rest_cold_start_dump_stress_synthetic_queue_fill_count,
        "--rest-cold-start-dump-stress-synthetic-queue-fill-size-bytes",
        live_options.rest_cold_start_dump_stress_synthetic_queue_fill_size_bytes,
        "--rest-cold-start-dump-stress-synthetic-queue-fill-batch-size",
        live_options.rest_cold_start_dump_stress_synthetic_queue_fill_batch_size,
        "--rest-cold-start-dump-stress-target-completed-downloads",
        live_options.rest_cold_start_dump_stress_target_completed_downloads,
        "--rest-cold-start-dump-stress-completion-timeout-seconds",
        live_options.rest_cold_start_dump_stress_completion_timeout_seconds,
        "--rest-cold-start-dump-stress-max-active-downloads",
        live_options.rest_cold_start_dump_stress_max_active_downloads,
        "--rest-cold-start-dump-stress-download-churn-interval-seconds",
        live_options.rest_cold_start_dump_stress_download_churn_interval_seconds,
        "--rest-cold-start-dump-stress-download-remove-count-per-churn",
        live_options.rest_cold_start_dump_stress_download_remove_count_per_churn,
        "--rest-cold-start-dump-stress-resource-monitor-interval-seconds",
        live_options.rest_cold_start_dump_stress_resource_monitor_interval_seconds,
        "--rest-cold-start-dump-stress-post-drain-seconds",
        live_options.rest_cold_start_dump_stress_post_drain_seconds,
        "--rest-cold-start-dump-stress-tool-timeout-seconds",
        live_options.rest_cold_start_dump_stress_tool_timeout_seconds,
        "--rest-cold-start-dump-stress-cpu-profile-max-file-mb",
        live_options.rest_cold_start_dump_stress_cpu_profile_max_file_mb,
        "--rest-cold-start-dump-stress-cpu-profile-stack-min-hits",
        live_options.rest_cold_start_dump_stress_cpu_profile_stack_min_hits,
    ]
    if app_exe is not None:
        args.extend(["--app-exe", app_exe])
    if profile_seed_config_dir is not None:
        args.extend(["--profile-seed-dir", profile_seed_config_dir])
    if live_process_monitor_profile_dir is not None:
        args.extend(["--live-process-monitor-profile-dir", live_process_monitor_profile_dir])
    _append_optional_flag(args, live_options.profile_cpu, "--profile-cpu")
    _append_optional_flag(args, live_options.profile_cpu_stack, "--profile-cpu-stack")
    _append_optional_flag(args, live_options.multi_client_require_optional_clients, "--multi-client-require-optional-clients")
    _append_optional_flag(args, live_options.godzilla_visible_ui, "--godzilla-visible-ui")
    _append_optional_flag(args, live_options.godzilla_cpu_profile, "--godzilla-cpu-profile")
    if live_options.godzilla_p2p_bind_interface_address:
        args.extend(["--godzilla-p2p-bind-interface-address", live_options.godzilla_p2p_bind_interface_address])
    if live_options.godzilla_stage is not None:
        args.extend(["--godzilla-stage", live_options.godzilla_stage])
    args.extend(["--godzilla-vhd-runtime-root", live_options.godzilla_vhd_runtime_root])
    args.extend(["--godzilla-total-client-count", live_options.godzilla_total_client_count])
    args.extend(["--godzilla-peer-transfer-count", live_options.godzilla_peer_transfer_count])
    args.extend(["--godzilla-harness-transfer-count", live_options.godzilla_harness_transfer_count])
    args.extend(["--godzilla-emulebb-files", live_options.godzilla_emulebb_files])
    args.extend(["--godzilla-extra-emulebb-files", live_options.godzilla_extra_emulebb_files])
    args.extend(["--godzilla-harness-files", live_options.godzilla_harness_files])
    args.extend(["--godzilla-amule-files", live_options.godzilla_amule_files])
    args.extend(["--godzilla-adverse-kill-cycles", live_options.godzilla_adverse_kill_cycles])
    args.extend(["--godzilla-adverse-kill-warmup-seconds", live_options.godzilla_adverse_kill_warmup_seconds])
    args.extend(["--godzilla-adverse-recovery-timeout-seconds", live_options.godzilla_adverse_recovery_timeout_seconds])
    if not live_options.profile_symbols_required:
        args.append("--no-profile-symbols-required")
    _append_optional_flag(args, live_options.profile_memory, "--profile-memory")
    _append_optional_flag(args, live_options.rest_cold_start_dump_stress_enable_umdh, "--rest-cold-start-dump-stress-enable-umdh")
    _append_optional_flag(args, live_options.rest_cold_start_dump_stress_cpu_profile, "--rest-cold-start-dump-stress-cpu-profile")
    _append_optional_flag(args, live_options.rest_cold_start_dump_stress_cpu_profile_stack, "--rest-cold-start-dump-stress-cpu-profile-stack")
    _append_optional_flag(
        args,
        live_options.rest_cold_start_dump_stress_allow_required_zero_result_searches,
        "--rest-cold-start-dump-stress-allow-required-zero-result-searches",
    )
    _append_optional_flag(
        args,
        live_options.rest_cold_start_dump_stress_skip_transfer_cleanup,
        "--rest-cold-start-dump-stress-skip-transfer-cleanup",
    )
    _append_optional_flag(args, live_options.rest_cold_start_dump_stress_skip_umdh_diffs, "--rest-cold-start-dump-stress-skip-umdh-diffs")
    if not live_options.rest_cold_start_dump_stress_cpu_profile_symbols_required:
        args.append("--no-rest-cold-start-dump-stress-cpu-profile-symbols-required")
    _append_optional_flag(args, live_options.rest_cold_start_dump_stress_skip_dumps, "--rest-cold-start-dump-stress-skip-dumps")
    if live_options.rest_leak_churn_cycles >= 0:
        args.extend(["--rest-leak-churn-cycles", live_options.rest_leak_churn_cycles])
    _append_optional_flag(args, live_options.rest_stop_start_after_churn, "--rest-stop-start-after-churn")
    if live_options.shared_root:
        args.extend(["--shared-root", live_options.shared_root])
    _append_optional_flag(args, live_options.admin_volume_fixtures, "--admin-volume-fixtures")
    args.extend(["--vhd-size-mb", live_options.vhd_size_mb])
    if live_options.mount_root:
        args.extend(["--mount-root", live_options.mount_root])
    _append_optional_flag(args, live_options.keep_admin_fixtures, "--keep-admin-fixtures")
    args.extend(["--dependency-mode", live_options.dependency_mode])
    args.extend(["--dependency-channel", live_options.dependency_channel])
    if live_options.dependency_cache_root:
        args.extend(["--dependency-cache-root", _resolve_workspace_path_argument(layout, live_options.dependency_cache_root)])
    _append_optional_flag(args, live_options.refresh_dependencies, "--refresh-dependencies")
    if live_options.prowlarr_exe:
        args.extend(["--prowlarr-exe", _resolve_workspace_path_argument(layout, live_options.prowlarr_exe)])
    if live_options.radarr_exe:
        args.extend(["--radarr-exe", _resolve_workspace_path_argument(layout, live_options.radarr_exe)])
    if live_options.sonarr_exe:
        args.extend(["--sonarr-exe", _resolve_workspace_path_argument(layout, live_options.sonarr_exe)])
    _append_optional_flag(args, live_options.preference_ui_directories_tree_stress, "--preference-ui-directories-tree-stress")
    for scenario_name in live_options.shared_files_ui_scenarios:
        args.extend(["--shared-files-ui-scenario", scenario_name])
    if live_options.shared_files_tree_stress_churn_cycles >= 0:
        args.extend(["--shared-files-tree-stress-churn-cycles", live_options.shared_files_tree_stress_churn_cycles])
    if live_options.live_wire_inputs_file:
        args.extend(["--live-wire-inputs-file", _resolve_workspace_argument(layout, live_options.live_wire_inputs_file)])
    if live_options.radarr_movie_root:
        args.extend(["--radarr-movie-root", live_options.radarr_movie_root])
    if live_options.sonarr_series_root:
        args.extend(["--sonarr-series-root", live_options.sonarr_series_root])
    if live_options.acquisition_timeout_minutes is not None:
        args.extend(["--media-acquisition-timeout-minutes", live_options.acquisition_timeout_minutes])
    args.extend(["--arr-download-proof-mode", live_options.arr_download_proof_mode])
    if live_options.rest_search_method_override:
        args.extend(["--rest-search-method-override", live_options.rest_search_method_override])
    args.extend(["--rest-webserver-scheme", live_options.rest_webserver_scheme])
    args.extend(["--local-kad-bootstrap-mode", live_options.local_kad_bootstrap_mode])
    args.extend(["--local-kad-nodes-dat-fixture-mode", live_options.local_kad_nodes_dat_fixture_mode])
    if live_options.profile != "default":
        args.extend(["--profile", live_options.profile])
    for suite_name in live_options.suites:
        args.extend(["--suite", suite_name])
    _append_optional_flag(args, live_options.fail_fast, "--fail-fast")
    _append_optional_flag(args, live_options.skip_live_seed_refresh, "--skip-live-seed-refresh")

    python = get_python_invocation()
    _run_live_native(
        layout,
        python.command(args),
        label="live E2E suite",
        cwd=layout.emule_workspace_root,
        env=_test_network_env(
            layout,
            test_network=live_options.test_network,
            vpn_interface_name=live_options.p2p_bind_interface_name,
        ),
    )


def invoke_release_campaign_report(
    layout: WorkspaceLayout,
    campaign_options: ReleaseCampaignOptions,
) -> None:
    """Shows the eMuleBB release campaign matrix and latest evidence status."""

    script_path = layout.tests_repo_root / "scripts" / "show-release-campaigns.py"
    if not script_path.is_file():
        raise RuntimeError(f"Missing release campaign reporter: {script_path}")

    args: list[str | Path] = [
        script_path,
        "--test-repo-root",
        layout.tests_repo_root,
        "--workspace-root",
        layout.emule_workspace_root,
        "--workspace-state-root",
        layout.workspace_root / "state",
        "--campaign",
        campaign_options.campaign,
    ]
    if campaign_options.phase:
        args.extend(["--phase", campaign_options.phase])
    _append_optional_flag(args, campaign_options.show_template, "--template")
    _append_optional_flag(args, campaign_options.json_output, "--json")

    python = get_python_invocation()
    run_native(
        python.command(args),
        label="release campaign report",
        cwd=layout.emule_workspace_root,
        env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
    )


def invoke_amutorrent_interactive_session(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    session_options: AmutorrentSessionOptions,
) -> None:
    """Starts a disposable interactive aMuTorrent session."""

    _assert_test_execution_platform_supported(options)
    app_root = layout.get_app_variant(layout.test_targets.test_run_variant).path
    script_path = layout.tests_repo_root / "scripts" / "amutorrent-interactive-session.py"
    if not script_path.is_file():
        raise RuntimeError(f"Missing aMuTorrent interactive session runner: {script_path}")

    args: list[str | Path] = [
        script_path,
        "--workspace-root",
        layout.workspace_root,
        "--app-root",
        app_root,
        "--configuration",
        options.configuration,
    ]
    _append_optional_flag(args, session_options.live_network, "--live-network")
    python = get_python_invocation()
    run_native(
        python.command(args),
        label="aMuTorrent interactive session",
        cwd=layout.emule_workspace_root,
        env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
    )


def invoke_fake_kad_trust_soak(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    soak_options: FakeKadTrustSoakOptions,
) -> None:
    """Runs the focused fake-file/Kad trust live soak."""

    _assert_test_execution_platform_supported(options)
    app_root = layout.get_app_variant(layout.test_targets.test_run_variant).path
    script_path = layout.tests_repo_root / "scripts" / "fake-kad-trust-soak.py"
    if not script_path.is_file():
        raise RuntimeError(f"Missing fake/Kad trust soak runner: {script_path}")

    args: list[str | Path | float | int] = [
        script_path,
        "--workspace-root",
        layout.workspace_root,
        "--app-root",
        app_root,
        "--configuration",
        options.configuration,
        "--duration-seconds",
        soak_options.duration_seconds,
        "--cycle-pause-seconds",
        soak_options.cycle_pause_seconds,
        "--search-observation-timeout-seconds",
        soak_options.search_observation_timeout_seconds,
        "--resource-sample-interval-seconds",
        soak_options.resource_sample_interval_seconds,
        "--min-result-rows",
        soak_options.min_result_rows,
        "--min-kad-publish-info-rows",
        soak_options.min_kad_publish_info_rows,
        "--max-failed-cycles",
        soak_options.max_failed_cycles,
        "--p2p-bind-interface-name",
        soak_options.p2p_bind_interface_name,
    ]
    if soak_options.live_wire_inputs_file:
        args.extend(["--live-wire-inputs-file", _resolve_workspace_argument(layout, soak_options.live_wire_inputs_file)])
    _append_optional_flag(args, soak_options.keep_artifacts, "--keep-artifacts")
    _append_optional_flag(args, soak_options.keep_running, "--keep-running")
    _append_optional_flag(args, soak_options.skip_live_seed_refresh, "--skip-live-seed-refresh")
    _append_optional_flag(args, soak_options.require_kad_connected, "--require-kad-connected")

    python = get_python_invocation()
    _run_live_native(
        layout,
        python.command(args),
        label="fake/Kad trust soak",
        cwd=layout.emule_workspace_root,
        env=_test_network_env(
            layout,
            test_network=soak_options.test_network,
            vpn_interface_name=soak_options.p2p_bind_interface_name,
            require_vpn=True,
        ),
    )


def invoke_amutorrent_clean_startup(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    clean_options: AmutorrentCleanStartupOptions,
) -> None:
    """Runs the automated aMuTorrent first-run wizard integration proof."""

    _assert_test_execution_platform_supported(options)
    app_root = layout.get_app_variant(layout.test_targets.test_run_variant).path
    if clean_options.test_network in {"vpn", "all"}:
        ensure_split_tunnel_apps(_hide_me_registration_paths(_resolve_live_e2e_app_exe(app_root, None, options)))
    script_path = layout.tests_repo_root / "scripts" / "amutorrent-clean-startup.py"
    if not script_path.is_file():
        raise RuntimeError(f"Missing aMuTorrent clean-startup runner: {script_path}")

    args: list[str | Path | float] = [
        script_path,
        "--workspace-root",
        layout.workspace_root,
        "--app-root",
        app_root,
        "--configuration",
        options.configuration,
        "--p2p-bind-interface-name",
        clean_options.p2p_bind_interface_name,
        "--rest-webserver-scheme",
        clean_options.rest_webserver_scheme,
        "--ready-timeout-seconds",
        clean_options.ready_timeout_seconds,
        "--network-ready-timeout-seconds",
        clean_options.network_ready_timeout_seconds,
        "--search-observation-timeout-seconds",
        clean_options.search_observation_timeout_seconds,
    ]
    if clean_options.live_wire_inputs_file:
        args.extend(["--live-wire-inputs-file", _resolve_workspace_argument(layout, clean_options.live_wire_inputs_file)])
    _append_optional_flag(args, clean_options.keep_artifacts, "--keep-artifacts")

    python = get_python_invocation()
    _run_live_native(
        layout,
        python.command(args),
        label="aMuTorrent clean startup",
        cwd=layout.emule_workspace_root,
        env=_test_network_env(
            layout,
            test_network=clean_options.test_network,
            vpn_interface_name=clean_options.p2p_bind_interface_name,
            require_vpn=True,
        ),
    )


def invoke_amutorrent_resilience(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    resilience_options: AmutorrentResilienceOptions,
) -> None:
    """Runs the automated aMuTorrent resilience live E2E proof."""

    _assert_test_execution_platform_supported(options)
    app_root = layout.get_app_variant(layout.test_targets.test_run_variant).path
    if resilience_options.test_network in {"vpn", "all"}:
        ensure_split_tunnel_apps(_hide_me_registration_paths(_resolve_live_e2e_app_exe(app_root, None, options)))
    script_path = layout.tests_repo_root / "scripts" / "amutorrent-resilience-live.py"
    if not script_path.is_file():
        raise RuntimeError(f"Missing aMuTorrent resilience live runner: {script_path}")

    args: list[str | Path | float] = [
        script_path,
        "--workspace-root",
        layout.workspace_root,
        "--app-root",
        app_root,
        "--configuration",
        options.configuration,
        "--p2p-bind-interface-name",
        resilience_options.p2p_bind_interface_name,
        "--rest-webserver-scheme",
        resilience_options.rest_webserver_scheme,
        "--ready-timeout-seconds",
        resilience_options.ready_timeout_seconds,
        "--network-ready-timeout-seconds",
        resilience_options.network_ready_timeout_seconds,
        "--search-observation-timeout-seconds",
        resilience_options.search_observation_timeout_seconds,
        "--reconnect-timeout-seconds",
        resilience_options.reconnect_timeout_seconds,
    ]
    if resilience_options.live_wire_inputs_file:
        args.extend(["--live-wire-inputs-file", _resolve_workspace_argument(layout, resilience_options.live_wire_inputs_file)])
    _append_optional_flag(args, resilience_options.keep_artifacts, "--keep-artifacts")

    python = get_python_invocation()
    _run_live_native(
        layout,
        python.command(args),
        label="aMuTorrent resilience live",
        cwd=layout.emule_workspace_root,
        env=_test_network_env(
            layout,
            test_network=resilience_options.test_network,
            vpn_interface_name=resilience_options.p2p_bind_interface_name,
            require_vpn=True,
        ),
    )


def invoke_amutorrent_emulebb_ui(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    ui_options: AmutorrentEmulebbUiOptions,
) -> None:
    """Runs the automated aMuTorrent eMuleBB UI live E2E proof."""

    _assert_test_execution_platform_supported(options)
    app_root = layout.get_app_variant(layout.test_targets.test_run_variant).path
    if ui_options.test_network in {"vpn", "all"}:
        ensure_split_tunnel_apps(_hide_me_registration_paths(_resolve_live_e2e_app_exe(app_root, None, options)))
    script_path = layout.tests_repo_root / "scripts" / "amutorrent-emulebb-ui-live.py"
    if not script_path.is_file():
        raise RuntimeError(f"Missing aMuTorrent eMuleBB UI live runner: {script_path}")

    args: list[str | Path | float] = [
        script_path,
        "--workspace-root",
        layout.workspace_root,
        "--app-root",
        app_root,
        "--configuration",
        options.configuration,
        "--p2p-bind-interface-name",
        ui_options.p2p_bind_interface_name,
        "--rest-webserver-scheme",
        ui_options.rest_webserver_scheme,
        "--ready-timeout-seconds",
        ui_options.ready_timeout_seconds,
        "--network-ready-timeout-seconds",
        ui_options.network_ready_timeout_seconds,
        "--search-observation-timeout-seconds",
        ui_options.search_observation_timeout_seconds,
    ]
    if ui_options.live_wire_inputs_file:
        args.extend(["--live-wire-inputs-file", _resolve_workspace_argument(layout, ui_options.live_wire_inputs_file)])
    _append_optional_flag(args, ui_options.keep_artifacts, "--keep-artifacts")

    python = get_python_invocation()
    _run_live_native(
        layout,
        python.command(args),
        label="aMuTorrent eMuleBB UI live",
        cwd=layout.emule_workspace_root,
        env=_test_network_env(
            layout,
            test_network=ui_options.test_network,
            vpn_interface_name=ui_options.p2p_bind_interface_name,
            require_vpn=True,
        ),
    )


def _append_optional_flag(args: list, enabled: bool, flag: str) -> None:
    if enabled:
        args.append(flag)


def _run_live_native(
    layout: WorkspaceLayout,
    command: Sequence[str | os.PathLike[str]],
    *,
    label: str,
    cwd: Path,
    env: dict[str, str],
) -> None:
    completed = run_native(command, label=label, cwd=cwd, env=env, allow_failure=True)
    if int(getattr(completed, "returncode", 0) or 0) == 0:
        return

    failure_text = _recent_live_failure_text(layout.workspace_root)
    restart_hide_me_after_upnp_failure_if_requested(failure_text)
    raise RuntimeError(f"{label} failed with exit code {completed.returncode}.")


def _recent_live_failure_text(workspace_root: Path) -> str:
    state_root = workspace_root / "state"
    candidates: list[Path] = []
    for relative_root in ("test-reports", "test-artifacts"):
        root = state_root / relative_root
        if root.is_dir():
            candidates.extend(path for path in root.rglob("*.json") if path.is_file())
            candidates.extend(path for path in root.rglob("emulebb*.log") if path.is_file())

    def sort_key(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    fragments: list[str] = []
    for path in sorted(candidates, key=sort_key, reverse=True)[:32]:
        try:
            fragments.append(path.read_text(encoding="utf-8", errors="replace")[:65536])
        except OSError:
            continue
    return "\n".join(fragments)


def _hide_me_registration_paths(app_exe: Path) -> list[Path]:
    paths = [app_exe]
    try:
        paths.append(get_python_invocation().executable)
    except RuntimeError:
        pass
    node_exe = find_tool(("node.exe", "node"))
    if node_exe is not None:
        paths.append(node_exe)
    paths.extend(_playwright_browser_registration_paths())
    return paths


def _playwright_browser_registration_paths() -> list[Path]:
    """Returns locally installed Playwright browser executables that may drive live UI tests."""

    candidates: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        playwright_root = Path(local_appdata) / "ms-playwright"
        candidates.extend(playwright_root.glob("chromium-*/chrome-win/chrome.exe"))
        candidates.extend(playwright_root.glob("chromium-*/chrome-win64/chrome.exe"))
        candidates.extend(playwright_root.glob("chromium_headless_shell-*/chrome-win/headless_shell.exe"))
        candidates.extend(playwright_root.glob("chromium_headless_shell-*/chrome-win64/headless_shell.exe"))
        candidates.extend(playwright_root.glob("firefox-*/firefox/firefox.exe"))
        candidates.extend(playwright_root.glob("webkit-*/Playwright.exe"))

    browser_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if browser_env and browser_env != "0":
        playwright_root = Path(browser_env).expanduser()
        candidates.extend(playwright_root.glob("chromium-*/chrome-win/chrome.exe"))
        candidates.extend(playwright_root.glob("chromium-*/chrome-win64/chrome.exe"))
        candidates.extend(playwright_root.glob("chromium_headless_shell-*/chrome-win/headless_shell.exe"))
        candidates.extend(playwright_root.glob("chromium_headless_shell-*/chrome-win64/headless_shell.exe"))
        candidates.extend(playwright_root.glob("firefox-*/firefox/firefox.exe"))
        candidates.extend(playwright_root.glob("webkit-*/Playwright.exe"))

    return candidates


def _live_e2e_test_install_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-pid{os.getpid()}"


def _resolve_live_e2e_app_exe(app_root: Path, app_exe: Path | None, options: WorkspaceOptions) -> Path:
    """Returns the eMuleBB executable path used by live E2E runners."""

    if app_exe is not None:
        return app_exe
    return app_root / "srchybrid" / options.platform / options.configuration / "emulebb.exe"


def _resolve_workspace_argument(layout: WorkspaceLayout, value: str) -> str:
    """Resolves an existing workspace-relative operator input path."""

    path = Path(value)
    if path.is_absolute():
        return str(path)
    workspace_path = layout.emule_workspace_root / path
    if workspace_path.exists():
        return str(workspace_path.resolve())
    return value


def _resolve_workspace_path_argument(layout: WorkspaceLayout, value: str) -> str:
    """Resolves workspace-relative path knobs even when the target is created later."""

    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((layout.emule_workspace_root / path).resolve())


def _test_network_env(
    layout: WorkspaceLayout,
    *,
    test_network: TestNetwork,
    vpn_interface_name: str | None = None,
    require_vpn: bool = False,
) -> dict[str, str]:
    """Returns the eMule workspace environment for one network-scoped child run."""

    context = resolve_workspace_network_context(
        workspace_root=layout.workspace_root,
        test_network=test_network,
        vpn_interface_name=vpn_interface_name,
        require_vpn=require_vpn,
    )
    return {
        "EMULEBB_WORKSPACE_ROOT": str(layout.emule_workspace_root),
        **context.env(),
    }


def _assert_test_execution_platform_supported(options: WorkspaceOptions) -> None:
    if options.platform != "x64":
        raise RuntimeError("Test execution supports x64 only.")
