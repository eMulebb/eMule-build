from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from emule_workspace.config import LocalHammerCampaignOptions, WorkspaceOptions
from emule_workspace.local_package_install import MaterializedLocalInstall
from emule_workspace import local_hammer_campaign


def _layout(tmp_path: Path) -> SimpleNamespace:
    output_root = tmp_path.parent / f"{tmp_path.name}-output"
    return SimpleNamespace(
        emule_workspace_root=tmp_path,
        workspace_root=tmp_path / "workspaces" / "workspace",
        output_reports_root=output_root / "reports",
        output_tmp_root=output_root / "tmp",
        build_repo_root=tmp_path / "repos" / "emulebb-build",
        tests_repo_root=tmp_path / "repos" / "emulebb-build-tests",
    )


def _workspace_options(tmp_path: Path) -> WorkspaceOptions:
    return WorkspaceOptions(
        workspace_root=tmp_path,
        workspace_name="workspace",
        configuration="Release",
        platform="x64",
        build_output_mode="ErrorsOnly",
        output_root=tmp_path.parent / f"{tmp_path.name}-output",
    )


def test_hammer_phase_plan_escalates_from_smoke_to_refresh() -> None:
    options = LocalHammerCampaignOptions(
        skip_build=True,
        live_wire_inputs_file="repos/emulebb-build-tests/live-wire-inputs.local.json",
        godzilla_p2p_bind_interface_address="192.168.1.10",
    )

    phases = local_hammer_campaign.build_hammer_phase_plan(options)

    assert [phase.name for phase in phases] == [
        "installer-command-line-smoke",
        "quick-godzilla-local-swarm",
        "medium-godzilla-local-swarm",
        "heavy-godzilla-local-swarm",
        "large-library-resource-hammer",
        "refresh-repeatability-check",
    ]
    assert phases[0].live_options is not None
    assert phases[0].live_options.materialize_test_install is True
    assert phases[1].live_options is not None
    assert phases[1].live_options.godzilla_total_client_count < phases[2].live_options.godzilla_total_client_count
    assert phases[2].live_options.godzilla_total_client_count < phases[3].live_options.godzilla_total_client_count
    assert phases[3].live_options.godzilla_stage == "full"
    assert phases[4].live_options is not None
    assert "tree-refresh-stress-50k" in phases[4].live_options.shared_files_ui_scenarios
    assert phases[5].refresh_repeatability is True
    assert "--materialize-test-install-skip-build" in phases[0].command
    assert "--godzilla-p2p-bind-interface-address 192.168.1.10" in phases[1].command


def test_dry_run_writes_planned_campaign_report(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    options = LocalHammerCampaignOptions(
        dry_run=True,
        max_cycles=1,
        until_local="2099-05-30T05:00:00",
    )

    local_hammer_campaign.invoke_local_hammer_campaign(layout, _workspace_options(tmp_path), options)

    latest = layout.output_reports_root / "hammer-campaign-runs" / "latest" / "local-hammer-campaign-result.json"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["schema"] == local_hammer_campaign.REPORT_SCHEMA
    assert payload["status"] == "planned"
    assert payload["preflight"]["status"] == "planned"
    assert len(payload["plannedPhases"]) == 6
    assert len(payload["phases"]) == 6
    assert all(phase["status"] == "planned" for phase in payload["phases"])


def test_refresh_repeatability_requires_second_profile_import_skip(tmp_path: Path, monkeypatch) -> None:
    layout = _layout(tmp_path)
    calls = 0

    def fake_materialize(*args, **kwargs) -> MaterializedLocalInstall:
        nonlocal calls
        calls += 1
        target = layout.output_tmp_root / "test-installs" / "run" / "refresh-repeatability" / "primary"
        app_root = target / "apps" / "eMuleBB"
        profile_config = target / "profiles" / "emulebb" / "config"
        seed_config = target / "harness-profile-seed" / "config"
        manifest_dir = target / "manifests"
        app_root.mkdir(parents=True, exist_ok=True)
        profile_config.mkdir(parents=True, exist_ok=True)
        seed_config.mkdir(parents=True, exist_ok=True)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (app_root / "emulebb.exe").write_bytes(b"exe")
        (app_root / "emulebb.pdb").write_bytes(b"pdb")
        for name in ("preferences.ini", "preferences.dat", "server.met", "nodes.dat"):
            (seed_config / name).write_bytes(name.encode("ascii"))
        action = "imported" if calls == 1 else "skipped-existing"
        (manifest_dir / "suite-install.json").write_text(
            json.dumps({"profileImport": {"action": action}}),
            encoding="utf-8",
        )
        (manifest_dir / "local-install.json").write_text("{}\n", encoding="utf-8")
        return MaterializedLocalInstall(
            target_path=target,
            app_root=app_root,
            app_exe=app_root / "emulebb.exe",
            profile_dir=target / "profiles" / "emulebb",
            profile_config_dir=profile_config,
            profile_seed_config_dir=seed_config,
            manifest_path=manifest_dir / "local-install.json",
        )

    monkeypatch.setattr(local_hammer_campaign, "materialize_test_local_install", fake_materialize)

    payload = local_hammer_campaign._run_refresh_repeatability(
        layout,
        _workspace_options(tmp_path),
        LocalHammerCampaignOptions(skip_build=True),
        tmp_path / "report-run",
    )

    assert payload["firstProfileImportAction"] == "imported"
    assert payload["secondProfileImportAction"] == "skipped-existing"
    assert payload["adjacentPdb"].endswith("emulebb.pdb")
