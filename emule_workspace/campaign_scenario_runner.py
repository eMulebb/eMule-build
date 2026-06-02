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

    return LiveE2eOptions(
        profile=str(spec.local_profile or "default"),
        suites=tuple(str(suite) for suite in spec.local_suites),
        test_network="lan",
        pre_run_cleanup=False,
    )


def vm_test_options(spec: Any, scenario_options: CampaignScenarioOptions) -> WindowsVmTestOptions:
    """Returns the Windows VM options for one shared campaign scenario."""

    return WindowsVmTestOptions(
        matrix=("win10", "win11"),
        profile=str(spec.vm_profile),
        release_version=scenario_options.release_version,
        skip_build=scenario_options.skip_build,
        dry_run=scenario_options.dry_run,
        fixture_size_bytes=scenario_options.fixture_size_bytes,
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
