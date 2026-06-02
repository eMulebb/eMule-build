from __future__ import annotations

from pathlib import Path

from emule_workspace import campaign_scenario_runner
from emule_workspace.config import CampaignScenarioOptions, WorkspaceOptions
from test_release_campaign_runner import make_layout, write_campaign_scenario_catalog


def test_campaign_scenario_local_mode_reuses_local_live_suites_and_tiered_swarm(
    tmp_path: Path,
    monkeypatch,
) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    calls: list[tuple[str, tuple[str, ...], str, bool, int, int, str, bool, bool]] = []

    monkeypatch.setattr(
        campaign_scenario_runner,
        "invoke_live_e2e_suite",
        lambda _layout, _workspace_options, options: calls.append(
            (
                options.profile,
                options.suites,
                options.test_network,
                options.plan_only,
                options.godzilla_total_client_count,
                options.godzilla_amule_files,
                options.godzilla_stage or "",
                options.admin_volume_fixtures,
                options.godzilla_cpu_profile,
            )
        ),
    )

    campaign_scenario_runner.invoke_campaign_scenario(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        CampaignScenarioOptions(scenario="emulebb.flow.ui.search.local-swarm.v1", mode="local", swarm_tier=2),
    )

    assert calls == [
        (
            "multi-client-p2p",
            ("local-ed2k-search-soak", "local-kad-swarm", "godzilla-local-swarm"),
            "default",
            False,
            12,
            66,
            "launch-scale",
            True,
            True,
        )
    ]


def test_campaign_scenario_local_dry_run_plans_local_live_suites(
    tmp_path: Path,
    monkeypatch,
) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    calls: list[bool] = []

    monkeypatch.setattr(
        campaign_scenario_runner,
        "invoke_live_e2e_suite",
        lambda _layout, _workspace_options, options: calls.append(options.plan_only),
    )

    campaign_scenario_runner.invoke_campaign_scenario(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        CampaignScenarioOptions(
            scenario="emulebb.flow.ui.search.local-swarm.v1",
            mode="local",
            dry_run=True,
        ),
    )

    assert calls == [True]


def test_godzilla_tier_options_come_from_campaign_catalog(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    catalog = campaign_scenario_runner.load_campaign_scenario_catalog(layout)

    assert campaign_scenario_runner.godzilla_tier_options(catalog, 1)["total_client_count"] == 4
    assert campaign_scenario_runner.godzilla_tier_options(catalog, 2)["total_client_count"] == 12
    assert campaign_scenario_runner.godzilla_tier_options(catalog, 2)["amule_files"] == 66
    assert campaign_scenario_runner.godzilla_tier_options(catalog, 3)["total_client_count"] == 18


def test_campaign_scenario_vm_mode_reuses_vm_profile(tmp_path: Path, monkeypatch) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    calls: list[tuple[tuple[str, ...], str, str, bool, bool, int, int, str]] = []

    monkeypatch.setattr(
        campaign_scenario_runner,
        "invoke_windows_vm_tests",
        lambda _layout, _workspace_options, options: calls.append(
            (
                options.matrix,
                options.profile,
                options.release_version,
                options.skip_build,
                options.dry_run,
                options.fixture_size_bytes,
                options.swarm_tier,
                options.local_swarm_mode,
            )
        ),
    )

    campaign_scenario_runner.invoke_campaign_scenario(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        CampaignScenarioOptions(
            scenario="search-ui-local-swarm",
            mode="vm",
            release_version="0.7.4-rc.2",
            skip_build=True,
            dry_run=True,
            fixture_size_bytes=4096,
            swarm_tier=3,
            local_swarm_mode="execute",
        ),
    )

    assert calls == [(("win10", "win11"), "search-ui-local-swarm-vm", "0.7.4-rc.2", True, True, 4096, 3, "execute")]


def test_campaign_scenario_vm_mode_accepts_target_matrix(tmp_path: Path, monkeypatch) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        campaign_scenario_runner,
        "invoke_windows_vm_tests",
        lambda _layout, _workspace_options, options: calls.append(options.matrix),
    )

    campaign_scenario_runner.invoke_campaign_scenario(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        CampaignScenarioOptions(
            scenario="search-ui-local-swarm",
            mode="vm",
            vm_matrix=("win10",),
        ),
    )

    assert calls == [("win10",)]
