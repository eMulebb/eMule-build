"""First-class release campaign execution for eMuleBB."""

from __future__ import annotations

import json
import shlex
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any
import importlib.util

from .artifact_names import release_campaign_result_file_name, utc_run_id
from .certification import invoke_certification
from .cleanup import CleanupFailedError, CleanupRunSummary, cleanup_summary_payload, run_pre_test_cleanup
from .config import (
    AmutorrentCleanStartupOptions,
    AmutorrentEmulebbUiOptions,
    AmutorrentPackageOptions,
    AmutorrentResilienceOptions,
    CampaignScenarioOptions,
    CertificationOptions,
    CommunityCoverageOptions,
    LiveE2eOptions,
    PythonTestOptions,
    ReleaseCampaignOptions,
    ReleasePackageOptions,
    VariantComparisonOptions,
    WorkspaceOptions,
)
from .campaign_scenario_runner import invoke_campaign_scenario
from .layout import WorkspaceLayout
from .process import get_python_invocation, run_native
from .python_tests import invoke_python_tests
from .release import create_amutorrent_package, create_release_package
from .test_runs import (
    invoke_amutorrent_clean_startup,
    invoke_amutorrent_emulebb_ui,
    invoke_amutorrent_resilience,
    invoke_community_core_coverage,
    invoke_live_e2e_suite,
    invoke_protocol_parity,
    invoke_test_runs,
)
from .validation import validate_workspace
from .windows_vm_lab import WindowsVmTestOptions, invoke_windows_vm_tests, parse_matrix


_WORKSPACE_VALUE_OPTIONS = {"--config", "--platform"}
_CERTIFICATION_VALUE_OPTIONS = {
    "--profile",
    "--test-network",
    "--live-wire-inputs-file",
    "--radarr-movie-root",
    "--sonarr-series-root",
    "--acquisition-timeout-minutes",
    "--p2p-bind-interface-name",
}
_CERTIFICATION_FLAG_OPTIONS = {"--skip-live-seed-refresh"}
_LIVE_E2E_VALUE_OPTIONS = {
    "--profile",
    "--suite",
    "--test-network",
    "--materialize-test-install-release-version",
    "--live-wire-inputs-file",
    "--radarr-movie-root",
    "--sonarr-series-root",
    "--acquisition-timeout-minutes",
    "--p2p-bind-interface-name",
    "--godzilla-stage",
}
_LIVE_E2E_FLAG_OPTIONS = {
    "--fail-fast",
    "--materialize-test-install",
    "--materialize-test-install-clean",
    "--materialize-test-install-skip-build",
    "--multi-client-require-optional-clients",
    "--skip-live-seed-refresh",
}
_AMUTORRENT_VALUE_OPTIONS = {
    "--live-wire-inputs-file",
    "--test-network",
    "--rest-webserver-scheme",
    "--ready-timeout-seconds",
    "--network-ready-timeout-seconds",
    "--search-observation-timeout-seconds",
    "--p2p-bind-interface-name",
}
_AMUTORRENT_FLAG_OPTIONS = {"--keep-artifacts"}
_WINDOWS_VM_VALUE_OPTIONS = {
    "--config-file",
    "--matrix",
    "--profile",
    "--release-version",
    "--fixture-size-bytes",
    "--local-swarm-mode",
}
_WINDOWS_VM_FLAG_OPTIONS = {"--skip-build", "--keep-running", "--dry-run"}
_CAMPAIGN_SCENARIO_VALUE_OPTIONS = {
    "--scenario",
    "--mode",
    "--release-version",
    "--matrix",
    "--fixture-size-bytes",
    "--swarm-tier",
    "--local-swarm-mode",
}
_CAMPAIGN_SCENARIO_FLAG_OPTIONS = {"--skip-build", "--dry-run"}


@dataclass(frozen=True)
class CampaignScenarioContext:
    """Scenario metadata needed for command-level validation."""

    scenario_id: str
    blocking: bool
    flow_category: str
    execution_mode: str
    execution_modes: tuple[str, ...]
    local_profile: str
    vm_profile: str
    control_bind_scope: str
    amutorrent_bind_scope: str
    p2p_mode: str
    p2p_bind_scope: str
    live_e2e_profile: str
    live_e2e_suite: str


@dataclass(frozen=True)
class CampaignCommandPlan:
    """One deduplicated release campaign command with owning scenarios."""

    command: str
    phase_ids: tuple[str, ...]
    scenario_ids: tuple[str, ...]
    scenario_contexts: tuple[CampaignScenarioContext, ...] = ()


@dataclass
class CampaignCommandResult:
    """Recorded result for one release campaign command."""

    command: str
    phase_ids: tuple[str, ...]
    scenario_ids: tuple[str, ...]
    status: str
    duration_seconds: float
    error: str = ""


class ReleaseCampaignExecutionError(RuntimeError):
    """Raised when a release campaign run finishes with failed commands."""


def invoke_release_campaign(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    campaign_options: ReleaseCampaignOptions,
) -> None:
    """Reports or executes the selected release campaign."""

    if not campaign_options.execute:
        from .test_runs import invoke_release_campaign_report

        invoke_release_campaign_report(layout, campaign_options)
        return

    campaign = _load_campaign(layout.tests_repo_root, campaign_options.campaign)
    plan = build_release_campaign_execution_plan(campaign, campaign_options)
    report_dir = _new_report_dir(layout, campaign_options.campaign)
    report_dir.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(timezone.utc)
    results: list[CampaignCommandResult] = []
    pre_run_cleanup: CleanupRunSummary | None = None
    stop_error: ReleaseCampaignExecutionError | None = None

    try:
        if campaign_options.pre_run_cleanup and not campaign_options.dry_run:
            try:
                pre_run_cleanup = run_pre_test_cleanup(layout)
            except CleanupFailedError as exc:
                pre_run_cleanup = exc.summary
                raise
        for command_plan in plan:
            result = _run_campaign_command(
                layout,
                workspace_options,
                campaign_options,
                command_plan,
            )
            results.append(result)
            _write_report(report_dir, campaign, campaign_options, started_at, plan, results, pre_run_cleanup, status="running")
            if result.status == "failed" and not campaign_options.continue_on_failure:
                stop_error = ReleaseCampaignExecutionError(
                    f"Release campaign command failed: {result.command}: {result.error}"
                )
                break

        status = _aggregate_status(results, dry_run=campaign_options.dry_run)
        _write_report(report_dir, campaign, campaign_options, started_at, plan, results, pre_run_cleanup, status=status)
        print("")
        print(f"Release campaign: {campaign_options.campaign}")
        print(f"Status: {status}")
        print(f"Commands: {len(results)}/{len(plan)}")
        print(f"Report: {report_dir / release_campaign_result_file_name()}")
        if stop_error is not None:
            raise stop_error
        if status == "failed":
            raise ReleaseCampaignExecutionError(f"Release campaign '{campaign_options.campaign}' completed with failures.")
    except Exception:
        status = _aggregate_status(results, dry_run=campaign_options.dry_run) if results else "failed"
        _write_report(report_dir, campaign, campaign_options, started_at, plan, results, pre_run_cleanup, status=status)
        print(f"Release campaign report: {report_dir / release_campaign_result_file_name()}")
        raise


def build_release_campaign_execution_plan(
    campaign: dict[str, Any],
    campaign_options: ReleaseCampaignOptions,
) -> tuple[CampaignCommandPlan, ...]:
    """Builds a deduplicated command plan from a release campaign manifest."""

    command_rows: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for phase in campaign.get("phases", []):
        phase_id = str(phase.get("id", ""))
        if campaign_options.phase and phase_id != campaign_options.phase:
            continue
        for scenario in phase.get("scenarios", []):
            if not _scenario_selected(scenario, campaign_options):
                continue
            command = _selected_scenario_command(scenario, campaign_options)
            if not command:
                continue
            _assert_supported_command(command)
            if command not in command_rows:
                command_rows[command] = {"phase_ids": set(), "scenario_ids": set(), "scenario_contexts": []}
                order.append(command)
            phase_ids = command_rows[command]["phase_ids"]
            scenario_ids = command_rows[command]["scenario_ids"]
            scenario_contexts = command_rows[command]["scenario_contexts"]
            assert isinstance(phase_ids, set)
            assert isinstance(scenario_ids, set)
            assert isinstance(scenario_contexts, list)
            phase_ids.add(phase_id)
            scenario_id = str(scenario.get("id", ""))
            scenario_ids.add(scenario_id)
            scenario_contexts.append(
                CampaignScenarioContext(
                    scenario_id=scenario_id,
                    blocking=bool(scenario.get("blocking", True)),
                    flow_category=str(scenario.get("flowCategory") or ""),
                    execution_mode=str(scenario.get("executionMode") or ""),
                    execution_modes=tuple(str(mode) for mode in scenario.get("executionModes", ())),
                    local_profile=str(scenario.get("localProfile") or ""),
                    vm_profile=str(scenario.get("vmProfile") or ""),
                    control_bind_scope=str(scenario.get("controlBindScope") or ""),
                    amutorrent_bind_scope=str(scenario.get("amutorrentBindScope") or ""),
                    p2p_mode=str(scenario.get("p2pMode") or ""),
                    p2p_bind_scope=str(scenario.get("p2pBindScope") or ""),
                    live_e2e_profile=str(scenario.get("liveE2eProfile") or ""),
                    live_e2e_suite=str(scenario.get("liveE2eSuite") or ""),
                )
            )

    if campaign_options.phase and not any(str(phase.get("id", "")) == campaign_options.phase for phase in campaign.get("phases", [])):
        raise ValueError(f"Unknown release campaign phase: {campaign_options.phase}")

    return tuple(
        CampaignCommandPlan(
            command=command,
            phase_ids=tuple(sorted(command_rows[command]["phase_ids"])),  # type: ignore[arg-type]
            scenario_ids=tuple(sorted(command_rows[command]["scenario_ids"])),  # type: ignore[arg-type]
            scenario_contexts=tuple(command_rows[command]["scenario_contexts"]),  # type: ignore[arg-type]
        )
        for command in order
    )


def _scenario_selected(scenario: dict[str, Any], campaign_options: ReleaseCampaignOptions) -> bool:
    if bool(scenario.get("blocking", True)):
        return True
    return campaign_options.include_nonblocking


def _selected_scenario_command(scenario: dict[str, Any], campaign_options: ReleaseCampaignOptions) -> str:
    """Returns the command selected for one campaign scenario."""

    command = ""
    if (
        campaign_options.local_vm_swarm_mode != "manifest"
        and scenario.get("flowCategory") == "local-vm-swarm"
    ):
        command_key = "localCommand" if campaign_options.local_vm_swarm_mode == "local" else "vmCommand"
        command = str(scenario.get(command_key, "")).strip()
        if not command:
            scenario_id = str(scenario.get("id") or "<unknown>")
            raise ValueError(
                f"Release campaign local-vm-swarm scenario {scenario_id} is missing {command_key}."
            )
    else:
        command = str(scenario.get("command", "")).strip()
    if scenario.get("flowCategory") == "local-vm-swarm":
        return _apply_local_vm_swarm_execution_mode(command, campaign_options)
    return command


def _apply_local_vm_swarm_execution_mode(command: str, campaign_options: ReleaseCampaignOptions) -> str:
    """Applies the release-level local-swarm plan/execute override to reusable scenario commands."""

    if campaign_options.local_vm_swarm_execution_mode == "manifest" or not command:
        return command
    tokens = _parse_command(command)
    if tokens[3:5] != ["test", "campaign-scenario"]:
        return command
    mode = _option_value(tokens, "--mode")
    if mode not in {"local", "vm"}:
        return command
    if campaign_options.local_vm_swarm_execution_mode == "plan":
        return " ".join(
            _ensure_flag(
                _remove_value_option(tokens, "--local-swarm-mode"),
                "--dry-run",
            )
        )
    tokens = _remove_flag(tokens, "--dry-run")
    if mode == "local":
        return " ".join(_remove_value_option(tokens, "--local-swarm-mode"))
    return " ".join(
        _replace_or_append_option(
            tokens,
            "--local-swarm-mode",
            "execute",
        )
    )


def _replace_or_append_option(tokens: list[str], option: str, value: str) -> list[str]:
    """Returns command tokens with one value option replaced or appended."""

    updated = list(tokens)
    for index, token in enumerate(updated[:-1]):
        if token == option:
            updated[index + 1] = value
            return updated
    updated.extend([option, value])
    return updated


def _remove_value_option(tokens: list[str], option: str) -> list[str]:
    """Returns command tokens with all instances of one value option removed."""

    updated: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token == option:
            skip_next = True
            continue
        updated.append(token)
    return updated


def _remove_flag(tokens: list[str], flag: str) -> list[str]:
    """Returns command tokens with all instances of one flag removed."""

    return [token for token in tokens if token != flag]


def _ensure_flag(tokens: list[str], flag: str) -> list[str]:
    """Returns command tokens containing one flag exactly once."""

    updated = _remove_flag(tokens, flag)
    updated.append(flag)
    return updated


def _run_campaign_command(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    campaign_options: ReleaseCampaignOptions,
    command_plan: CampaignCommandPlan,
) -> CampaignCommandResult:
    started = time.monotonic()
    status = "planned" if campaign_options.dry_run else "passed"
    error = ""
    try:
        _validate_command_plan_context(layout, campaign_options, command_plan)
        if not campaign_options.dry_run:
            _dispatch_supported_command(layout, workspace_options, campaign_options, command_plan.command)
    except Exception as exc:
        status = "failed"
        error = str(exc)
    return CampaignCommandResult(
        command=command_plan.command,
        phase_ids=command_plan.phase_ids,
        scenario_ids=command_plan.scenario_ids,
        status=status,
        duration_seconds=round(time.monotonic() - started, 3),
        error=error,
    )


def _dispatch_supported_command(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    campaign_options: ReleaseCampaignOptions,
    command: str,
) -> None:
    tokens = _parse_command(command)
    if tokens[:3] == ["python", "-m", "emule_workspace"]:
        _dispatch_workspace_command(layout, workspace_options, campaign_options, tokens[3:])
        return
    if len(tokens) == 2 and tokens[0] == "python" and tokens[1].replace("/", "\\") == r"repos\emulebb-tooling\ci\check-clean-worktree.py":
        python = get_python_invocation()
        run_native(
            python.command([layout.emule_workspace_root / tokens[1]]),
            label="release clean worktree provenance",
            cwd=layout.emule_workspace_root,
            env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
        )
        return
    raise ValueError(f"Unsupported release campaign command: {command}")


def _dispatch_workspace_command(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    campaign_options: ReleaseCampaignOptions,
    tokens: list[str],
) -> None:
    if tokens == ["validate"]:
        validate_workspace(layout)
        return
    if tokens[:2] == ["test", "certification"]:
        invoke_certification(layout, workspace_options, _certification_options(campaign_options, tokens))
        return
    if tokens[:2] == ["test", "python"]:
        invoke_python_tests(layout, PythonTestOptions(quiet="--quiet" in tokens))
        return
    if tokens[:2] == ["test", "protocol-parity"]:
        invoke_protocol_parity(layout, workspace_options, VariantComparisonOptions())
        return
    if tokens[:2] == ["test", "community-core-coverage"]:
        invoke_community_core_coverage(
            layout,
            workspace_options,
            CommunityCoverageOptions(
                rest_coverage_budget=_option_value(tokens, "--rest-coverage-budget") or "contract",
                rest_stress_budget=_option_value(tokens, "--rest-stress-budget") or "smoke",
            ),
        )
        return
    if tokens[:2] == ["test", "all"]:
        invoke_test_runs(layout, workspace_options)
        return
    if tokens[:2] == ["test", "live-e2e"]:
        invoke_live_e2e_suite(
            layout,
            _workspace_options_from_tokens(workspace_options, tokens),
            _live_options_from_tokens(campaign_options, tokens),
        )
        return
    if tokens[:2] == ["test", "windows-vm"]:
        invoke_windows_vm_tests(
            layout,
            _workspace_options_from_tokens(workspace_options, tokens),
            _windows_vm_options_from_tokens(tokens),
        )
        return
    if tokens[:2] == ["test", "campaign-scenario"]:
        invoke_campaign_scenario(
            layout,
            _workspace_options_from_tokens(workspace_options, tokens),
            _campaign_scenario_options_from_tokens(tokens),
        )
        return
    if tokens[:2] == ["test", "amutorrent-clean-startup"]:
        invoke_amutorrent_clean_startup(
            layout,
            _workspace_options_from_tokens(workspace_options, tokens),
            _amutorrent_clean_options_from_tokens(campaign_options, tokens),
        )
        return
    if tokens[:2] == ["test", "amutorrent-emulebb-ui"]:
        invoke_amutorrent_emulebb_ui(
            layout,
            _workspace_options_from_tokens(workspace_options, tokens),
            _amutorrent_ui_options_from_tokens(campaign_options, tokens),
        )
        return
    if tokens[:2] == ["test", "amutorrent-resilience"]:
        invoke_amutorrent_resilience(
            layout,
            _workspace_options_from_tokens(workspace_options, tokens),
            _amutorrent_resilience_options_from_tokens(campaign_options, tokens),
        )
        return
    if tokens and tokens[0] == "package-release":
        create_release_package(
            layout,
            _workspace_options_from_tokens(workspace_options, tokens),
            ReleasePackageOptions(),
        )
        return
    if tokens and tokens[0] == "package-amutorrent":
        create_amutorrent_package(
            layout,
            _workspace_options_from_tokens(workspace_options, tokens),
            AmutorrentPackageOptions(),
        )
        return
    raise ValueError(f"Unsupported emule_workspace release campaign command: {' '.join(tokens)}")


def _certification_options(campaign_options: ReleaseCampaignOptions, tokens: list[str]) -> CertificationOptions:
    return CertificationOptions(
        profile=_option_value(tokens, "--profile") or "fast",
        test_network=_option_value(tokens, "--test-network") or campaign_options.test_network,
        pre_run_cleanup=False,
        continue_on_failure=campaign_options.continue_on_failure,
        live_wire_inputs_file=_option_value(tokens, "--live-wire-inputs-file") or campaign_options.live_wire_inputs_file,
        radarr_movie_root=_option_value(tokens, "--radarr-movie-root") or campaign_options.radarr_movie_root,
        sonarr_series_root=_option_value(tokens, "--sonarr-series-root") or campaign_options.sonarr_series_root,
        acquisition_timeout_minutes=_option_float(tokens, "--acquisition-timeout-minutes")
        or campaign_options.acquisition_timeout_minutes,
        p2p_bind_interface_name=_option_value(tokens, "--p2p-bind-interface-name") or campaign_options.p2p_bind_interface_name,
        skip_live_seed_refresh="--skip-live-seed-refresh" in tokens or campaign_options.skip_live_seed_refresh,
    )


def _live_options_from_tokens(campaign_options: ReleaseCampaignOptions, tokens: list[str]) -> LiveE2eOptions:
    return LiveE2eOptions(
        profile=_option_value(tokens, "--profile") or "default",
        suites=tuple(_option_values(tokens, "--suite")),
        test_network=_option_value(tokens, "--test-network") or campaign_options.test_network,
        pre_run_cleanup=False,
        fail_fast="--fail-fast" in tokens,
        materialize_test_install="--materialize-test-install" in tokens,
        materialize_test_install_release_version=_option_value(tokens, "--materialize-test-install-release-version") or "0.7.3-rc.1",
        materialize_test_install_clean="--materialize-test-install-clean" in tokens,
        materialize_test_install_skip_build="--materialize-test-install-skip-build" in tokens,
        live_wire_inputs_file=_option_value(tokens, "--live-wire-inputs-file") or campaign_options.live_wire_inputs_file,
        radarr_movie_root=_option_value(tokens, "--radarr-movie-root") or campaign_options.radarr_movie_root,
        sonarr_series_root=_option_value(tokens, "--sonarr-series-root") or campaign_options.sonarr_series_root,
        acquisition_timeout_minutes=_option_float(tokens, "--acquisition-timeout-minutes")
        or campaign_options.acquisition_timeout_minutes,
        p2p_bind_interface_name=_option_value(tokens, "--p2p-bind-interface-name") or campaign_options.p2p_bind_interface_name,
        multi_client_require_optional_clients="--multi-client-require-optional-clients" in tokens,
        godzilla_stage=_option_value(tokens, "--godzilla-stage"),
        skip_live_seed_refresh="--skip-live-seed-refresh" in tokens or campaign_options.skip_live_seed_refresh,
    )


def _amutorrent_clean_options_from_tokens(
    campaign_options: ReleaseCampaignOptions,
    tokens: list[str],
) -> AmutorrentCleanStartupOptions:
    return AmutorrentCleanStartupOptions(
        live_wire_inputs_file=_option_value(tokens, "--live-wire-inputs-file") or campaign_options.live_wire_inputs_file,
        test_network=_vpn_command_test_network(campaign_options, tokens),
        rest_webserver_scheme=_option_value(tokens, "--rest-webserver-scheme") or "https",
        keep_artifacts="--keep-artifacts" in tokens,
        ready_timeout_seconds=_option_float(tokens, "--ready-timeout-seconds") or 60.0,
        network_ready_timeout_seconds=_option_float(tokens, "--network-ready-timeout-seconds") or 180.0,
        search_observation_timeout_seconds=_option_float(tokens, "--search-observation-timeout-seconds") or 120.0,
        p2p_bind_interface_name=_option_value(tokens, "--p2p-bind-interface-name") or campaign_options.p2p_bind_interface_name,
    )


def _amutorrent_ui_options_from_tokens(
    campaign_options: ReleaseCampaignOptions,
    tokens: list[str],
) -> AmutorrentEmulebbUiOptions:
    return AmutorrentEmulebbUiOptions(
        live_wire_inputs_file=_option_value(tokens, "--live-wire-inputs-file") or campaign_options.live_wire_inputs_file,
        test_network=_vpn_command_test_network(campaign_options, tokens),
        rest_webserver_scheme=_option_value(tokens, "--rest-webserver-scheme") or "https",
        keep_artifacts="--keep-artifacts" in tokens,
        ready_timeout_seconds=_option_float(tokens, "--ready-timeout-seconds") or 60.0,
        network_ready_timeout_seconds=_option_float(tokens, "--network-ready-timeout-seconds") or 180.0,
        search_observation_timeout_seconds=_option_float(tokens, "--search-observation-timeout-seconds") or 120.0,
        p2p_bind_interface_name=_option_value(tokens, "--p2p-bind-interface-name") or campaign_options.p2p_bind_interface_name,
    )


def _amutorrent_resilience_options_from_tokens(
    campaign_options: ReleaseCampaignOptions,
    tokens: list[str],
) -> AmutorrentResilienceOptions:
    return AmutorrentResilienceOptions(
        live_wire_inputs_file=_option_value(tokens, "--live-wire-inputs-file") or campaign_options.live_wire_inputs_file,
        test_network=_vpn_command_test_network(campaign_options, tokens),
        rest_webserver_scheme=_option_value(tokens, "--rest-webserver-scheme") or "https",
        keep_artifacts="--keep-artifacts" in tokens,
        ready_timeout_seconds=_option_float(tokens, "--ready-timeout-seconds") or 60.0,
        network_ready_timeout_seconds=_option_float(tokens, "--network-ready-timeout-seconds") or 180.0,
        search_observation_timeout_seconds=_option_float(tokens, "--search-observation-timeout-seconds") or 120.0,
        reconnect_timeout_seconds=_option_float(tokens, "--reconnect-timeout-seconds") or 120.0,
        p2p_bind_interface_name=_option_value(tokens, "--p2p-bind-interface-name") or campaign_options.p2p_bind_interface_name,
    )


def _vpn_command_test_network(campaign_options: ReleaseCampaignOptions, tokens: list[str]) -> str:
    token_value = _option_value(tokens, "--test-network")
    if token_value:
        return token_value
    return "all" if campaign_options.test_network == "all" else "vpn"


def _workspace_options_from_tokens(workspace_options: WorkspaceOptions, tokens: list[str]) -> WorkspaceOptions:
    return workspace_options.model_copy(
        update={
            "configuration": _option_value(tokens, "--config") or workspace_options.configuration,
            "platform": _option_value(tokens, "--platform") or workspace_options.platform,
        }
    )


def _windows_vm_options_from_tokens(tokens: list[str]) -> WindowsVmTestOptions:
    return WindowsVmTestOptions(
        config_file=_option_value(tokens, "--config-file"),
        matrix=parse_matrix(_option_value(tokens, "--matrix") or None),
        profile=_option_value(tokens, "--profile") or "package-smoke",
        release_version=_option_value(tokens, "--release-version") or "0.7.3-rc.1",
        skip_build="--skip-build" in tokens,
        keep_running="--keep-running" in tokens,
        dry_run="--dry-run" in tokens,
        fixture_size_bytes=_option_int(tokens, "--fixture-size-bytes") or 25 * 1024 * 1024,
        local_swarm_mode=_option_value(tokens, "--local-swarm-mode") or "plan",
    )


def _campaign_scenario_options_from_tokens(tokens: list[str]) -> CampaignScenarioOptions:
    scenario = _option_value(tokens, "--scenario")
    if not scenario:
        raise ValueError("Release campaign scenario command requires --scenario.")
    return CampaignScenarioOptions(
        scenario=scenario,
        mode=_option_value(tokens, "--mode") or "local",  # type: ignore[arg-type]
        release_version=_option_value(tokens, "--release-version") or "0.7.3-rc.1",
        skip_build="--skip-build" in tokens,
        dry_run="--dry-run" in tokens,
        fixture_size_bytes=_option_int(tokens, "--fixture-size-bytes") or 25 * 1024 * 1024,
        vm_matrix=parse_matrix(_option_value(tokens, "--matrix") or None),
        swarm_tier=_option_int(tokens, "--swarm-tier") or 1,  # type: ignore[arg-type]
        local_swarm_mode=_option_value(tokens, "--local-swarm-mode") or "plan",  # type: ignore[arg-type]
    )


def _option_value(tokens: list[str], option: str) -> str | None:
    for index, token in enumerate(tokens[:-1]):
        if token == option:
            return tokens[index + 1]
    return None


def _option_values(tokens: list[str], option: str) -> list[str]:
    return [tokens[index + 1] for index, token in enumerate(tokens[:-1]) if token == option]


def _option_float(tokens: list[str], option: str) -> float | None:
    value = _option_value(tokens, option)
    if value is None:
        return None
    return float(value)


def _option_int(tokens: list[str], option: str) -> int | None:
    value = _option_value(tokens, option)
    if value is None:
        return None
    return int(value)


def _assert_supported_command(command: str) -> None:
    _dispatch_shape = _parse_command(command)
    if _dispatch_shape[:3] == ["python", "-m", "emule_workspace"]:
        _validate_workspace_command_tokens(_dispatch_shape[3:])
        return
    if len(_dispatch_shape) == 2 and _dispatch_shape[0] == "python" and _dispatch_shape[1].replace("/", "\\") == r"repos\emulebb-tooling\ci\check-clean-worktree.py":
        return
    raise ValueError(f"Unsupported release campaign command: {command}")


def _validate_workspace_command_tokens(tokens: list[str]) -> None:
    campaign_options = ReleaseCampaignOptions()
    workspace_options = WorkspaceOptions(workspace_root=Path("."))
    if tokens == ["validate"]:
        return
    if tokens[:2] == ["test", "certification"]:
        _validate_options(tokens[2:], value_options=_CERTIFICATION_VALUE_OPTIONS, flag_options=_CERTIFICATION_FLAG_OPTIONS)
        _certification_options(campaign_options, tokens)
        return
    if tokens[:2] == ["test", "python"]:
        _validate_options(tokens[2:], value_options=set(), flag_options={"--quiet"})
        return
    if tokens[:2] == ["test", "protocol-parity"]:
        _validate_options(tokens[2:], value_options=set(), flag_options=set())
        return
    if tokens[:2] == ["test", "community-core-coverage"]:
        _validate_options(tokens[2:], value_options={"--rest-coverage-budget", "--rest-stress-budget"}, flag_options=set())
        return
    if tokens[:2] == ["test", "all"]:
        _validate_options(tokens[2:], value_options=set(), flag_options=set())
        return
    if tokens[:2] == ["test", "live-e2e"]:
        _validate_options(
            tokens[2:],
            value_options=_WORKSPACE_VALUE_OPTIONS | _LIVE_E2E_VALUE_OPTIONS,
            flag_options=_LIVE_E2E_FLAG_OPTIONS,
        )
        _workspace_options_from_tokens(workspace_options, tokens)
        _live_options_from_tokens(campaign_options, tokens)
        return
    if tokens[:2] == ["test", "windows-vm"]:
        _validate_options(
            tokens[2:],
            value_options=_WORKSPACE_VALUE_OPTIONS | _WINDOWS_VM_VALUE_OPTIONS,
            flag_options=_WINDOWS_VM_FLAG_OPTIONS,
        )
        _workspace_options_from_tokens(workspace_options, tokens)
        _windows_vm_options_from_tokens(tokens)
        return
    if tokens[:2] == ["test", "campaign-scenario"]:
        _validate_options(
            tokens[2:],
            value_options=_WORKSPACE_VALUE_OPTIONS | _CAMPAIGN_SCENARIO_VALUE_OPTIONS,
            flag_options=_CAMPAIGN_SCENARIO_FLAG_OPTIONS,
        )
        _workspace_options_from_tokens(workspace_options, tokens)
        _campaign_scenario_options_from_tokens(tokens)
        return
    if tokens[:2] == ["test", "amutorrent-clean-startup"]:
        _validate_options(
            tokens[2:],
            value_options=_WORKSPACE_VALUE_OPTIONS | _AMUTORRENT_VALUE_OPTIONS,
            flag_options=_AMUTORRENT_FLAG_OPTIONS,
        )
        _workspace_options_from_tokens(workspace_options, tokens)
        _amutorrent_clean_options_from_tokens(campaign_options, tokens)
        return
    if tokens[:2] == ["test", "amutorrent-emulebb-ui"]:
        _validate_options(
            tokens[2:],
            value_options=_WORKSPACE_VALUE_OPTIONS | _AMUTORRENT_VALUE_OPTIONS,
            flag_options=_AMUTORRENT_FLAG_OPTIONS,
        )
        _workspace_options_from_tokens(workspace_options, tokens)
        _amutorrent_ui_options_from_tokens(campaign_options, tokens)
        return
    if tokens[:2] == ["test", "amutorrent-resilience"]:
        _validate_options(
            tokens[2:],
            value_options=_WORKSPACE_VALUE_OPTIONS | _AMUTORRENT_VALUE_OPTIONS | {"--reconnect-timeout-seconds"},
            flag_options=_AMUTORRENT_FLAG_OPTIONS,
        )
        _workspace_options_from_tokens(workspace_options, tokens)
        _amutorrent_resilience_options_from_tokens(campaign_options, tokens)
        return
    if tokens and tokens[0] == "package-release":
        _validate_options(tokens[1:], value_options=_WORKSPACE_VALUE_OPTIONS, flag_options=set())
        _workspace_options_from_tokens(workspace_options, tokens)
        return
    if tokens and tokens[0] == "package-amutorrent":
        _validate_options(tokens[1:], value_options=_WORKSPACE_VALUE_OPTIONS, flag_options=set())
        _workspace_options_from_tokens(workspace_options, tokens)
        return
    raise ValueError(f"Unsupported emule_workspace release campaign command: {' '.join(tokens)}")


def _validate_options(tokens: list[str], *, value_options: set[str], flag_options: set[str]) -> None:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            index += 1
            continue
        if token in flag_options:
            index += 1
            continue
        if token in value_options:
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                raise ValueError(f"Release campaign option requires a value: {token}")
            index += 2
            continue
        raise ValueError(f"Unsupported release campaign option: {token}")


def _validate_command_plan_context(
    layout: WorkspaceLayout,
    campaign_options: ReleaseCampaignOptions,
    command_plan: CampaignCommandPlan,
) -> None:
    tokens = _parse_command(command_plan.command)
    if tokens[:5] != ["python", "-m", "emule_workspace", "test", "live-e2e"]:
        return
    requirements = tuple(
        context
        for context in command_plan.scenario_contexts
        if context.blocking and (context.live_e2e_profile or context.live_e2e_suite)
    )
    if not requirements:
        return

    live_e2e_suite = _load_live_e2e_suite_module(layout)
    live_options = _live_options_from_tokens(campaign_options, tokens[3:])
    requested_specs = _resolve_campaign_live_e2e_specs(live_e2e_suite, live_options)
    selected_specs, skipped_suites = live_e2e_suite.filter_suite_specs_for_network(
        requested_specs,
        live_options.test_network,
    )
    requested_names = {spec.name for spec in requested_specs}
    selected_names = {spec.name for spec in selected_specs}
    skipped_by_name = {str(row["name"]): row for row in skipped_suites}
    required_suite_names = sorted(
        {context.live_e2e_suite for context in requirements if context.live_e2e_suite}
    )
    skipped_required = [name for name in required_suite_names if name in skipped_by_name]
    if skipped_required:
        raise ValueError(
            "Release campaign required live E2E suite(s) skipped by "
            f"test_network={live_options.test_network}: {', '.join(skipped_required)}."
        )
    not_requested = [name for name in required_suite_names if name not in requested_names]
    if not_requested:
        raise ValueError(
            "Release campaign scenario declares live E2E suite(s) not selected by command: "
            + ", ".join(not_requested)
            + "."
        )
    if required_suite_names:
        not_selected = [name for name in required_suite_names if name not in selected_names]
        if not_selected:
            raise ValueError(
                "Release campaign required live E2E suite(s) were not selected: "
                + ", ".join(not_selected)
                + "."
            )
    if not selected_specs:
        raise ValueError(
            "Release campaign live E2E command selected no suites after "
            f"test_network={live_options.test_network} filtering."
        )


def _resolve_campaign_live_e2e_specs(live_e2e_suite: ModuleType, live_options: LiveE2eOptions) -> tuple[Any, ...]:
    if live_options.suites:
        return tuple(live_e2e_suite.resolve_suite_specs(list(live_options.suites)))
    if live_options.profile == "default":
        return tuple(live_e2e_suite.resolve_suite_specs(None))
    profile_suites = live_e2e_suite.PROFILE_SUITE_NAMES.get(live_options.profile)
    if profile_suites is None:
        raise ValueError(f"Release campaign references unknown live E2E profile: {live_options.profile}")
    return tuple(live_e2e_suite.resolve_suite_specs(list(profile_suites)))


def _load_live_e2e_suite_module(layout: WorkspaceLayout) -> ModuleType:
    module_path = layout.tests_repo_root / "emule_test_harness" / "live_e2e_suite.py"
    if not module_path.is_file():
        raise ValueError(f"Live E2E suite module is missing: {module_path}")
    spec = importlib.util.spec_from_file_location("emulebb_release_campaign_live_e2e_suite", module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Unable to load live E2E suite module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    added_repo_root = False
    repo_root = str(layout.tests_repo_root)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
        added_repo_root = True
    try:
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        if added_repo_root:
            try:
                sys.path.remove(repo_root)
            except ValueError:
                pass
    for name in ("PROFILE_SUITE_NAMES", "resolve_suite_specs", "filter_suite_specs_for_network"):
        if not hasattr(module, name):
            raise ValueError(f"Live E2E suite module is missing {name}.")
    return module


def _parse_command(command: str) -> list[str]:
    return shlex.split(command, posix=False)


def _load_campaign(tests_repo_root: Path, campaign_id: str) -> dict[str, Any]:
    manifest_dir = tests_repo_root / "manifests" / "release-campaigns"
    for manifest_path in sorted(manifest_dir.glob("*.json")):
        if manifest_path.name.endswith(".schema.json"):
            continue
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("kind") == "instance" and payload.get("campaignId") == campaign_id:
            return payload
    raise ValueError(f"Release campaign not found: {campaign_id}")


def _aggregate_status(results: list[CampaignCommandResult], *, dry_run: bool) -> str:
    if dry_run and all(result.status == "planned" for result in results):
        return "planned"
    if any(result.status == "failed" for result in results):
        return "failed"
    return "passed"


def _new_report_dir(layout: WorkspaceLayout, campaign_id: str) -> Path:
    stamp = utc_run_id()
    return layout.workspace_root / "state" / "release-campaign-runs" / f"{stamp}-{campaign_id}"


def _scenario_context_payload(contexts: tuple[CampaignScenarioContext, ...]) -> list[dict[str, Any]]:
    """Returns report-friendly scenario metadata for one deduplicated command."""

    return [
        {
            "scenarioId": context.scenario_id,
            "blocking": context.blocking,
            "flowCategory": context.flow_category,
            "executionMode": context.execution_mode,
            "executionModes": list(context.execution_modes),
            "localProfile": context.local_profile,
            "vmProfile": context.vm_profile,
            "controlBindScope": context.control_bind_scope,
            "amutorrentBindScope": context.amutorrent_bind_scope,
            "p2pMode": context.p2p_mode,
            "p2pBindScope": context.p2p_bind_scope,
            "liveE2eProfile": context.live_e2e_profile,
            "liveE2eSuite": context.live_e2e_suite,
        }
        for context in contexts
    ]


def _selected_campaign_scenario_mode(command: str) -> str:
    """Returns the selected reusable campaign command mode, when present."""

    tokens = _parse_command(command)
    if tokens[3:5] != ["test", "campaign-scenario"]:
        return ""
    return _option_value(tokens, "--mode") or ""


def _write_report(
    report_dir: Path,
    campaign: dict[str, Any],
    campaign_options: ReleaseCampaignOptions,
    started_at: datetime,
    plan: tuple[CampaignCommandPlan, ...],
    results: list[CampaignCommandResult],
    pre_run_cleanup: CleanupRunSummary | None,
    *,
    status: str,
) -> None:
    plan_by_command = {item.command: item for item in plan}
    payload = {
        "schemaVersion": "emule-build.release-campaign-run.v1",
        "campaignId": campaign_options.campaign,
        "releaseVersion": campaign.get("releaseVersion", ""),
        "phase": campaign_options.phase or "",
        "status": status,
        "startedAt": started_at.isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "options": {
            "testNetwork": campaign_options.test_network,
            "localVmSwarmMode": campaign_options.local_vm_swarm_mode,
            "localVmSwarmExecutionMode": campaign_options.local_vm_swarm_execution_mode,
            "includeNonblocking": campaign_options.include_nonblocking,
            "continueOnFailure": campaign_options.continue_on_failure,
            "dryRun": campaign_options.dry_run,
            "preRunCleanup": campaign_options.pre_run_cleanup,
        },
        "preRunCleanup": cleanup_summary_payload(pre_run_cleanup),
        "plannedCommands": [
            {
                "command": item.command,
                "selectedCampaignScenarioMode": _selected_campaign_scenario_mode(item.command),
                "phaseIds": list(item.phase_ids),
                "scenarioIds": list(item.scenario_ids),
                "scenarioContexts": _scenario_context_payload(item.scenario_contexts),
            }
            for item in plan
        ],
        "commands": [
            {
                "command": item.command,
                "selectedCampaignScenarioMode": _selected_campaign_scenario_mode(item.command),
                "phaseIds": list(item.phase_ids),
                "scenarioIds": list(item.scenario_ids),
                "scenarioContexts": _scenario_context_payload(
                    plan_by_command.get(
                        item.command,
                        CampaignCommandPlan(item.command, item.phase_ids, item.scenario_ids),
                    ).scenario_contexts
                ),
                "status": item.status,
                "durationSeconds": item.duration_seconds,
                "error": item.error,
            }
            for item in results
        ],
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / release_campaign_result_file_name()).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
