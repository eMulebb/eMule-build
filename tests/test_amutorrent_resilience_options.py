from __future__ import annotations

from pathlib import Path

from emule_workspace.config import AmutorrentResilienceOptions, WorkspaceOptions
from emule_workspace.layout import AppVariant, TestTargets as LayoutTestTargets, WorkspaceLayout
from emule_workspace import test_runs


def make_layout(tmp_path: Path) -> WorkspaceLayout:
    emule_workspace_root = tmp_path
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    tests_repo_root = emule_workspace_root / "repos" / "eMule-build-tests"
    app_root = workspace_root / "app" / "eMule-main"
    (tests_repo_root / "scripts").mkdir(parents=True)
    (tests_repo_root / "scripts" / "amutorrent-resilience-live.py").write_text("# test runner\n", encoding="utf-8")
    app_root.mkdir(parents=True)
    return WorkspaceLayout(
        emule_workspace_root=emule_workspace_root,
        workspace_name="workspace",
        workspace_root=workspace_root,
        build_repo_root=emule_workspace_root / "repos" / "eMule-build",
        tests_repo_root=tests_repo_root,
        tooling_repo_root=emule_workspace_root / "repos" / "eMule-tooling",
        ed2k_server_repo_root=emule_workspace_root / "repos" / "goed2k-server",
        amule_repo_root=emule_workspace_root / "repos" / "amule",
        emuleai_repo_root=emule_workspace_root / "repos" / "eMuleAI",
        seed_repo_path=emule_workspace_root / "repos" / "eMule",
        seed_repo_branch="main",
        dependencies=(),
        app_variants=(AppVariant(name="main", path=app_root, branch="main"),),
        test_targets=LayoutTestTargets(test_build_variant="main", test_run_variant="main", baseline_variant="community"),
        toolset_override_variable="",
    )


def option_values(command: list[str], option: str) -> list[str]:
    return [command[index + 1] for index, value in enumerate(command[:-1]) if value == option]


def test_amutorrent_resilience_forwards_live_options(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)
        captured["label"] = label
        captured["cwd"] = cwd
        captured["env"] = dict(env or {})

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_amutorrent_resilience(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        AmutorrentResilienceOptions(
            live_wire_inputs_file="inputs.json",
            keep_artifacts=True,
            ready_timeout_seconds=11.0,
            network_ready_timeout_seconds=22.0,
            search_observation_timeout_seconds=33.0,
            reconnect_timeout_seconds=44.0,
            p2p_bind_interface_name="hide.me",
        ),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert command[1].endswith("amutorrent-resilience-live.py")
    assert captured["label"] == "aMuTorrent resilience live"
    assert option_values(command, "--live-wire-inputs-file") == ["inputs.json"]
    assert option_values(command, "--ready-timeout-seconds") == ["11.0"]
    assert option_values(command, "--network-ready-timeout-seconds") == ["22.0"]
    assert option_values(command, "--search-observation-timeout-seconds") == ["33.0"]
    assert option_values(command, "--reconnect-timeout-seconds") == ["44.0"]
    assert option_values(command, "--p2p-bind-interface-name") == ["hide.me"]
    assert "--keep-artifacts" in command


def test_amutorrent_resilience_omits_optional_inputs_by_default(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_native(command, *, label, cwd, env=None, allow_failure=False):
        captured["command"] = list(command)

    layout = make_layout(tmp_path)
    monkeypatch.setattr(test_runs, "run_native", fake_run_native)

    test_runs.invoke_amutorrent_resilience(
        layout,
        WorkspaceOptions(workspace_root=tmp_path, platform="x64"),
        AmutorrentResilienceOptions(),
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "--live-wire-inputs-file" not in command
    assert "--keep-artifacts" not in command
