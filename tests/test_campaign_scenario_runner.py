from __future__ import annotations

from pathlib import Path

from emule_workspace import campaign_scenario_runner
from emule_workspace.config import CampaignScenarioOptions, WorkspaceOptions
from test_release_campaign_runner import make_layout, write_campaign_scenario_catalog


def test_campaign_scenario_local_mode_reuses_local_live_suites(tmp_path: Path, monkeypatch) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    calls: list[tuple[str, tuple[str, ...], str]] = []

    monkeypatch.setattr(
        campaign_scenario_runner,
        "invoke_live_e2e_suite",
        lambda _layout, _workspace_options, options: calls.append(
            (options.profile, options.suites, options.test_network)
        ),
    )

    campaign_scenario_runner.invoke_campaign_scenario(
        layout,
        WorkspaceOptions(workspace_root=tmp_path),
        CampaignScenarioOptions(scenario="emulebb.flow.ui.search.local-swarm.v1", mode="local"),
    )

    assert calls == [("multi-client-p2p", ("local-ed2k-search-soak", "local-kad-swarm"), "lan")]


def test_campaign_scenario_vm_mode_reuses_vm_profile(tmp_path: Path, monkeypatch) -> None:
    layout = make_layout(tmp_path)
    write_campaign_scenario_catalog(layout)
    calls: list[tuple[tuple[str, ...], str, str, bool, bool, int]] = []

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
        ),
    )

    assert calls == [(("win10", "win11"), "search-ui-local-swarm-vm", "0.7.4-rc.2", True, True, 4096)]
