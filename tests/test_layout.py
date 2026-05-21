from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from emule_workspace.layout import file_token, get_test_build_tag
from emule_workspace.setup_commands import compare_root
from emule_workspace.topology import (
    WORKSPACE_MANIFEST_SCHEMA_VERSION,
    build_workspace_manifest,
    canonical_topology,
    validate_workspace_manifest_contract,
)


def test_get_test_build_tag_matches_existing_harness_shape(tmp_path: Path) -> None:
    workspace_root = tmp_path / "owner" / "workspaces" / "workspace"
    app_root = workspace_root / "app" / "eMule-main"

    assert get_test_build_tag(workspace_root, app_root) == "owner-workspace-eMule-main"


def test_file_token_matches_legacy_filename_sanitization() -> None:
    assert file_token('repos\\eMule-build-tests: bad/name') == "repos-eMule-build-tests-bad-name"


def test_workspace_manifest_uses_json_contract_shape() -> None:
    manifest = build_workspace_manifest(canonical_topology(), "workspace")

    assert manifest["schema_version"] == WORKSPACE_MANIFEST_SCHEMA_VERSION
    assert manifest["workspace"]["repos"]["build"] == "..\\..\\repos\\eMule-build"
    assert manifest["workspace"]["repos"]["ed2k_server"] == "..\\..\\repos\\emulebb-ed2k-server"
    assert manifest["workspace"]["repos"]["amule"] == "..\\..\\repos\\amule"
    assert manifest["workspace"]["repos"]["emuleai"] == "..\\..\\repos\\eMuleAI"
    assert manifest["workspace"]["repos"]["pages"] == "..\\..\\repos\\eMulebb-pages"
    assert manifest["workspace"]["repos"]["org_profile"] == "..\\..\\repos\\eMulebb-org-profile"
    assert manifest["workspace"]["app_repo"]["variants"][0] == {
        "name": "main",
        "path": "app\\eMule-main",
        "branch": "main",
    }


def test_canonical_topology_materializes_web_repositories_under_repos() -> None:
    repos = {repo.name: repo for repo in canonical_topology().repos}

    assert repos["eMulebb-pages"].url == "https://github.com/eMulebb/eMulebb.github.io.git"
    assert repos["eMulebb-pages"].relative_path == "repos\\eMulebb-pages"
    assert repos["eMulebb-org-profile"].url == "https://github.com/eMulebb/.github.git"
    assert repos["eMulebb-org-profile"].relative_path == "repos\\eMulebb-org-profile"


def test_canonical_topology_materializes_ed2k_server_fork_under_repos() -> None:
    repos = {repo.name: repo for repo in canonical_topology().repos}

    ed2k_server = repos["emulebb-ed2k-server"]
    assert ed2k_server.url == "https://github.com/eMulebb/emulebb-ed2k-server.git"
    assert ed2k_server.relative_path == "repos\\emulebb-ed2k-server"
    assert ed2k_server.branch == "master"
    assert tuple((remote.name, remote.url) for remote in ed2k_server.additional_remotes) == (
        ("upstream", "https://github.com/p2p-overlord/p2p-overlord-ed2k-server.git"),
    )


def test_canonical_topology_promotes_multi_client_forks_under_repos() -> None:
    repos = {repo.name: repo for repo in canonical_topology().repos}

    amule = repos["amule"]
    assert amule.url == "https://github.com/eMulebb/amule.git"
    assert amule.relative_path == "repos\\amule"
    assert amule.branch == "main"
    assert amule.compare_subdir == "src"
    assert tuple((remote.name, remote.url) for remote in amule.additional_remotes) == (
        ("upstream", "https://github.com/amule-project/amule.git"),
    )

    emuleai = repos["emuleai"]
    assert emuleai.url == "https://github.com/eMulebb/eMuleAI.git"
    assert emuleai.relative_path == "repos\\eMuleAI"
    assert emuleai.branch == "main"
    assert emuleai.compare_subdir == "srchybrid"
    assert tuple((remote.name, remote.url) for remote in emuleai.additional_remotes) == (
        ("upstream", "https://github.com/eMuleAI/eMuleAI.git"),
    )


def test_compare_root_accepts_repo_targets_with_and_without_compare_subdirs(tmp_path: Path) -> None:
    topology = canonical_topology()

    assert compare_root(tmp_path, topology, "amule") == tmp_path / "repos" / "amule" / "src"
    assert compare_root(tmp_path, topology, "mods-archive") == tmp_path / "analysis" / "mods-archive"


def test_workspace_manifest_schema_rejects_unsupported_versions() -> None:
    manifest = build_workspace_manifest(canonical_topology(), "workspace")
    manifest["schema_version"] = WORKSPACE_MANIFEST_SCHEMA_VERSION + 1

    with pytest.raises(ValidationError, match="unsupported workspace manifest schema_version"):
        validate_workspace_manifest_contract(manifest)
