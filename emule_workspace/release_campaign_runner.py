"""First-class release campaign execution for eMuleBB."""

from __future__ import annotations

import json
import shlex
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_names import release_campaign_result_file_name, utc_run_id
from .certification import invoke_certification
from .cleanup import CleanupFailedError, CleanupRunSummary, cleanup_summary_payload, run_pre_test_cleanup
from .config import (
    AmutorrentCleanStartupOptions,
    AmutorrentEmulebbUiOptions,
    AmutorrentPackageOptions,
    AmutorrentResilienceOptions,
    CertificationOptions,
    CommunityCoverageOptions,
    LiveE2eOptions,
    PythonTestOptions,
    ReleaseCampaignOptions,
    ReleasePackageOptions,
    VariantComparisonOptions,
    WorkspaceOptions,
)
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


@dataclass(frozen=True)
class CampaignCommandPlan:
    """One deduplicated release campaign command with owning scenarios."""

    command: str
    phase_ids: tuple[str, ...]
    scenario_ids: tuple[str, ...]


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

    command_rows: dict[str, dict[str, set[str]]] = {}
    order: list[str] = []
    for phase in campaign.get("phases", []):
        phase_id = str(phase.get("id", ""))
        if campaign_options.phase and phase_id != campaign_options.phase:
            continue
        for scenario in phase.get("scenarios", []):
            if not _scenario_selected(scenario, campaign_options):
                continue
            command = str(scenario.get("command", "")).strip()
            if not command:
                continue
            _assert_supported_command(command)
            if command not in command_rows:
                command_rows[command] = {"phase_ids": set(), "scenario_ids": set()}
                order.append(command)
            command_rows[command]["phase_ids"].add(phase_id)
            command_rows[command]["scenario_ids"].add(str(scenario.get("id", "")))

    if campaign_options.phase and not any(str(phase.get("id", "")) == campaign_options.phase for phase in campaign.get("phases", [])):
        raise ValueError(f"Unknown release campaign phase: {campaign_options.phase}")

    return tuple(
        CampaignCommandPlan(
            command=command,
            phase_ids=tuple(sorted(command_rows[command]["phase_ids"])),
            scenario_ids=tuple(sorted(command_rows[command]["scenario_ids"])),
        )
        for command in order
    )


def _scenario_selected(scenario: dict[str, Any], campaign_options: ReleaseCampaignOptions) -> bool:
    if bool(scenario.get("blocking", True)):
        return True
    return campaign_options.include_nonblocking


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


def _assert_supported_command(command: str) -> None:
    _dispatch_shape = _parse_command(command)
    if _dispatch_shape[:3] == ["python", "-m", "emule_workspace"]:
        return
    if len(_dispatch_shape) == 2 and _dispatch_shape[0] == "python" and _dispatch_shape[1].replace("/", "\\") == r"repos\emulebb-tooling\ci\check-clean-worktree.py":
        return
    raise ValueError(f"Unsupported release campaign command: {command}")


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
            "includeNonblocking": campaign_options.include_nonblocking,
            "continueOnFailure": campaign_options.continue_on_failure,
            "dryRun": campaign_options.dry_run,
            "preRunCleanup": campaign_options.pre_run_cleanup,
        },
        "preRunCleanup": cleanup_summary_payload(pre_run_cleanup),
        "plannedCommands": [
            {
                "command": item.command,
                "phaseIds": list(item.phase_ids),
                "scenarioIds": list(item.scenario_ids),
            }
            for item in plan
        ],
        "commands": [
            {
                "command": item.command,
                "phaseIds": list(item.phase_ids),
                "scenarioIds": list(item.scenario_ids),
                "status": item.status,
                "durationSeconds": item.duration_seconds,
                "error": item.error,
            }
            for item in results
        ],
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / release_campaign_result_file_name()).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
