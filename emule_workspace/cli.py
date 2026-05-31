"""Click command surface for eMule workspace orchestration."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import click

from .build_tests import invoke_build_tests
from .build import build_apps as invoke_build_apps
from .build import build_clients as invoke_build_clients
from .build import build_libs as invoke_build_libs
from .certification import invoke_certification
from .cleanup import cleanup_workspace
from .config import (
    AmulePackageOptions,
    AmutorrentPackageOptions,
    AmutorrentCleanStartupOptions,
    AmutorrentEmulebbUiOptions,
    AmutorrentResilienceOptions,
    AmutorrentSessionOptions,
    BROAD_LIVE_E2E_PRE_RUN_CLEANUP_PROFILES,
    BuildClientsOptions,
    BuildTestsOptions,
    CertificationOptions,
    CleanupOptions,
    CommunityCoverageOptions,
    FakeKadTrustSoakOptions,
    LiveE2eOptions,
    LocalHammerCampaignOptions,
    LocalPackageInstallOptions,
    MiniupnpcPackageOptions,
    PythonTestOptions,
    ReleasePackageOptions,
    ReleaseCampaignOptions,
    VariantComparisonOptions,
    WorkspaceOptions,
    resolve_workspace_options,
)
from .evidence import build_heavy_evidence_index, print_heavy_evidence_index, write_heavy_evidence_index
from .amule_release import create_amule_package
from .layout import load_layout
from .local_hammer_campaign import invoke_local_hammer_campaign
from .local_package_install import install_local_package
from .locks import WorkspaceLock
from .materialize import materialize_workspace, sync_workspace
from .miniupnpc_release import create_miniupnpc_package
from .product_family import (
    audit_product_family_toolchain,
    prepare_product_family_repos,
    print_product_family_toolchain,
    refresh_product_family_rebases,
)
from .python_tests import invoke_python_tests
from .release import create_amutorrent_package, create_release_package
from .release_campaign_runner import invoke_release_campaign
from .setup_commands import run_compare, write_dependency_update_report, write_materialization_status
from .status import write_dependency_status, write_workspace_repo_status, write_workspace_summary
from .test_runs import (
    invoke_amutorrent_clean_startup,
    invoke_amutorrent_emulebb_ui,
    invoke_amutorrent_interactive_session,
    invoke_amutorrent_resilience,
    invoke_community_core_coverage,
    invoke_fake_kad_trust_soak,
    invoke_live_diff_runs,
    invoke_live_e2e_suite,
    invoke_native_test_suites,
    invoke_protocol_parity,
    invoke_test_runs,
)
from .validation import validate_workspace

F = TypeVar("F", bound=Callable[..., Any])

APP_VARIANT_HELP = "Configured app variant key (for example: main, community). This is not the worktree folder name."
APP_VARIANT_BUILD_HELP = f"{APP_VARIANT_HELP} Defaults to all variants."
TEST_RUN_VARIANT_HELP = f"{APP_VARIANT_HELP} Defaults to the workspace test-run variant."
BASELINE_VARIANT_HELP = f"{APP_VARIANT_HELP} Defaults to the workspace baseline variant."


def _common_options(function: F) -> F:
    @click.option("--workspace-root", envvar="EMULEBB_WORKSPACE_ROOT", help="Canonical EMULEBB_WORKSPACE_ROOT.")
    @click.option("--workspace-name", default=None, help="Workspace name. Defaults to build manifest value.")
    @click.option("--config", "configuration", type=click.Choice(["Debug", "Release"]), default="Release", show_default=True)
    @click.option("--platform", type=click.Choice(["x64", "ARM64"]), default="x64", show_default=True)
    @click.option(
        "--build-output-mode",
        type=click.Choice(["Full", "Warnings", "ErrorsOnly"]),
        default="ErrorsOnly",
        show_default=True,
    )
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            workspace_options = resolve_workspace_options(
                workspace_root=kwargs.pop("workspace_root"),
                workspace_name=kwargs.pop("workspace_name"),
                configuration=kwargs.pop("configuration"),
                platform=kwargs.pop("platform"),
                build_output_mode=kwargs.pop("build_output_mode"),
            )
            layout = load_layout(workspace_options.workspace_root, workspace_options.workspace_name)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        return function(*args, workspace_options=workspace_options, layout=layout, **kwargs)

    return wrapper  # type: ignore[return-value]


def _locked(command_name: str, function: F) -> F:
    @wraps(function)
    def wrapper(*args: Any, workspace_options: WorkspaceOptions, layout, **kwargs: Any) -> Any:
        lock = WorkspaceLock(layout=layout, command=command_name, options=workspace_options)
        if not lock.acquire():
            raise click.ClickException(
                f"Workspace busy: command '{command_name}' cannot start for "
                f"{layout.emule_workspace_root}. Active owner: {lock.active_owner_text()}."
            )
        try:
            try:
                return function(*args, workspace_options=workspace_options, layout=layout, **kwargs)
            except click.ClickException:
                raise
            except Exception as exc:
                raise click.ClickException(str(exc)) from exc
        finally:
            lock.release()

    return wrapper  # type: ignore[return-value]


def _comparison_options(function: F) -> F:
    @click.option("--test-run-variant", default=None, help=TEST_RUN_VARIANT_HELP)
    @click.option("--baseline-variant", default=None, help=BASELINE_VARIANT_HELP)
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        comparison_options = VariantComparisonOptions(
            test_run_variant=kwargs.pop("test_run_variant"),
            baseline_variant=kwargs.pop("baseline_variant"),
        )
        return function(*args, comparison_options=comparison_options, **kwargs)

    return wrapper  # type: ignore[return-value]


def _live_e2e_options(function: F) -> F:
    @click.option("--suite", "suites", multiple=True, help="Live E2E suite to run.")
    @click.option(
        "--test-network",
        type=click.Choice(["default", "offline", "lan", "vpn", "all"]),
        default="default",
        show_default=True,
        help="Network scope for live E2E suite selection.",
    )
    @click.option(
        "--profile",
        type=click.Choice([
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
        ]),
        default="default",
        show_default=True,
        help="Named live E2E suite profile.",
    )
    @click.option("--fail-fast", is_flag=True, help="Stop the live E2E suite after the first failure.")
    @click.option("--skip-live-seed-refresh", is_flag=True, help="Reuse the existing live seed state.")
    @click.option("--startup-trace-mode", type=click.Choice(["required", "optional"]), default="required", show_default=True)
    @click.option("--shared-root", default=None, help="Shared file root for live UI scenarios.")
    @click.option("--admin-volume-fixtures", is_flag=True, help="Enable admin-only VHD drive-letter and folder-mount live fixtures.")
    @click.option("--vhd-size-mb", default=256, show_default=True, type=int)
    @click.option("--mount-root", default=None, help="Parent directory for admin-only folder mount fixtures.")
    @click.option("--keep-admin-fixtures", is_flag=True, help="Leave admin VHD fixture files after a live suite for inspection.")
    @click.option("--dependency-mode", type=click.Choice(["cache-only", "auto-download", "off"]), default="cache-only", show_default=True)
    @click.option("--dependency-channel", type=click.Choice(["pinned", "latest"]), default="pinned", show_default=True)
    @click.option("--dependency-cache-root", default=None, help="Workspace-owned cache root for portable live-test dependencies.")
    @click.option("--refresh-dependencies", is_flag=True, help="Refresh cached portable live-test dependencies before running selected suites.")
    @click.option("--prowlarr-exe", default=None, help="Explicit Prowlarr executable for package-helper live tests.")
    @click.option("--radarr-exe", default=None, help="Explicit Radarr executable for package-helper live tests.")
    @click.option("--sonarr-exe", default=None, help="Explicit Sonarr executable for package-helper live tests.")
    @click.option("--preference-ui-directories-tree-stress", is_flag=True, help="Exercise the Preferences Directories tree with a large shared-directory profile.")
    @click.option("--shared-files-ui-scenario", "shared_files_ui_scenarios", multiple=True)
    @click.option("--shared-files-tree-stress-churn-cycles", default=-1, show_default=True, type=int)
    @click.option("--profile-cpu", is_flag=True, help="Capture bounded ETW CPU profiles for suites selected by broad diagnostics.")
    @click.option("--profile-cpu-max-file-mb", default=512, show_default=True, type=int)
    @click.option("--profile-cpu-stack", is_flag=True, help="Export stack-attributed CPU profile summaries when CPU profiling is enabled.")
    @click.option("--profile-cpu-stack-min-hits", default=10, show_default=True, type=int)
    @click.option("--profile-symbols-required/--no-profile-symbols-required", default=True, show_default=True)
    @click.option("--profile-memory", is_flag=True, help="Surface child suite resource monitor and memory delta diagnostics in aggregate reports.")
    @click.option("--profile-resource-interval-seconds", default=2.0, show_default=True, type=float)
    @click.option("--live-wire-inputs-file", default=None, help="Runtime live-wire search input JSON.")
    @click.option("--materialize-test-install", is_flag=True, help="Materialize an installer-backed isolated test install before live E2E.")
    @click.option("--materialize-test-install-release-version", default="0.7.3-rc.1", show_default=True)
    @click.option("--materialize-test-install-clean", is_flag=True, help="Clean package outputs before materializing the test install.")
    @click.option("--materialize-test-install-skip-build", is_flag=True, help="Reuse existing package artifacts when materializing the test install.")
    @click.option("--live-process-monitor-profile-dir", default=None, help="Existing profile directory for the live-process-monitor suite.")
    @click.option("--radarr-movie-root", default=None, help="Radarr-visible movie root for Radarr import live checks.")
    @click.option("--sonarr-series-root", default=None, help="Sonarr-visible series root for Sonarr import live checks.")
    @click.option("--acquisition-timeout-minutes", default=None, type=float, help="Arr acquisition timeout forwarded to live suites.")
    @click.option("--arr-download-proof-mode", type=click.Choice(["complete", "handoff"]), default="complete", show_default=True)
    @click.option("--p2p-bind-interface-name", default="hide.me", show_default=True)
    @click.option("--rest-server-search-count", default=6, show_default=True, type=int)
    @click.option("--rest-kad-search-count", default=6, show_default=True, type=int)
    @click.option("--rest-download-trigger-count", default=1, show_default=True, type=int)
    @click.option("--rest-search-method-override", type=click.Choice(["", "automatic", "server", "global", "kad"]), default="")
    @click.option("--rest-webserver-scheme", type=click.Choice(["http", "https"]), default="https", show_default=True)
    @click.option("--local-kad-bootstrap-mode", type=click.Choice(["rest", "preseed", "both"]), default="rest", show_default=True)
    @click.option("--local-kad-nodes-dat-fixture-mode", type=click.Choice(["valid", "truncated", "stale"]), default="valid", show_default=True)
    @click.option("--rest-coverage-budget", type=click.Choice(["smoke", "contract", "contract-stress"]), default="contract")
    @click.option("--rest-stress-budget", type=click.Choice(["off", "smoke", "soak"]), default="smoke")
    @click.option("--rest-stress-duration-seconds", default=30.0, show_default=True, type=float)
    @click.option("--rest-stress-concurrency", default=4, show_default=True, type=int)
    @click.option("--rest-stress-max-failures", default=1, show_default=True, type=int)
    @click.option("--rest-stress-request-timeout-seconds", default=5.0, show_default=True, type=float)
    @click.option("--rest-socket-adversity-budget", type=click.Choice(["off", "smoke"]), default="off")
    @click.option("--rest-tls-handshake-adversity-budget", type=click.Choice(["off", "smoke"]), default="off")
    @click.option("--rest-leak-churn-budget", type=click.Choice(["off", "smoke", "soak"]), default="off")
    @click.option("--rest-leak-churn-cycles", default=-1, show_default=True, type=int)
    @click.option("--rest-stop-start-after-churn", is_flag=True)
    @click.option("--vpn-guard-live-config", default=None)
    @click.option("--vpn-guard-allowed-public-ip-cidrs", default="")
    @click.option("--vpn-guard-scenario", type=click.Choice(["off", "success", "not-allowlisted", "vpn-off"]), default="success")
    @click.option("--multi-client-require-optional-clients", is_flag=True)
    @click.option("--search-ui-search-rounds", default=1, show_default=True, type=int)
    @click.option("--search-ui-download-lifecycle-count", default=1, show_default=True, type=int)
    @click.option("--godzilla-visible-ui", is_flag=True, help="Run the Godzilla local swarm with visible eMuleBB windows.")
    @click.option("--godzilla-p2p-bind-interface-address", default=None, help="Explicit LAN IPv4 address forwarded to the Godzilla local swarm.")
    @click.option("--godzilla-cpu-profile", is_flag=True, help="Capture a bounded ETW CPU profile for the Godzilla local swarm.")
    @click.option(
        "--godzilla-stage",
        type=click.Choice(["full", "launch-scale"]),
        default=None,
        help="Godzilla campaign boundary to run through.",
    )
    @click.option("--godzilla-total-client-count", default=30, show_default=True, type=int)
    @click.option("--godzilla-peer-transfer-count", default=300, show_default=True, type=int)
    @click.option("--godzilla-harness-transfer-count", default=300, show_default=True, type=int)
    @click.option("--godzilla-emulebb-files", default=600, show_default=True, type=int)
    @click.option("--godzilla-extra-emulebb-files", default=50, show_default=True, type=int)
    @click.option("--godzilla-harness-files", default=400, show_default=True, type=int)
    @click.option("--godzilla-amule-files", default=100, show_default=True, type=int)
    @click.option("--godzilla-adverse-kill-cycles", default=2, show_default=True, type=int)
    @click.option("--godzilla-adverse-kill-warmup-seconds", default=45.0, show_default=True, type=float)
    @click.option("--godzilla-adverse-recovery-timeout-seconds", default=300.0, show_default=True, type=float)
    @click.option(
        "--godzilla-vhd-runtime-root",
        type=click.Choice(["drive-letter"]),
        default="drive-letter",
        show_default=True,
        help="Runtime root used by Godzilla VHD fixtures; mixed aMule/tracing-harness runs must stay on the short VHD drive-letter root.",
    )
    @click.option("--rest-cold-start-dump-stress-waves", default=4, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-searches-per-wave", default=12, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-max-concurrent-searches", default=8, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-search-observation-timeout-seconds", default=60.0, show_default=True, type=float)
    @click.option("--rest-cold-start-dump-stress-downloads-per-wave", default=600, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-downloads-per-search", default=50, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-max-missing-download-triggers", default=0, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-synthetic-queue-fill-count", default=0, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-synthetic-queue-fill-size-bytes", default=1024 * 1024, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-synthetic-queue-fill-batch-size", default=50, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-target-completed-downloads", default=0, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-completion-timeout-seconds", default=1800.0, show_default=True, type=float)
    @click.option("--rest-cold-start-dump-stress-max-active-downloads", default=512, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-allow-required-zero-result-searches", is_flag=True)
    @click.option("--rest-cold-start-dump-stress-skip-transfer-cleanup", is_flag=True)
    @click.option("--rest-cold-start-dump-stress-download-churn-interval-seconds", default=0.0, show_default=True, type=float)
    @click.option("--rest-cold-start-dump-stress-download-remove-count-per-churn", default=0, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-resource-monitor-interval-seconds", default=5.0, show_default=True, type=float)
    @click.option("--rest-cold-start-dump-stress-post-drain-seconds", default=30.0, show_default=True, type=float)
    @click.option("--rest-cold-start-dump-stress-tool-timeout-seconds", default=60.0, show_default=True, type=float)
    @click.option("--rest-cold-start-dump-stress-enable-umdh", is_flag=True)
    @click.option("--rest-cold-start-dump-stress-skip-umdh-diffs", is_flag=True)
    @click.option("--rest-cold-start-dump-stress-cpu-profile", is_flag=True)
    @click.option("--rest-cold-start-dump-stress-cpu-profile-max-file-mb", default=512, show_default=True, type=int)
    @click.option("--rest-cold-start-dump-stress-cpu-profile-stack", is_flag=True)
    @click.option("--rest-cold-start-dump-stress-cpu-profile-stack-min-hits", default=10, show_default=True, type=int)
    @click.option(
        "--rest-cold-start-dump-stress-cpu-profile-symbols-required/--no-rest-cold-start-dump-stress-cpu-profile-symbols-required",
        default=True,
        show_default=True,
    )
    @click.option(
        "--pre-run-cleanup/--skip-pre-run-cleanup",
        default=None,
        help="Prune old generated outcomes before broad live E2E profiles.",
    )
    @click.option("--rest-cold-start-dump-stress-skip-dumps", is_flag=True)
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        pre_run_cleanup = kwargs.pop("pre_run_cleanup")
        values = {key: kwargs.pop(key) for key in LiveE2eOptions.model_fields if key != "pre_run_cleanup"}
        if pre_run_cleanup is None:
            pre_run_cleanup = values["profile"] in BROAD_LIVE_E2E_PRE_RUN_CLEANUP_PROFILES
        live_options = LiveE2eOptions(**values, pre_run_cleanup=pre_run_cleanup)
        return function(*args, live_options=live_options, **kwargs)

    return wrapper  # type: ignore[return-value]


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """Build, validate, test, and package an eMuleBB workspace."""


@main.command()
@click.option("--workspace-root", default=None, help="Canonical EMULEBB_WORKSPACE_ROOT. Defaults from repos/emulebb-build layout.")
@click.option("--workspace-name", default=None, help="Workspace name. Defaults to canonical topology.")
@click.option("--artifacts-seed-root", default=None, help="Optional third-party artifact seed root.")
def materialize(*, workspace_root: str | None, workspace_name: str | None, artifacts_seed_root: str | None) -> None:
    """Materialize a new canonical workspace around this emulebb-build clone."""

    try:
        materialize_workspace(
            workspace_root=workspace_root,
            workspace_name=workspace_name,
            artifacts_seed_root=artifacts_seed_root,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.option("--workspace-root", envvar="EMULEBB_WORKSPACE_ROOT", default=None, help="Canonical EMULEBB_WORKSPACE_ROOT.")
@click.option("--workspace-name", default=None, help="Workspace name. Defaults to canonical topology.")
@click.option("--artifacts-seed-root", default=None, help="Optional third-party artifact seed root.")
def sync(*, workspace_root: str | None, workspace_name: str | None, artifacts_seed_root: str | None) -> None:
    """Synchronize setup-owned workspace state."""

    try:
        sync_workspace(
            workspace_root=workspace_root,
            workspace_name=workspace_name,
            artifacts_seed_root=artifacts_seed_root,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@_common_options
@click.option(
    "--include-product-family",
    is_flag=True,
    help="Also run repo-native checks for p2p-overlord and goed2k product-family repositories.",
)
@click.option(
    "--product-family-tier",
    type=click.Choice(["quick", "quality", "full"]),
    default="quality",
    show_default=True,
    help="Repo-native product-family validation depth used with --include-product-family.",
)
@click.pass_context
def validate(
    ctx: click.Context,
    *,
    include_product_family: bool,
    product_family_tier: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run workspace validation and centralized policy audits."""

    del ctx
    _locked(
        "validate",
        lambda **kwargs: validate_workspace(
            kwargs["layout"],
            include_product_family=include_product_family,
            product_family_tier=product_family_tier,
        ),
    )(
        workspace_options=workspace_options,
        layout=layout,
    )


@main.command("prepare-product-family")
@_common_options
def prepare_product_family(*, workspace_options: WorkspaceOptions, layout) -> None:
    """Install or fetch dependencies for product-family repositories."""

    _locked("prepare-product-family", lambda **kwargs: prepare_product_family_repos(kwargs["layout"]))(
        workspace_options=workspace_options,
        layout=layout,
    )


@main.command("refresh-product-family-rebases")
@_common_options
def refresh_product_family_rebase_clones(*, workspace_options: WorkspaceOptions, layout) -> None:
    """Refresh local aMule and aMuTorrent clones after automated upstream rebases."""

    _locked("refresh-product-family-rebases", lambda **kwargs: refresh_product_family_rebases(kwargs["layout"]))(
        workspace_options=workspace_options,
        layout=layout,
    )


@main.command("product-family-toolchain")
@_common_options
@click.option("--strict", is_flag=True, help="Fail when any product-family runtime is missing or outside policy.")
def product_family_toolchain(*, strict: bool, workspace_options: WorkspaceOptions, layout) -> None:
    """Report product-family runtime and tool version policy."""

    _locked(
        "product-family-toolchain",
        lambda **kwargs: print_product_family_toolchain(audit_product_family_toolchain(strict=strict)),
    )(
        workspace_options=workspace_options,
        layout=layout,
    )


@main.command("cleanup")
@_common_options
@click.option("--apply", "apply_cleanup", is_flag=True, help="Delete selected artifacts. Omit for a dry run.")
@click.option("--profile", type=click.Choice(["routine", "deep"]), default="routine", show_default=True)
@click.option("--report-payload-retention-hours", default=24.0, show_default=True, type=float)
@click.option("--report-run-retention-days", default=3.0, show_default=True, type=float)
@click.option("--arr-acquisition-retention-hours", default=24.0, show_default=True, type=float)
@click.option("--build-log-retention-days", default=7.0, show_default=True, type=float)
@click.option("--keep-build-log-runs", default=25, show_default=True, type=int)
@click.option("--include-build-outputs", is_flag=True, help="Also prune generated app/test/dependency build outputs.")
@click.option("--include-release-state", is_flag=True, help="Also prune superseded release rehearsal state.")
@click.option("--include-product-family-outputs", is_flag=True, help="Also prune generated outputs from product-family repos.")
@click.option("--include-root-legacy-state", is_flag=True, help="Also prune legacy generated state directories at workspace root.")
@click.option("--include-legacy-root-logs", is_flag=True, help="Also prune retired root-level workspace log files.")
@click.option(
    "--include-profiling-artifacts/--skip-profiling-artifacts",
    default=True,
    show_default=True,
    help="Prune profiling diagnostics, dumps, ETW, UMDH, and pageheap output.",
)
@click.option(
    "--include-legacy-test-reports/--skip-legacy-test-reports",
    default=True,
    show_default=True,
    help="Prune legacy generated reports under repos/emulebb-build-tests/reports.",
)
def cleanup(
    *,
    apply_cleanup: bool,
    profile: str,
    report_payload_retention_hours: float,
    report_run_retention_days: float,
    arr_acquisition_retention_hours: float,
    build_log_retention_days: float,
    keep_build_log_runs: int,
    include_build_outputs: bool,
    include_release_state: bool,
    include_product_family_outputs: bool,
    include_root_legacy_state: bool,
    include_legacy_root_logs: bool,
    include_profiling_artifacts: bool,
    include_legacy_test_reports: bool,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Prune generated workspace artifacts, dry-run by default."""

    cleanup_options = CleanupOptions(
        apply=apply_cleanup,
        profile=profile,
        report_payload_retention_hours=report_payload_retention_hours,
        report_run_retention_days=report_run_retention_days,
        arr_acquisition_retention_hours=arr_acquisition_retention_hours,
        build_log_retention_days=build_log_retention_days,
        keep_build_log_runs=keep_build_log_runs,
        include_build_outputs=include_build_outputs,
        include_release_state=include_release_state,
        include_product_family_outputs=include_product_family_outputs,
        include_root_legacy_state=include_root_legacy_state,
        include_legacy_root_logs=include_legacy_root_logs,
        include_profiling_artifacts=include_profiling_artifacts,
        include_legacy_test_reports=include_legacy_test_reports,
    )
    _locked("cleanup", lambda **kwargs: cleanup_workspace(kwargs["layout"], cleanup_options))(
        workspace_options=workspace_options,
        layout=layout,
    )


@main.command("evidence-index")
@_common_options
@click.option("--threshold-mb", default=512.0, show_default=True, type=float, help="Minimum directory size to include.")
@click.option("--write/--no-write", default=True, show_default=True, help="Write state/heavy-evidence-index.json.")
def evidence_index(*, threshold_mb: float, write: bool, workspace_options: WorkspaceOptions, layout) -> None:
    """Index large generated evidence directories before cleanup decisions."""

    def run(**kwargs):
        target_layout = kwargs["layout"]
        payload = (
            write_heavy_evidence_index(target_layout, threshold_mb=threshold_mb)
            if write
            else build_heavy_evidence_index(target_layout, threshold_mb=threshold_mb)
        )
        print_heavy_evidence_index(target_layout, payload)

    _locked("evidence-index", run)(workspace_options=workspace_options, layout=layout)


@main.command("dep-status")
@_common_options
def dep_status(*, workspace_options: WorkspaceOptions, layout) -> None:
    """Report dependency and app worktree status."""

    _locked("dep-status", lambda **kwargs: write_dependency_status(kwargs["layout"]))(
        workspace_options=workspace_options,
        layout=layout,
    )


@main.command("workspace-status")
@_common_options
def workspace_status(*, workspace_options: WorkspaceOptions, layout) -> None:
    """Report branch, upstream, and dirty-state for every managed workspace repo."""

    _locked("workspace-status", lambda **kwargs: write_workspace_repo_status(kwargs["layout"]))(
        workspace_options=workspace_options,
        layout=layout,
    )


@main.command("status")
@click.option("--workspace-root", envvar="EMULEBB_WORKSPACE_ROOT", default=None, help="Canonical EMULEBB_WORKSPACE_ROOT.")
def materialization_status(*, workspace_root: str | None) -> None:
    """Report setup-managed repository status."""

    try:
        write_materialization_status(workspace_root=workspace_root)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("dep-updates")
@click.option("--workspace-root", envvar="EMULEBB_WORKSPACE_ROOT", default=None, help="Canonical EMULEBB_WORKSPACE_ROOT.")
@click.option("--workspace-name", default=None, help="Workspace name. Defaults to canonical topology.")
def dep_updates(*, workspace_root: str | None, workspace_name: str | None) -> None:
    """Report advisory third-party dependency updates."""

    try:
        write_dependency_update_report(workspace_root=workspace_root, workspace_name=workspace_name)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("compare")
@click.argument("preset_key", required=False)
@click.option("--workspace-root", envvar="EMULEBB_WORKSPACE_ROOT", default=None, help="Canonical EMULEBB_WORKSPACE_ROOT.")
def compare_command(*, preset_key: str | None, workspace_root: str | None) -> None:
    """Show or launch WinMerge comparison presets."""

    try:
        run_compare(preset_key=preset_key, workspace_root=workspace_root)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@main.group()
def build() -> None:
    """Build workspace targets."""


@build.command("libs")
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected dependency outputs before building.")
def build_libs(
    *,
    clean: bool,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build the shared dependency set."""

    _locked(
        "build libs",
        lambda **kwargs: invoke_build_libs(kwargs["layout"], kwargs["workspace_options"], clean=clean),
    )(workspace_options=workspace_options, layout=layout)


@build.command("app")
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected app outputs before building.")
@click.option("--variant", "app_variants", multiple=True, help=APP_VARIANT_BUILD_HELP)
def build_app(
    *,
    clean: bool,
    app_variants: tuple[str, ...],
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build selected app worktrees."""

    _locked(
        "build app",
        lambda **kwargs: invoke_build_apps(
            kwargs["layout"],
            kwargs["workspace_options"],
            clean=clean,
            app_variant_names=app_variants,
        ),
    )(workspace_options=workspace_options, layout=layout)


@build.command("tests")
@_common_options
@click.option("--clean", is_flag=True, help="Clean native test intermediates before building.")
@click.option("--test-run-variant", default=None, help=TEST_RUN_VARIANT_HELP)
def build_tests(
    *,
    clean: bool,
    test_run_variant: str | None,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build the shared native emule-tests executable."""

    build_options = BuildTestsOptions(clean=clean, test_run_variant=test_run_variant)
    _locked(
        "build tests",
        lambda **kwargs: invoke_build_tests(kwargs["layout"], kwargs["workspace_options"], build_options),
    )(workspace_options=workspace_options, layout=layout)


@build.command("clients")
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected client outputs before building.")
@click.option(
    "--client",
    "clients",
    multiple=True,
    type=click.Choice(["amule"]),
    help="Optional P2P client to build. Defaults to all clients.",
)
def build_clients(
    *,
    clean: bool,
    clients: tuple[str, ...],
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build opt-in third-party P2P clients for local multi-client tests."""

    build_options = BuildClientsOptions(clean=clean, clients=clients)
    _locked(
        "build clients",
        lambda **kwargs: invoke_build_clients(kwargs["layout"], kwargs["workspace_options"], build_options),
    )(workspace_options=workspace_options, layout=layout)


@build.command("all")
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected build outputs before building.")
@click.option("--variant", "app_variants", multiple=True, help=APP_VARIANT_BUILD_HELP)
@click.option("--test-run-variant", default=None, help=TEST_RUN_VARIANT_HELP)
def build_all(
    *,
    clean: bool,
    app_variants: tuple[str, ...],
    test_run_variant: str | None,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build dependencies, app variants, and the native test executable."""

    build_options = BuildTestsOptions(clean=clean, test_run_variant=test_run_variant)

    def run_all(**kwargs: Any) -> None:
        invoke_build_libs(kwargs["layout"], kwargs["workspace_options"], clean=clean)
        invoke_build_apps(kwargs["layout"], kwargs["workspace_options"], clean=clean, app_variant_names=app_variants)
        invoke_build_tests(kwargs["layout"], kwargs["workspace_options"], build_options)

    _locked("build all", run_all)(workspace_options=workspace_options, layout=layout)


@main.group()
def test() -> None:
    """Run workspace test suites."""


@test.command("python", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@_common_options
@click.option("--quiet", "-q", is_flag=True, help="Pass -q to pytest.")
@click.option("--path", "paths", multiple=True, help="Pytest path to run, relative to emulebb-build-tests.")
@click.option("--expression", "-k", default=None, help="Pytest -k expression.")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
def test_python(
    *,
    quiet: bool,
    paths: tuple[str, ...],
    expression: str | None,
    extra_args: tuple[str, ...],
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run the fast pytest harness suite."""

    test_options = PythonTestOptions(
        quiet=quiet,
        paths=paths,
        expression=expression,
        extra_args=extra_args,
    )
    _locked(
        "test python",
        lambda **kwargs: invoke_python_tests(kwargs["layout"], test_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("native")
@_common_options
@click.option("--test-run-variant", default=None, help=TEST_RUN_VARIANT_HELP)
@click.option("--suite-name", multiple=True, help="Native doctest suite to run. Defaults to parity and web_api.")
def test_native(
    *,
    test_run_variant: str | None,
    suite_name: tuple[str, ...],
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run native emule-tests suites without live-diff or live E2E work."""

    _locked(
        "test native",
        lambda **kwargs: invoke_native_test_suites(
            kwargs["layout"],
            kwargs["workspace_options"],
            test_run_variant,
            suite_name,
        ),
    )(workspace_options=workspace_options, layout=layout)


@test.command("all")
@_common_options
def test_all(*, workspace_options: WorkspaceOptions, layout) -> None:
    """Run native parity, coverage, and live-diff checks."""

    _locked("test all", lambda **kwargs: invoke_test_runs(kwargs["layout"], kwargs["workspace_options"]))(
        workspace_options=workspace_options,
        layout=layout,
    )


@test.command("live-diff")
@_common_options
@_comparison_options
def test_live_diff(
    *,
    comparison_options: VariantComparisonOptions,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Compare two configured app variants."""

    _locked(
        "test live-diff",
        lambda **kwargs: invoke_live_diff_runs(kwargs["layout"], kwargs["workspace_options"], comparison_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("protocol-parity")
@_common_options
@_comparison_options
def test_protocol_parity(
    *,
    comparison_options: VariantComparisonOptions,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run focused Kad/eD2K protocol parity checks against the community baseline."""

    _locked(
        "test protocol-parity",
        lambda **kwargs: invoke_protocol_parity(kwargs["layout"], kwargs["workspace_options"], comparison_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("community-core-coverage")
@_common_options
@click.option("--test-run-variant", default=None, help=TEST_RUN_VARIANT_HELP)
@click.option("--baseline-variant", default=None, help=BASELINE_VARIANT_HELP)
@click.option("--rest-coverage-budget", type=click.Choice(["smoke", "contract", "contract-stress"]), default="contract")
@click.option("--rest-stress-budget", type=click.Choice(["off", "smoke", "soak"]), default="smoke")
def test_community_core_coverage(
    *,
    test_run_variant: str | None,
    baseline_variant: str | None,
    rest_coverage_budget: str,
    rest_stress_budget: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run community-core coverage checks."""

    coverage_options = CommunityCoverageOptions(
        test_run_variant=test_run_variant,
        baseline_variant=baseline_variant,
        rest_coverage_budget=rest_coverage_budget,
        rest_stress_budget=rest_stress_budget,
    )
    _locked(
        "test community-core-coverage",
        lambda **kwargs: invoke_community_core_coverage(kwargs["layout"], kwargs["workspace_options"], coverage_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("live-e2e")
@_common_options
@_live_e2e_options
def test_live_e2e(
    *,
    live_options: LiveE2eOptions,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run aggregate live E2E suites."""

    _locked(
        "test live-e2e",
        lambda **kwargs: invoke_live_e2e_suite(kwargs["layout"], kwargs["workspace_options"], live_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("overnight-local-hammer")
@_common_options
@click.option("--until-local", default=None, help="Local wall-clock deadline, for example 2026-05-30T05:00:00.")
@click.option("--timezone", "timezone_str", default="Europe/Berlin", show_default=True)
@click.option("--max-cycles", default=0, show_default=True, type=int, help="Maximum full smoke-to-heavy cycles; 0 means until deadline.")
@click.option("--cycle-pause-seconds", default=0.0, show_default=True, type=float)
@click.option("--dry-run", is_flag=True, help="Write the planned campaign matrix without running phases.")
@click.option("--live-wire-inputs-file", default=None, help="Runtime live-wire JSON with local_package_install settings.")
@click.option("--release-version", default="0.7.3-rc.1", show_default=True)
@click.option("--clean", is_flag=True, help="Clean package outputs before installer materialization.")
@click.option("--skip-build", is_flag=True, help="Reuse existing package artifacts during installer materialization.")
@click.option("--p2p-bind-interface-name", default="hide.me", show_default=True)
@click.option("--godzilla-p2p-bind-interface-address", default=None, help="Explicit LAN IPv4 address for Godzilla swarm binding.")
@click.option("--profile-symbols-required/--no-profile-symbols-required", default=True, show_default=True)
def test_overnight_local_hammer(
    *,
    until_local: str | None,
    timezone_str: str,
    max_cycles: int,
    cycle_pause_seconds: float,
    dry_run: bool,
    live_wire_inputs_file: str | None,
    release_version: str,
    clean: bool,
    skip_build: bool,
    p2p_bind_interface_name: str,
    godzilla_p2p_bind_interface_address: str | None,
    profile_symbols_required: bool,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run the installer-backed local overnight heavy hammer campaign."""

    campaign_options = LocalHammerCampaignOptions(
        until_local=until_local,
        timezone_str=timezone_str,
        max_cycles=max_cycles,
        cycle_pause_seconds=cycle_pause_seconds,
        dry_run=dry_run,
        live_wire_inputs_file=live_wire_inputs_file,
        release_version=release_version,
        clean=clean,
        skip_build=skip_build,
        p2p_bind_interface_name=p2p_bind_interface_name,
        godzilla_p2p_bind_interface_address=godzilla_p2p_bind_interface_address,
        profile_symbols_required=profile_symbols_required,
    )
    _locked(
        "test overnight-local-hammer",
        lambda **kwargs: invoke_local_hammer_campaign(kwargs["layout"], kwargs["workspace_options"], campaign_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("release-campaign")
@_common_options
@click.option("--campaign", default="emulebb-0.7.3", show_default=True, help="Release campaign manifest id.")
@click.option("--phase", default=None, help="Optional strict taxonomy phase id to show.")
@click.option("--template", "show_template", is_flag=True, help="Show the generic eMuleBB release campaign template.")
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON instead of a terminal table.")
@click.option("--execute", is_flag=True, help="Run the selected campaign commands instead of only reporting evidence.")
@click.option("--include-nonblocking", is_flag=True, help="Include nonblocking optional campaign scenarios during execution.")
@click.option("--continue-on-failure", is_flag=True, help="Run remaining campaign commands after a failure.")
@click.option("--dry-run", is_flag=True, help="Write an execution plan report without running campaign commands.")
@click.option("--skip-pre-run-cleanup", is_flag=True, help="Do not prune old generated outcomes before executing campaign commands.")
@click.option("--test-network", type=click.Choice(["default", "offline", "lan", "vpn", "all"]), default="default", show_default=True)
@click.option("--live-wire-inputs-file", default=None, help="Runtime live-wire search/download input JSON for campaign commands.")
@click.option("--radarr-movie-root", default=None, help="Radarr-visible movie root for campaign live checks.")
@click.option("--sonarr-series-root", default=None, help="Sonarr-visible series root for campaign live checks.")
@click.option("--acquisition-timeout-minutes", default=None, type=float, help="Arr acquisition timeout forwarded to campaign live checks.")
@click.option("--p2p-bind-interface-name", default="hide.me", show_default=True)
@click.option("--skip-live-seed-refresh", is_flag=True, help="Reuse the existing live seed state in campaign live checks.")
def test_release_campaign(
    *,
    campaign: str,
    phase: str | None,
    show_template: bool,
    json_output: bool,
    execute: bool,
    include_nonblocking: bool,
    continue_on_failure: bool,
    dry_run: bool,
    skip_pre_run_cleanup: bool,
    test_network: str,
    live_wire_inputs_file: str | None,
    radarr_movie_root: str | None,
    sonarr_series_root: str | None,
    acquisition_timeout_minutes: float | None,
    p2p_bind_interface_name: str,
    skip_live_seed_refresh: bool,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Show or run release campaign phases, feature flows, and evidence status."""

    campaign_options = ReleaseCampaignOptions(
        campaign=campaign,
        test_network=test_network,
        phase=phase,
        show_template=show_template,
        json_output=json_output,
        execute=execute,
        include_nonblocking=include_nonblocking,
        continue_on_failure=continue_on_failure,
        dry_run=dry_run,
        pre_run_cleanup=not skip_pre_run_cleanup,
        live_wire_inputs_file=live_wire_inputs_file,
        radarr_movie_root=radarr_movie_root,
        sonarr_series_root=sonarr_series_root,
        acquisition_timeout_minutes=acquisition_timeout_minutes,
        p2p_bind_interface_name=p2p_bind_interface_name,
        skip_live_seed_refresh=skip_live_seed_refresh,
    )
    _locked(
        "test release-campaign",
        lambda **kwargs: invoke_release_campaign(kwargs["layout"], kwargs["workspace_options"], campaign_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("certification")
@_common_options
@click.option("--profile", type=click.Choice(["fast", "overnight"]), default="fast", show_default=True)
@click.option("--test-network", type=click.Choice(["default", "offline", "lan", "vpn", "all"]), default="default", show_default=True)
@click.option("--live-wire-inputs-file", default=None, help="Runtime live-wire search/download input JSON.")
@click.option("--radarr-movie-root", default=None, help="Radarr-visible movie root for Radarr import live checks.")
@click.option("--sonarr-series-root", default=None, help="Sonarr-visible series root for Sonarr import live checks.")
@click.option("--acquisition-timeout-minutes", default=None, type=float, help="Arr acquisition timeout forwarded to live suites.")
@click.option("--p2p-bind-interface-name", default="hide.me", show_default=True)
@click.option("--skip-live-seed-refresh", is_flag=True, help="Reuse the existing live seed state.")
@click.option("--continue-on-failure", is_flag=True, help="Run remaining certification steps after a failed or inconclusive step.")
@click.option("--skip-pre-run-cleanup", is_flag=True, help="Do not prune old generated outcomes before the certification run.")
def test_certification(
    *,
    profile: str,
    test_network: str,
    live_wire_inputs_file: str | None,
    radarr_movie_root: str | None,
    sonarr_series_root: str | None,
    acquisition_timeout_minutes: float | None,
    p2p_bind_interface_name: str,
    skip_live_seed_refresh: bool,
    continue_on_failure: bool,
    skip_pre_run_cleanup: bool,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run the release-certification test matrix."""

    certification_options = CertificationOptions(
        profile=profile,
        test_network=test_network,
        pre_run_cleanup=not skip_pre_run_cleanup,
        continue_on_failure=continue_on_failure,
        live_wire_inputs_file=live_wire_inputs_file,
        radarr_movie_root=radarr_movie_root,
        sonarr_series_root=sonarr_series_root,
        acquisition_timeout_minutes=acquisition_timeout_minutes,
        p2p_bind_interface_name=p2p_bind_interface_name,
        skip_live_seed_refresh=skip_live_seed_refresh,
    )
    _locked(
        "test certification",
        lambda **kwargs: invoke_certification(kwargs["layout"], kwargs["workspace_options"], certification_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("amutorrent-session")
@_common_options
@click.option("--live-network", is_flag=True, help="Allow the aMuTorrent session to use the live network.")
def test_amutorrent_session(
    *,
    live_network: bool,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Start an interactive aMuTorrent test session."""

    session_options = AmutorrentSessionOptions(live_network=live_network)
    _locked(
        "test amutorrent-session",
        lambda **kwargs: invoke_amutorrent_interactive_session(kwargs["layout"], kwargs["workspace_options"], session_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("fake-kad-trust-soak")
@_common_options
@click.option("--live-wire-inputs-file", default=None, help="Runtime live-wire search input JSON.")
@click.option("--test-network", type=click.Choice(["vpn", "all"]), default="vpn", show_default=True)
@click.option("--keep-artifacts", is_flag=True, help="Keep source artifacts after the soak run.")
@click.option("--keep-running", is_flag=True, help="Leave eMule running when the soak passes.")
@click.option("--skip-live-seed-refresh", is_flag=True, help="Reuse the existing live seed state.")
@click.option("--duration-seconds", default=3 * 60 * 60, show_default=True, type=float)
@click.option("--cycle-pause-seconds", default=10.0, show_default=True, type=float)
@click.option("--search-observation-timeout-seconds", default=90.0, show_default=True, type=float)
@click.option("--resource-sample-interval-seconds", default=60.0, show_default=True, type=float)
@click.option("--min-result-rows", default=1, show_default=True, type=int)
@click.option("--min-kad-publish-info-rows", default=1, show_default=True, type=int)
@click.option("--max-failed-cycles", default=0, show_default=True, type=int)
@click.option("--require-kad-connected", is_flag=True, help="Require full Kad connected state before soaking.")
@click.option("--p2p-bind-interface-name", default="hide.me", show_default=True)
def test_fake_kad_trust_soak(
    *,
    live_wire_inputs_file: str | None,
    test_network: str,
    keep_artifacts: bool,
    keep_running: bool,
    skip_live_seed_refresh: bool,
    duration_seconds: float,
    cycle_pause_seconds: float,
    search_observation_timeout_seconds: float,
    resource_sample_interval_seconds: float,
    min_result_rows: int,
    min_kad_publish_info_rows: int,
    max_failed_cycles: int,
    require_kad_connected: bool,
    p2p_bind_interface_name: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run a focused fake-file risk and Kad trust live soak."""

    soak_options = FakeKadTrustSoakOptions(
        live_wire_inputs_file=live_wire_inputs_file,
        test_network=test_network,
        keep_artifacts=keep_artifacts,
        keep_running=keep_running,
        skip_live_seed_refresh=skip_live_seed_refresh,
        duration_seconds=duration_seconds,
        cycle_pause_seconds=cycle_pause_seconds,
        search_observation_timeout_seconds=search_observation_timeout_seconds,
        resource_sample_interval_seconds=resource_sample_interval_seconds,
        min_result_rows=min_result_rows,
        min_kad_publish_info_rows=min_kad_publish_info_rows,
        max_failed_cycles=max_failed_cycles,
        require_kad_connected=require_kad_connected,
        p2p_bind_interface_name=p2p_bind_interface_name,
    )
    _locked(
        "test fake-kad-trust-soak",
        lambda **kwargs: invoke_fake_kad_trust_soak(kwargs["layout"], kwargs["workspace_options"], soak_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("amutorrent-clean-startup")
@_common_options
@click.option("--live-wire-inputs-file", default=None, help="Runtime live-wire search/download input JSON.")
@click.option("--test-network", type=click.Choice(["vpn", "all"]), default="vpn", show_default=True)
@click.option("--rest-webserver-scheme", type=click.Choice(["http", "https"]), default="https", show_default=True)
@click.option("--keep-artifacts", is_flag=True, help="Keep source artifacts after the clean-startup run.")
@click.option("--ready-timeout-seconds", default=60.0, show_default=True, type=float)
@click.option("--network-ready-timeout-seconds", default=180.0, show_default=True, type=float)
@click.option("--search-observation-timeout-seconds", default=120.0, show_default=True, type=float)
@click.option("--p2p-bind-interface-name", default="hide.me", show_default=True)
def test_amutorrent_clean_startup(
    *,
    live_wire_inputs_file: str | None,
    test_network: str,
    rest_webserver_scheme: str,
    keep_artifacts: bool,
    ready_timeout_seconds: float,
    network_ready_timeout_seconds: float,
    search_observation_timeout_seconds: float,
    p2p_bind_interface_name: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run the automated aMuTorrent first-run wizard live proof."""

    clean_options = AmutorrentCleanStartupOptions(
        live_wire_inputs_file=live_wire_inputs_file,
        test_network=test_network,
        rest_webserver_scheme=rest_webserver_scheme,
        keep_artifacts=keep_artifacts,
        ready_timeout_seconds=ready_timeout_seconds,
        network_ready_timeout_seconds=network_ready_timeout_seconds,
        search_observation_timeout_seconds=search_observation_timeout_seconds,
        p2p_bind_interface_name=p2p_bind_interface_name,
    )
    _locked(
        "test amutorrent-clean-startup",
        lambda **kwargs: invoke_amutorrent_clean_startup(kwargs["layout"], kwargs["workspace_options"], clean_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("amutorrent-resilience")
@_common_options
@click.option("--live-wire-inputs-file", default=None, help="Runtime live-wire search/download input JSON.")
@click.option("--test-network", type=click.Choice(["vpn", "all"]), default="vpn", show_default=True)
@click.option("--rest-webserver-scheme", type=click.Choice(["http", "https"]), default="https", show_default=True)
@click.option("--keep-artifacts", is_flag=True, help="Keep source artifacts after the resilience run.")
@click.option("--ready-timeout-seconds", default=60.0, show_default=True, type=float)
@click.option("--network-ready-timeout-seconds", default=180.0, show_default=True, type=float)
@click.option("--search-observation-timeout-seconds", default=120.0, show_default=True, type=float)
@click.option("--reconnect-timeout-seconds", default=120.0, show_default=True, type=float)
@click.option("--p2p-bind-interface-name", default="hide.me", show_default=True)
def test_amutorrent_resilience(
    *,
    live_wire_inputs_file: str | None,
    test_network: str,
    rest_webserver_scheme: str,
    keep_artifacts: bool,
    ready_timeout_seconds: float,
    network_ready_timeout_seconds: float,
    search_observation_timeout_seconds: float,
    reconnect_timeout_seconds: float,
    p2p_bind_interface_name: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run the automated aMuTorrent resilience live proof."""

    resilience_options = AmutorrentResilienceOptions(
        live_wire_inputs_file=live_wire_inputs_file,
        test_network=test_network,
        rest_webserver_scheme=rest_webserver_scheme,
        keep_artifacts=keep_artifacts,
        ready_timeout_seconds=ready_timeout_seconds,
        network_ready_timeout_seconds=network_ready_timeout_seconds,
        search_observation_timeout_seconds=search_observation_timeout_seconds,
        reconnect_timeout_seconds=reconnect_timeout_seconds,
        p2p_bind_interface_name=p2p_bind_interface_name,
    )
    _locked(
        "test amutorrent-resilience",
        lambda **kwargs: invoke_amutorrent_resilience(kwargs["layout"], kwargs["workspace_options"], resilience_options),
    )(workspace_options=workspace_options, layout=layout)


@test.command("amutorrent-emulebb-ui")
@_common_options
@click.option("--live-wire-inputs-file", default=None, help="Runtime live-wire search/download input JSON.")
@click.option("--test-network", type=click.Choice(["vpn", "all"]), default="vpn", show_default=True)
@click.option("--rest-webserver-scheme", type=click.Choice(["http", "https"]), default="https", show_default=True)
@click.option("--keep-artifacts", is_flag=True, help="Keep source artifacts after the eMuleBB UI run.")
@click.option("--ready-timeout-seconds", default=60.0, show_default=True, type=float)
@click.option("--network-ready-timeout-seconds", default=180.0, show_default=True, type=float)
@click.option("--search-observation-timeout-seconds", default=120.0, show_default=True, type=float)
@click.option("--p2p-bind-interface-name", default="hide.me", show_default=True)
def test_amutorrent_emulebb_ui(
    *,
    live_wire_inputs_file: str | None,
    test_network: str,
    rest_webserver_scheme: str,
    keep_artifacts: bool,
    ready_timeout_seconds: float,
    network_ready_timeout_seconds: float,
    search_observation_timeout_seconds: float,
    p2p_bind_interface_name: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run the automated aMuTorrent eMuleBB UI live proof."""

    ui_options = AmutorrentEmulebbUiOptions(
        live_wire_inputs_file=live_wire_inputs_file,
        test_network=test_network,
        rest_webserver_scheme=rest_webserver_scheme,
        keep_artifacts=keep_artifacts,
        ready_timeout_seconds=ready_timeout_seconds,
        network_ready_timeout_seconds=network_ready_timeout_seconds,
        search_observation_timeout_seconds=search_observation_timeout_seconds,
        p2p_bind_interface_name=p2p_bind_interface_name,
    )
    _locked(
        "test amutorrent-emulebb-ui",
        lambda **kwargs: invoke_amutorrent_emulebb_ui(kwargs["layout"], kwargs["workspace_options"], ui_options),
    )(workspace_options=workspace_options, layout=layout)


@main.command()
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected build outputs before building.")
@click.option("--variant", "app_variants", multiple=True, help=APP_VARIANT_BUILD_HELP)
@click.option("--test-run-variant", default=None, help=TEST_RUN_VARIANT_HELP)
def full(
    *,
    clean: bool,
    app_variants: tuple[str, ...],
    test_run_variant: str | None,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Run build all, test all, and a workspace summary."""

    build_options = BuildTestsOptions(clean=clean, test_run_variant=test_run_variant)

    def run_full(**kwargs: Any) -> None:
        invoke_build_libs(kwargs["layout"], kwargs["workspace_options"], clean=clean)
        invoke_build_apps(kwargs["layout"], kwargs["workspace_options"], clean=clean, app_variant_names=app_variants)
        invoke_build_tests(kwargs["layout"], kwargs["workspace_options"], build_options)
        invoke_test_runs(kwargs["layout"], kwargs["workspace_options"])
        write_workspace_summary(kwargs["layout"])

    _locked("full", run_full)(workspace_options=workspace_options, layout=layout)


@main.command("package-release")
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected package build outputs before building.")
@click.option(
    "--release-version",
    default="0.7.3-rc.1",
    show_default=True,
    help="Release version in MAJOR.MINOR.PATCH[-rc.N|-beta.N|-nightly.YYYYMMDD.SHA] form.",
)
def package_release(
    *,
    clean: bool,
    release_version: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build the main app and create release package artifacts."""

    package_options = ReleasePackageOptions(release_version=release_version, clean=clean)
    _locked(
        "package release",
        lambda **kwargs: create_release_package(kwargs["layout"], kwargs["workspace_options"], package_options),
    )(workspace_options=workspace_options, layout=layout)


@main.command("package-amutorrent")
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected package build outputs before building.")
@click.option(
    "--release-version",
    default="0.7.3-rc.1",
    show_default=True,
    help="Release version in MAJOR.MINOR.PATCH[-rc.N|-beta.N|-nightly.YYYYMMDD.SHA] form.",
)
def package_amutorrent(
    *,
    clean: bool,
    release_version: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build the optional aMuTorrent controller package artifact."""

    package_options = AmutorrentPackageOptions(release_version=release_version, clean=clean)
    _locked(
        "package amutorrent",
        lambda **kwargs: create_amutorrent_package(kwargs["layout"], kwargs["workspace_options"], package_options),
    )(workspace_options=workspace_options, layout=layout)


@main.command("package-amule")
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected package build outputs before building.")
@click.option(
    "--release-version",
    default="3.0.0-emulebb.1",
    show_default=True,
    help="aMule release version in MAJOR.MINOR.PATCH-emulebb.N form.",
)
def package_amule(
    *,
    clean: bool,
    release_version: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build the optional aMule Windows package artifact."""

    package_options = AmulePackageOptions(release_version=release_version, clean=clean)
    _locked(
        "package amule",
        lambda **kwargs: create_amule_package(kwargs["layout"], kwargs["workspace_options"], package_options),
    )(workspace_options=workspace_options, layout=layout)


@main.command("package-miniupnpc")
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected package build outputs before building.")
@click.option(
    "--release-version",
    default="2.2.3-emulebb.1",
    show_default=True,
    help="MiniUPnP release version in MAJOR.MINOR.PATCH-emulebb.N form.",
)
def package_miniupnpc(
    *,
    clean: bool,
    release_version: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build the optional MiniUPnP upnpc Windows package artifact."""

    package_options = MiniupnpcPackageOptions(release_version=release_version, clean=clean)
    _locked(
        "package miniupnpc",
        lambda **kwargs: create_miniupnpc_package(kwargs["layout"], kwargs["workspace_options"], package_options),
    )(workspace_options=workspace_options, layout=layout)


@main.command("install-local-package")
@_common_options
@click.option("--clean", is_flag=True, help="Clean selected package build outputs before building.")
@click.option("--skip-build", is_flag=True, help="Deploy existing package artifacts without rebuilding them.")
@click.option("--live-wire-inputs-file", default=None, help="Ignored live-wire JSON containing local_package_install settings.")
@click.option(
    "--release-version",
    default="0.7.3-rc.1",
    show_default=True,
    help="Release version in MAJOR.MINOR.PATCH[-rc.N|-beta.N|-nightly.YYYYMMDD.SHA] form.",
)
def install_local_package_command(
    *,
    clean: bool,
    skip_build: bool,
    live_wire_inputs_file: str | None,
    release_version: str,
    workspace_options: WorkspaceOptions,
    layout,
) -> None:
    """Build and refresh a local package install from ignored live-wire JSON."""

    install_options = LocalPackageInstallOptions(
        release_version=release_version,
        clean=clean,
        skip_build=skip_build,
        live_wire_inputs_file=live_wire_inputs_file,
    )
    _locked(
        "install local-package",
        lambda **kwargs: install_local_package(kwargs["layout"], kwargs["workspace_options"], install_options),
    )(workspace_options=workspace_options, layout=layout)


@main.command("env-check")
@_common_options
def env_check(*, workspace_options: WorkspaceOptions, layout) -> None:
    """Verify basic tool discovery and manifest loading."""

    from .validation import env_check as run_env_check

    _locked("env-check", lambda **kwargs: run_env_check(kwargs["layout"]))(
        workspace_options=workspace_options,
        layout=layout,
    )
