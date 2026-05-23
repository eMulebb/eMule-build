from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from emule_workspace.layout import AppVariant, TestTargets as LayoutTestTargets, WorkspaceLayout, file_token, get_test_build_tag
from emule_workspace.setup_commands import compare_root
from emule_workspace.topology import (
    WORKSPACE_MANIFEST_SCHEMA_VERSION,
    build_workspace_manifest,
    canonical_topology,
    validate_workspace_manifest_contract,
)


def test_get_test_build_tag_matches_existing_harness_shape(tmp_path: Path) -> None:
    workspace_root = tmp_path / "owner" / "workspaces" / "workspace"
    app_root = workspace_root / "app" / "emulebb-main"

    assert get_test_build_tag(workspace_root, app_root) == "owner-workspace-emulebb-main"


def test_file_token_matches_legacy_filename_sanitization() -> None:
    assert file_token('repos\\emulebb-build-tests: bad/name') == "repos-emulebb-build-tests-bad-name"


def test_workspace_manifest_uses_json_contract_shape() -> None:
    manifest = build_workspace_manifest(canonical_topology(), "workspace")

    assert manifest["schema_version"] == WORKSPACE_MANIFEST_SCHEMA_VERSION
    assert manifest["workspace"]["repos"]["build"] == "..\\..\\repos\\emulebb-build"
    assert manifest["workspace"]["repos"]["ed2k_server"] == "..\\..\\repos\\goed2k-server"
    assert manifest["workspace"]["repos"]["amule"] == "..\\..\\repos\\amule"
    assert "emuleai" not in manifest["workspace"]["repos"]
    assert manifest["workspace"]["repos"]["pages"] == "..\\..\\repos\\emulebb-pages"
    assert manifest["workspace"]["repos"]["org_profile"] == "..\\..\\repos\\emulebb-org-profile"
    assert manifest["workspace"]["repos"]["p2p_overlord_agents"] == "..\\..\\repos\\p2p-overlord-agents"
    assert manifest["workspace"]["repos"]["p2p_overlord_be"] == "..\\..\\repos\\p2p-overlord-be"
    assert manifest["workspace"]["app_repo"]["variants"][0] == {
        "name": "main",
        "path": "app\\emulebb-main",
        "branch": "main",
    }


def test_canonical_topology_materializes_web_repositories_under_repos() -> None:
    repos = {repo.name: repo for repo in canonical_topology().repos}

    assert repos["emulebb-pages"].url == "https://github.com/emulebb/emulebb.github.io.git"
    assert repos["emulebb-pages"].relative_path == "repos\\emulebb-pages"
    assert repos["emulebb-org-profile"].url == "https://github.com/emulebb/.github.git"
    assert repos["emulebb-org-profile"].relative_path == "repos\\emulebb-org-profile"


def test_canonical_topology_materializes_ed2k_server_fork_under_repos() -> None:
    repos = {repo.name: repo for repo in canonical_topology().repos}

    ed2k_server = repos["goed2k-server"]
    assert ed2k_server.url == "https://github.com/emulebb/goed2k-server.git"
    assert ed2k_server.relative_path == "repos\\goed2k-server"
    assert ed2k_server.branch == "master"
    assert tuple((remote.name, remote.url) for remote in ed2k_server.additional_remotes) == (
        ("upstream", "https://github.com/chenjia404/goed2k-server.git"),
    )


def test_canonical_topology_materializes_client_references_in_active_and_analysis_roots() -> None:
    repos = {repo.name: repo for repo in canonical_topology().repos}
    analysis_repos = {repo.name: repo for repo in canonical_topology().analysis_repos}

    amule = repos["amule"]
    assert amule.url == "https://github.com/emulebb/amule.git"
    assert amule.relative_path == "repos\\amule"
    assert amule.branch == "master"
    assert amule.compare_subdir == "src"
    assert tuple((remote.name, remote.url) for remote in amule.additional_remotes) == (
        ("upstream", "https://github.com/amule-project/amule.git"),
    )

    assert "emuleai" not in repos
    emuleai = analysis_repos["emuleai"]
    assert emuleai.url == "https://github.com/emulebb/emulebb-ai.git"
    assert emuleai.relative_path == "analysis\\emuleai"
    assert emuleai.branch == "master"
    assert emuleai.compare_subdir == "srchybrid"
    assert tuple((remote.name, remote.url) for remote in emuleai.additional_remotes) == (
        ("upstream", "https://github.com/eMuleAI/eMuleAI.git"),
    )


def test_canonical_topology_materializes_p2p_overlord_product_family_repos() -> None:
    repos = {repo.name: repo for repo in canonical_topology().repos}

    agents = repos["p2p-overlord-agents"]
    assert agents.url == "https://github.com/emulebb/p2p-overlord-agents.git"
    assert agents.relative_path == "repos\\p2p-overlord-agents"
    assert agents.branch == "develop"

    backend = repos["p2p-overlord-be"]
    assert backend.url == "https://github.com/emulebb/p2p-overlord-be.git"
    assert backend.relative_path == "repos\\p2p-overlord-be"
    assert backend.branch == "develop"

    assert "p2p-overlord-ed2k-server" not in repos


def test_compare_root_accepts_repo_targets_with_and_without_compare_subdirs(tmp_path: Path) -> None:
    topology = canonical_topology()

    assert compare_root(tmp_path, topology, "amule") == tmp_path / "repos" / "amule" / "src"
    assert compare_root(tmp_path, topology, "mods-archive") == tmp_path / "analysis" / "mods-archive"


def test_workspace_manifest_schema_rejects_unsupported_versions() -> None:
    manifest = build_workspace_manifest(canonical_topology(), "workspace")
    manifest["schema_version"] = WORKSPACE_MANIFEST_SCHEMA_VERSION + 1

    with pytest.raises(ValidationError, match="unsupported workspace manifest schema_version"):
        validate_workspace_manifest_contract(manifest)


def test_get_app_variant_error_lists_keys_paths_and_branches(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces" / "workspace"
    layout = WorkspaceLayout(
        emule_workspace_root=tmp_path,
        workspace_name="workspace",
        workspace_root=workspace_root,
        build_repo_root=tmp_path / "repos" / "emulebb-build",
        tests_repo_root=tmp_path / "repos" / "emulebb-build-tests",
        tooling_repo_root=tmp_path / "repos" / "emulebb-tooling",
        ed2k_server_repo_root=tmp_path / "repos" / "goed2k-server",
        amule_repo_root=tmp_path / "repos" / "amule",
        seed_repo_path=tmp_path / "repos" / "emulebb",
        seed_repo_branch="main",
        dependencies=(),
        app_variants=(
            AppVariant(name="main", path=workspace_root / "app" / "emulebb-main", branch="main"),
            AppVariant(
                name="community",
                path=workspace_root / "app" / "emulebb-community-baseline",
                branch="baseline/community-0.72a",
            ),
        ),
        test_targets=LayoutTestTargets(test_build_variant="main", test_run_variant="main", baseline_variant="community"),
        toolset_override_variable="",
    )

    with pytest.raises(RuntimeError) as exc_info:
        layout.get_app_variant("community-baseline")

    message = str(exc_info.value)
    assert "Use a configured variant key, not the worktree folder name." in message
    assert "main -> app\\emulebb-main (main)" in message
    assert "community -> app\\emulebb-community-baseline (baseline/community-0.72a)" in message
