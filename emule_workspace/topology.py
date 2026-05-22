"""Canonical workspace topology owned by the Python orchestration layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

BUILD_MANIFEST_NAME = "deps.json"
WORKSPACE_MANIFEST_NAME = "deps.json"
WORKSPACE_MANIFEST_SCHEMA_VERSION = 4
DEFAULT_WORKSPACE_NAME = "workspace"
WORKSPACE_PROPS_FILE_NAME = "workspace.props"
SETUP_LOG_FILE_NAME = "eMule-workspace.log"


class AdditionalRemote(BaseModel):
    """Extra remote attached to a managed clone."""

    model_config = ConfigDict(frozen=True)

    name: str
    url: str


class UpdatePolicyChild(BaseModel):
    """Advisory upstream metadata for a child component."""

    model_config = ConfigDict(frozen=True)

    name: str
    relative_path: str
    upstream_url: str
    tracking_mode: str
    baseline_ref: str
    version_pattern: str | None = None


class UpdatePolicy(BaseModel):
    """Advisory upstream metadata for a managed dependency."""

    model_config = ConfigDict(frozen=True)

    upstream_url: str | None = None
    tracking_mode: str
    baseline_ref: str | None = None
    upstream_ref: str | None = None
    version_pattern: str | None = None
    notes: str | None = None
    child_components: tuple[UpdatePolicyChild, ...] = ()


class ManagedRepo(BaseModel):
    """Repository cloned or maintained by materialization."""

    model_config = ConfigDict(frozen=True)

    name: str
    url: str
    relative_path: str
    branch: str
    branch_optional: bool = False
    has_submodules: bool = False
    compare_subdir: str | None = None
    additional_remotes: tuple[AdditionalRemote, ...] = ()
    update_policy: UpdatePolicy | None = None


class AppWorktree(BaseModel):
    """Managed app worktree materialized from the canonical app repo."""

    model_config = ConfigDict(frozen=True)

    name: str
    branch: str
    relative_path: str
    active: bool = True


class AppRepo(ManagedRepo):
    """Canonical app repository plus its managed worktrees."""

    worktrees: tuple[AppWorktree, ...] = ()


class WorkspaceTopology(BaseModel):
    """Complete materialization topology for the canonical workspace."""

    model_config = ConfigDict(frozen=True)

    default_workspace_name: str = DEFAULT_WORKSPACE_NAME
    root_directories: tuple[str, ...]
    app_repo: AppRepo
    repos: tuple[ManagedRepo, ...]
    analysis_repos: tuple[ManagedRepo, ...]
    third_party_repos: tuple[ManagedRepo, ...]

    def all_repos(self) -> tuple[ManagedRepo, ...]:
        """Returns every clone maintained directly by materialization."""

        return (*self.repos, *self.analysis_repos, *self.third_party_repos, self.app_repo)


class WorkspaceManifestSeedRepo(BaseModel):
    """Seed app repo entry in the generated workspace manifest."""

    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    branch: str


class WorkspaceManifestVariant(BaseModel):
    """Managed app variant entry in the generated workspace manifest."""

    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    branch: str


class WorkspaceManifestAppRepo(BaseModel):
    """App repo section in the generated workspace manifest."""

    model_config = ConfigDict(frozen=True)

    seed_repo: WorkspaceManifestSeedRepo
    variants: tuple[WorkspaceManifestVariant, ...]


class WorkspaceManifestRepos(BaseModel):
    """Repository path section in the generated workspace manifest."""

    model_config = ConfigDict(frozen=True)

    build: str
    tests: str
    tooling: str
    amutorrent: str
    ed2k_server: str
    amule: str
    pages: str
    org_profile: str
    third_party: str


class WorkspaceManifestWorkspace(BaseModel):
    """Workspace section in the generated workspace manifest."""

    model_config = ConfigDict(frozen=True)

    name: str
    app_repo: WorkspaceManifestAppRepo
    repos: WorkspaceManifestRepos


class WorkspaceManifestContract(BaseModel):
    """Versioned contract written to workspaces/<name>/deps.json."""

    model_config = ConfigDict(frozen=True)

    schema_version: int
    emule_workspace_root: str
    workspace: WorkspaceManifestWorkspace

    @field_validator("schema_version")
    @classmethod
    def require_supported_schema_version(cls, value: int) -> int:
        """Rejects manifests written by an incompatible schema version."""

        if value != WORKSPACE_MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported workspace manifest schema_version {value}")
        return value


def load_json(path: Path) -> dict[str, Any]:
    """Loads one JSON object from disk."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Manifest did not load as an object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Writes a deterministic JSON object to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def build_workspace_manifest(topology: WorkspaceTopology, workspace_name: str | None = None) -> dict[str, Any]:
    """Builds the generated workspace manifest contract."""

    resolved_workspace_name = workspace_name or topology.default_workspace_name
    active_worktrees = tuple(worktree for worktree in topology.app_repo.worktrees if worktree.active)
    repo_by_name = {repo.name: repo for repo in topology.repos}
    workspace_prefix = Path("..") / ".."
    app_prefix = Path("workspaces") / resolved_workspace_name
    return {
        "schema_version": WORKSPACE_MANIFEST_SCHEMA_VERSION,
        "emule_workspace_root": str(workspace_prefix),
        "workspace": {
            "name": resolved_workspace_name,
            "app_repo": {
                "seed_repo": {
                    "name": topology.app_repo.name,
                    "path": str(workspace_prefix / topology.app_repo.relative_path),
                    "branch": topology.app_repo.branch,
                },
                "variants": [
                    {
                        "name": worktree.name,
                        "path": str(Path(worktree.relative_path).relative_to(app_prefix)),
                        "branch": worktree.branch,
                    }
                    for worktree in active_worktrees
                ],
            },
            "repos": {
                "build": _workspace_relative_repo_path(repo_by_name["eMule-build"]),
                "tests": _workspace_relative_repo_path(repo_by_name["eMule-build-tests"]),
                "tooling": _workspace_relative_repo_path(repo_by_name["eMule-tooling"]),
                "amutorrent": _workspace_relative_repo_path(repo_by_name["amutorrent"]),
                "ed2k_server": _workspace_relative_repo_path(repo_by_name["goed2k-server"]),
                "amule": _workspace_relative_repo_path(repo_by_name["amule"]),
                "pages": _workspace_relative_repo_path(repo_by_name["eMulebb-pages"]),
                "org_profile": _workspace_relative_repo_path(repo_by_name["eMulebb-org-profile"]),
                "third_party": str(workspace_prefix / "repos" / "third_party"),
            },
        },
    }


def validate_workspace_manifest_contract(payload: dict[str, Any]) -> WorkspaceManifestContract:
    """Validates one generated workspace manifest payload."""

    return WorkspaceManifestContract.model_validate(payload)


def canonical_topology() -> WorkspaceTopology:
    """Returns the canonical eMuleBB workspace topology."""

    return WorkspaceTopology(
        root_directories=("analysis", "archives", "repos", "repos\\third_party", "workspaces"),
        app_repo=AppRepo(
            name="eMule",
            url="https://github.com/eMulebb/eMule.git",
            relative_path="repos\\eMule",
            branch="main",
            worktrees=(
                AppWorktree(name="main", branch="main", relative_path="workspaces\\workspace\\app\\eMule-main"),
                AppWorktree(
                    name="community",
                    branch="baseline/community-0.72a",
                    relative_path="workspaces\\workspace\\app\\eMule-community-baseline",
                ),
                AppWorktree(
                    name="tracing-harness",
                    branch="tracing-harness/community-0.72a",
                    relative_path="workspaces\\workspace\\app\\eMule-community-tracing-harness",
                ),
            ),
        ),
        repos=(
            ManagedRepo(
                name="eMule-build",
                url="https://github.com/eMulebb/eMule-build.git",
                relative_path="repos\\eMule-build",
                branch="main",
            ),
            ManagedRepo(
                name="eMule-build-tests",
                url="https://github.com/eMulebb/eMule-build-tests.git",
                relative_path="repos\\eMule-build-tests",
                branch="main",
            ),
            ManagedRepo(
                name="eMule-tooling",
                url="https://github.com/eMulebb/eMule-tooling.git",
                relative_path="repos\\eMule-tooling",
                branch="main",
            ),
            ManagedRepo(
                name="amutorrent",
                url="https://github.com/eMulebb/amutorrent.git",
                relative_path="repos\\amutorrent",
                branch="main",
                additional_remotes=(AdditionalRemote(name="upstream", url="https://github.com/got3nks/amutorrent.git"),),
            ),
            ManagedRepo(
                name="goed2k-server",
                url="https://github.com/eMulebb/goed2k-server.git",
                relative_path="repos\\goed2k-server",
                branch="master",
                additional_remotes=(
                    AdditionalRemote(name="upstream", url="https://github.com/chenjia404/goed2k-server.git"),
                ),
            ),
            ManagedRepo(
                name="amule",
                url="https://github.com/eMulebb/amule.git",
                relative_path="repos\\amule",
                branch="master",
                compare_subdir="src",
                additional_remotes=(AdditionalRemote(name="upstream", url="https://github.com/amule-project/amule.git"),),
            ),
            ManagedRepo(
                name="eMulebb-pages",
                url="https://github.com/eMulebb/eMulebb.github.io.git",
                relative_path="repos\\eMulebb-pages",
                branch="main",
            ),
            ManagedRepo(
                name="eMulebb-org-profile",
                url="https://github.com/eMulebb/.github.git",
                relative_path="repos\\eMulebb-org-profile",
                branch="main",
            ),
        ),
        analysis_repos=(
            ManagedRepo(
                name="community-0.60",
                url="https://github.com/irwir/eMule.git",
                relative_path="analysis\\community-0.60",
                branch="v0.60d",
                compare_subdir="srchybrid",
            ),
            ManagedRepo(
                name="community-0.72",
                url="https://github.com/irwir/eMule.git",
                relative_path="analysis\\community-0.72",
                branch="v0.72a",
                compare_subdir="srchybrid",
            ),
            ManagedRepo(
                name="mods-archive",
                url="https://github.com/eMulebb/eMule-mods-archive.git",
                relative_path="analysis\\mods-archive",
                branch="main",
                branch_optional=True,
            ),
            ManagedRepo(
                name="stale-v0.72a-experimental-clean",
                url="https://github.com/eMulebb/eMule.git",
                relative_path="analysis\\stale-v0.72a-experimental-clean",
                branch="stale/v0.72a-experimental-clean",
                compare_subdir="srchybrid",
            ),
            ManagedRepo(
                name="emuleai",
                url="https://github.com/eMulebb/eMuleAI.git",
                relative_path="analysis\\eMuleAI",
                branch="master",
                compare_subdir="srchybrid",
                additional_remotes=(AdditionalRemote(name="upstream", url="https://github.com/eMuleAI/eMuleAI.git"),),
            ),
        ),
        third_party_repos=(
            ManagedRepo(
                name="eMule-cryptopp",
                url="https://github.com/eMulebb/eMule-cryptopp.git",
                relative_path="repos\\third_party\\eMule-cryptopp",
                branch="CRYPTOPP_8_4_0-pristine",
                update_policy=UpdatePolicy(
                    upstream_url="https://github.com/weidai11/cryptopp.git",
                    tracking_mode="tag",
                    baseline_ref="CRYPTOPP_8_4_0",
                    version_pattern=r"^CRYPTOPP_(\d+)_(\d+)_(\d+)$",
                ),
            ),
            ManagedRepo(
                name="eMule-id3lib",
                url="https://github.com/eMulebb/eMule-id3lib.git",
                relative_path="repos\\third_party\\eMule-id3lib",
                branch="id3lib-v3.9.1-emule",
                update_policy=UpdatePolicy(
                    tracking_mode="none",
                    baseline_ref="v3.9.1",
                    notes="Patch baked into fork; no automated upstream comparison.",
                ),
            ),
            ManagedRepo(
                name="eMule-mbedtls",
                url="https://github.com/eMulebb/eMule-mbedtls.git",
                relative_path="repos\\third_party\\eMule-mbedtls",
                branch="mbedtls-v4.1.0-emule",
                has_submodules=True,
                update_policy=UpdatePolicy(
                    upstream_url="https://github.com/Mbed-TLS/mbedtls.git",
                    tracking_mode="tag",
                    baseline_ref="mbedtls-4.1.0",
                    version_pattern=r"^mbedtls-(\d+)\.(\d+)\.(\d+)$",
                    child_components=(
                        UpdatePolicyChild(
                            name="tf-psa-crypto",
                            relative_path="tf-psa-crypto",
                            upstream_url="https://github.com/Mbed-TLS/TF-PSA-Crypto.git",
                            tracking_mode="tag",
                            baseline_ref="v1.1.0",
                            version_pattern=r"^v(\d+)\.(\d+)\.(\d+)$",
                        ),
                    ),
                ),
            ),
            ManagedRepo(
                name="eMule-miniupnp",
                url="https://github.com/eMulebb/eMule-miniupnp.git",
                relative_path="repos\\third_party\\eMule-miniupnp",
                branch="miniupnpc-master-emule",
                update_policy=UpdatePolicy(
                    upstream_url="https://github.com/miniupnp/miniupnp.git",
                    tracking_mode="branch-head",
                    upstream_ref="master",
                    baseline_ref="0cc037f8b0d563334bace7af4e00e9041cfa97e6",
                ),
            ),
            ManagedRepo(
                name="eMule-libpcpnatpmp",
                url="https://github.com/eMulebb/eMule-libpcpnatpmp.git",
                relative_path="repos\\third_party\\eMule-libpcpnatpmp",
                branch="libpcpnatpmp-master-emule",
                update_policy=UpdatePolicy(
                    upstream_url="https://github.com/libpcpnatpmp/libpcpnatpmp.git",
                    tracking_mode="branch-head",
                    upstream_ref="master",
                    baseline_ref="7ab2f9475a242f3714715d7580e1001e9e8a7497",
                ),
            ),
            ManagedRepo(
                name="eMule-ResizableLib",
                url="https://github.com/eMulebb/eMule-ResizableLib.git",
                relative_path="repos\\third_party\\eMule-ResizableLib",
                branch="ResizableLib-bebab50-emule",
                update_policy=UpdatePolicy(
                    upstream_url="https://github.com/ppescher/resizablelib.git",
                    tracking_mode="branch-head",
                    upstream_ref="master",
                    baseline_ref="bebab50a5dbfbb0913b64d23b86d1c3110677c41",
                ),
            ),
            ManagedRepo(
                name="eMule-nlohmann-json",
                url="https://github.com/eMulebb/eMule-nlohmann-json.git",
                relative_path="repos\\third_party\\eMule-nlohmann-json",
                branch="json-v3.11.3-emule",
                update_policy=UpdatePolicy(
                    upstream_url="https://github.com/nlohmann/json.git",
                    tracking_mode="tag",
                    baseline_ref="v3.11.3",
                    version_pattern=r"^v(\d+)\.(\d+)\.(\d+)$",
                ),
            ),
            ManagedRepo(
                name="eMule-zlib",
                url="https://github.com/eMulebb/eMule-zlib.git",
                relative_path="repos\\third_party\\eMule-zlib",
                branch="zlib-v1.3.2-emule",
                update_policy=UpdatePolicy(
                    upstream_url="https://github.com/madler/zlib.git",
                    tracking_mode="tag",
                    baseline_ref="v1.3.2",
                    version_pattern=r"^v(\d+)\.(\d+)\.(\d+)$",
                ),
            ),
        ),
    )


def _workspace_relative_repo_path(repo: ManagedRepo) -> str:
    return str(Path("..") / ".." / repo.relative_path)
