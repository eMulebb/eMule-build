"""Dispatch shared campaign scenarios through local or Windows VM runners."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .config import CampaignScenarioOptions, LiveE2eOptions, WorkspaceOptions
from .layout import WorkspaceLayout
from .test_runs import invoke_live_e2e_suite
from .windows_vm_lab import WindowsVmTestOptions, invoke_windows_vm_tests


GODZILLA_SWARM_TIERS: dict[int, dict[str, object]] = {
    1: {
        "stage": "launch-scale",
        "total_client_count": 4,
        "peer_transfer_count": 24,
        "harness_transfer_count": 24,
        "emulebb_files": 80,
        "extra_emulebb_files": 8,
        "harness_files": 60,
        "amule_files": 20,
        "adverse_kill_cycles": 0,
        "adverse_kill_warmup_seconds": 0.0,
        "adverse_recovery_timeout_seconds": 180.0,
        "cpu_profile": False,
        "fail_fast": True,
    },
    2: {
        "stage": "launch-scale",
        "total_client_count": 10,
        "peer_transfer_count": 120,
        "harness_transfer_count": 120,
        "emulebb_files": 240,
        "extra_emulebb_files": 24,
        "harness_files": 180,
        "amule_files": 60,
        "adverse_kill_cycles": 0,
        "adverse_kill_warmup_seconds": 0.0,
        "adverse_recovery_timeout_seconds": 180.0,
        "cpu_profile": True,
        "fail_fast": False,
    },
    3: {
        "stage": "full",
        "total_client_count": 18,
        "peer_transfer_count": 360,
        "harness_transfer_count": 360,
        "emulebb_files": 720,
        "extra_emulebb_files": 72,
        "harness_files": 480,
        "amule_files": 120,
        "adverse_kill_cycles": 2,
        "adverse_kill_warmup_seconds": 20.0,
        "adverse_recovery_timeout_seconds": 180.0,
        "cpu_profile": True,
        "fail_fast": False,
    },
}
GODZILLA_LOCAL_SWARM_SUITE = "godzilla-local-swarm"


def invoke_campaign_scenario(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    scenario_options: CampaignScenarioOptions,
) -> None:
    """Runs one reusable campaign scenario in local or VM mode."""

    spec = resolve_campaign_scenario(layout, scenario_options.scenario)
    if scenario_options.mode == "local":
        invoke_live_e2e_suite(
            layout,
            workspace_options,
            local_live_e2e_options(spec, scenario_options),
        )
        return
    if scenario_options.mode == "vm":
        invoke_windows_vm_tests(
            layout,
            workspace_options,
            vm_test_options(spec, scenario_options),
        )
        return
    raise ValueError(f"Unsupported campaign scenario mode: {scenario_options.mode!r}.")


def local_live_e2e_options(spec: Any, scenario_options: CampaignScenarioOptions) -> LiveE2eOptions:
    """Returns the local live E2E options for one shared campaign scenario."""

    suites = tuple(str(suite) for suite in spec.local_suites)
    if bool(getattr(spec, "uses_local_swarm", False)) and GODZILLA_LOCAL_SWARM_SUITE not in suites:
        suites = (*suites, GODZILLA_LOCAL_SWARM_SUITE)
    godzilla = godzilla_tier_options(scenario_options.swarm_tier)
    return LiveE2eOptions(
        profile=str(spec.local_profile or "default"),
        suites=suites,
        test_network="lan",
        pre_run_cleanup=False,
        fail_fast=bool(godzilla["fail_fast"]) if GODZILLA_LOCAL_SWARM_SUITE in suites else False,
        admin_volume_fixtures=GODZILLA_LOCAL_SWARM_SUITE in suites,
        godzilla_stage=str(godzilla["stage"]) if GODZILLA_LOCAL_SWARM_SUITE in suites else None,  # type: ignore[arg-type]
        godzilla_total_client_count=int(godzilla["total_client_count"]),
        godzilla_peer_transfer_count=int(godzilla["peer_transfer_count"]),
        godzilla_harness_transfer_count=int(godzilla["harness_transfer_count"]),
        godzilla_emulebb_files=int(godzilla["emulebb_files"]),
        godzilla_extra_emulebb_files=int(godzilla["extra_emulebb_files"]),
        godzilla_harness_files=int(godzilla["harness_files"]),
        godzilla_amule_files=int(godzilla["amule_files"]),
        godzilla_adverse_kill_cycles=int(godzilla["adverse_kill_cycles"]),
        godzilla_adverse_kill_warmup_seconds=float(godzilla["adverse_kill_warmup_seconds"]),
        godzilla_adverse_recovery_timeout_seconds=float(godzilla["adverse_recovery_timeout_seconds"]),
        godzilla_cpu_profile=bool(godzilla["cpu_profile"]) if GODZILLA_LOCAL_SWARM_SUITE in suites else False,
    )


def godzilla_tier_options(swarm_tier: int) -> dict[str, object]:
    """Returns the existing local-swarm scale profile for a campaign tier."""

    try:
        return GODZILLA_SWARM_TIERS[swarm_tier]
    except KeyError as exc:
        raise ValueError(f"Unsupported campaign swarm tier: {swarm_tier}") from exc


def vm_test_options(spec: Any, scenario_options: CampaignScenarioOptions) -> WindowsVmTestOptions:
    """Returns the Windows VM options for one shared campaign scenario."""

    return WindowsVmTestOptions(
        matrix=("win10", "win11"),
        profile=str(spec.vm_profile),
        release_version=scenario_options.release_version,
        skip_build=scenario_options.skip_build,
        dry_run=scenario_options.dry_run,
        fixture_size_bytes=scenario_options.fixture_size_bytes,
        swarm_tier=scenario_options.swarm_tier,
    )


def resolve_campaign_scenario(layout: WorkspaceLayout, scenario: str) -> Any:
    """Loads a shared scenario by key, scenario id, or VM profile name."""

    catalog = load_campaign_scenario_catalog(layout)
    for mapping_name in (
        "REUSABLE_CAMPAIGN_SCENARIO_BY_KEY",
        "REUSABLE_CAMPAIGN_SCENARIO_BY_SCENARIO_ID",
        "REUSABLE_CAMPAIGN_SCENARIO_BY_VM_PROFILE",
    ):
        mapping = getattr(catalog, mapping_name)
        if scenario in mapping:
            return mapping[scenario]
    raise ValueError(f"Unknown reusable campaign scenario: {scenario}")


def load_campaign_scenario_catalog(layout: WorkspaceLayout) -> ModuleType:
    """Loads the test-owned campaign scenario catalog."""

    module_path = layout.tests_repo_root / "emule_test_harness" / "campaign_scenarios.py"
    return _load_test_module(
        layout.tests_repo_root,
        module_path,
        "emulebb_campaign_scenario_catalog",
        ("REUSABLE_CAMPAIGN_SCENARIO_BY_KEY", "REUSABLE_CAMPAIGN_SCENARIO_BY_SCENARIO_ID"),
    )


def _load_test_module(
    tests_repo_root: Path,
    module_path: Path,
    module_name: str,
    required_attrs: tuple[str, ...],
) -> ModuleType:
    if not module_path.is_file():
        raise ValueError(f"Campaign scenario catalog is missing: {module_path}")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Unable to load campaign scenario catalog: {module_path}")
    module = importlib.util.module_from_spec(spec)
    added_repo_root = False
    repo_root = str(tests_repo_root)
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
    for name in required_attrs:
        if not hasattr(module, name):
            raise ValueError(f"Campaign scenario catalog is missing {name}.")
    return module
