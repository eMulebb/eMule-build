from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from emule_workspace import validation
from emule_workspace.topology import ManagedRepo


def test_policy_audits_receive_workspace_root_through_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tooling_root = tmp_path / "repos" / "emulebb-tooling"
    audit_path = tooling_root / "ci" / "check-workspace-policy.py"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_run_native(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(validation, "run_native", fake_run_native)
    layout = SimpleNamespace(emule_workspace_root=tmp_path, tooling_repo_root=tooling_root)

    validation.run_policy_audits(layout)

    assert calls
    for call in calls:
        assert "-EmuleWorkspaceRoot" not in call["command"]
        assert "pwsh" not in call["command"]
        assert call["command"][-2] == str(audit_path)
        assert call["env"] == {"EMULE_WORKSPACE_ROOT": tmp_path}


def test_validation_reanchors_clean_canonical_app_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_repo = tmp_path / "repos" / "emulebb"
    canonical_repo.mkdir(parents=True)
    calls: list[tuple[str, ...]] = []

    def fake_git_output(repo: Path, *args: str) -> str:
        assert repo == canonical_repo
        calls.append(args)
        if args == ("rev-parse", "refs/remotes/origin/main"):
            return "expected-head\n"
        if args == ("rev-parse", "HEAD"):
            return "stale-head\n"
        if args == ("checkout", "--detach", "refs/remotes/origin/main"):
            return ""
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(validation, "repo_status_lines", lambda repo: ["## HEAD (no branch)"])
    monkeypatch.setattr(validation, "repo_branch", lambda repo: "HEAD")
    monkeypatch.setattr(validation, "git_output", fake_git_output)
    layout = SimpleNamespace(seed_repo_path=canonical_repo, seed_repo_branch="main")

    validation.ensure_canonical_app_anchor(layout)

    assert calls[-1] == ("checkout", "--detach", "refs/remotes/origin/main")


def test_validation_refuses_dirty_canonical_app_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_repo = tmp_path / "repos" / "emulebb"
    canonical_repo.mkdir(parents=True)
    calls: list[tuple[str, ...]] = []

    def fake_git_output(repo: Path, *args: str) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(validation, "repo_status_lines", lambda repo: ["## HEAD (no branch)", " M srchybrid/emule.rc"])
    monkeypatch.setattr(validation, "git_output", fake_git_output)
    layout = SimpleNamespace(seed_repo_path=canonical_repo, seed_repo_branch="main")

    with pytest.raises(RuntimeError, match="local changes"):
        validation.ensure_canonical_app_anchor(layout)

    assert calls == []


def test_required_workspace_paths_include_topology_managed_repos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspaces" / "workspace"
    for path in (
        tmp_path / "AGENTS.md",
        tmp_path / "workspace.props",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for path in (
        tmp_path / "repos" / "emulebb",
        tmp_path / "repos" / "emulebb-build-tests",
        tmp_path / "repos" / "emulebb-tooling",
        tmp_path / "repos" / "emulebb-build",
        tmp_path / "analysis" / "compare",
        workspace_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    (workspace_root / "deps.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        validation,
        "canonical_topology",
        lambda: SimpleNamespace(
            repos=(
                ManagedRepo(
                    name="emulebb-build",
                    url="https://example.invalid/build.git",
                    relative_path="repos\\emulebb-build",
                    branch="main",
                ),
                ManagedRepo(
                    name="emulebb-pages",
                    url="https://example.invalid/pages.git",
                    relative_path="repos\\emulebb-pages",
                    branch="main",
                ),
            )
        ),
    )
    layout = SimpleNamespace(
        emule_workspace_root=tmp_path,
        workspace_root=workspace_root,
        seed_repo_path=tmp_path / "repos" / "emulebb",
        tests_repo_root=tmp_path / "repos" / "emulebb-build-tests",
        tooling_repo_root=tmp_path / "repos" / "emulebb-tooling",
        dependencies=(),
        app_variants=(),
        resolve_workspace_path=lambda relative_path: tmp_path / relative_path,
    )

    with pytest.raises(RuntimeError, match="emulebb-pages"):
        validation.assert_required_workspace_paths(layout)


def test_product_family_validation_runs_repo_native_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents_root = tmp_path / "repos" / "p2p-overlord-agents"
    coordinator_root = tmp_path / "repos" / "p2p-overlord-be" / "overlord-be-coordinator"
    goed2k_root = tmp_path / "repos" / "goed2k-server"
    for path in (agents_root, coordinator_root, goed2k_root):
        path.mkdir(parents=True)
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run_native(command, **kwargs):
        calls.append((tuple(str(part) for part in command), kwargs["cwd"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(validation, "run_native", fake_run_native)
    monkeypatch.setattr(validation, "find_tool", lambda names: Path(names[0]))
    layout = SimpleNamespace(
        p2p_overlord_agents_repo_root=agents_root,
        p2p_overlord_be_repo_root=tmp_path / "repos" / "p2p-overlord-be",
        ed2k_server_repo_root=goed2k_root,
    )

    validation.validate_product_family_repos(layout)

    assert (("cargo.exe", "fmt", "--all", "--check"), agents_root) in calls
    assert (("npm.cmd", "run", "quality"), coordinator_root) in calls
    assert (("go.exe", "test", "./..."), goed2k_root) in calls
