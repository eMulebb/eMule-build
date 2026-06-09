"""Workspace topology loading and path resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .topology import BUILD_MANIFEST_NAME, WORKSPACE_MANIFEST_NAME, load_json


@dataclass(frozen=True)
class Dependency:
    """One dependency entry from the build manifest."""

    name: str
    path: str
    project: str
    header_only: bool = False


@dataclass(frozen=True)
class AppVariant:
    """One managed app worktree variant from the workspace manifest."""

    name: str
    path: Path
    branch: str


@dataclass(frozen=True)
class TestTargets:
    """Default app variants used by shared test flows."""

    test_build_variant: str
    test_run_variant: str
    baseline_variant: str


@dataclass(frozen=True)
class WorkspaceLayout:
    """Resolved layout for one materialized eMule workspace."""

    emule_workspace_root: Path
    workspace_name: str
    workspace_root: Path
    build_repo_root: Path
    tests_repo_root: Path
    tooling_repo_root: Path
    ed2k_server_repo_root: Path
    amule_repo_root: Path
    seed_repo_path: Path
    seed_repo_branch: str
    dependencies: tuple[Dependency, ...]
    app_variants: tuple[AppVariant, ...]
    test_targets: TestTargets
    toolset_override_variable: str
    p2p_overlord_agents_repo_root: Path | None = None
    p2p_overlord_be_repo_root: Path | None = None
    p2p_overlord_tooling_repo_root: Path | None = None
    output_root: Path | None = None

    def resolve_workspace_path(self, relative_path: str) -> Path:
        """Resolves a root-relative workspace path."""

        return (self.emule_workspace_root / relative_path).resolve()

    def get_app_variant(self, name: str) -> AppVariant:
        """Returns one configured app variant by name."""

        for variant in self.app_variants:
            if variant.name == name:
                return variant
        variant_lines = [
            f"{variant.name} -> {variant.path.relative_to(self.workspace_root)} ({variant.branch})"
            for variant in self.app_variants
        ]
        raise RuntimeError(
            f"App variant '{name}' is not defined in {WORKSPACE_MANIFEST_NAME}. "
            "Use a configured variant key, not the worktree folder name. "
            "Available variants: "
            + "; ".join(variant_lines)
        )

    def build_log_directory(self, stamp: str) -> Path:
        """Returns and creates the workspace build-log directory for one session."""

        directory = self.output_logs_root / "builds" / stamp
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def output_build_root(self) -> Path:
        """Returns the root for generated build outputs."""

        return self._resolved_output_root() / "builds"

    @property
    def output_logs_root(self) -> Path:
        """Returns the root for generated logs."""

        return self._resolved_output_root() / "logs"

    @property
    def output_reports_root(self) -> Path:
        """Returns the root for generated reports."""

        return self._resolved_output_root() / "reports"

    @property
    def output_artifacts_root(self) -> Path:
        """Returns the root for generated test and workflow artifacts."""

        return self._resolved_output_root() / "artifacts"

    @property
    def output_packages_root(self) -> Path:
        """Returns the root for generated package build staging."""

        return self._resolved_output_root() / "packages"

    @property
    def output_release_root(self) -> Path:
        """Returns the root for generated release assets."""

        return self._resolved_output_root() / "release"

    @property
    def output_cache_root(self) -> Path:
        """Returns the root for generated caches."""

        return self._resolved_output_root() / "cache"

    @property
    def output_tmp_root(self) -> Path:
        """Returns the root for generated temporary state."""

        return self._resolved_output_root() / "tmp"

    @property
    def output_profiles_root(self) -> Path:
        """Returns the root for generated runtime profiles."""

        return self._resolved_output_root() / "profiles"

    @property
    def output_tools_root(self) -> Path:
        """Returns the root for downloaded or built tool payloads."""

        return self._resolved_output_root() / "tools"

    def _resolved_output_root(self) -> Path:
        """Returns the configured output root, with a legacy fallback for direct unit fixtures."""

        return self.output_root or (self.workspace_root / "state")


def build_repo_root() -> Path:
    """Returns the repository root that owns this package."""

    return Path(__file__).resolve().parents[1]


def load_layout(emule_workspace_root: Path, workspace_name: str | None = None, *, output_root: Path | None = None) -> WorkspaceLayout:
    """Loads and resolves the build and workspace manifests."""

    repo_root = build_repo_root()
    build_manifest = load_json(repo_root / BUILD_MANIFEST_NAME)
    build_workspace = _required_dict(build_manifest, "workspace")
    resolved_workspace_name = workspace_name or str(build_workspace.get("name") or "workspace")
    workspace_root = (emule_workspace_root / "workspaces" / resolved_workspace_name).resolve()
    workspace_manifest_path = workspace_root / WORKSPACE_MANIFEST_NAME
    if not workspace_manifest_path.is_file():
        raise RuntimeError(
            f"Workspace manifest is missing: {workspace_manifest_path}. "
            "Run python -m emule_workspace materialize or sync for this workspace."
        )

    workspace_manifest = load_json(workspace_manifest_path)
    workspace_topology = _required_dict(workspace_manifest, "workspace")
    app_repo = _required_dict(workspace_topology, "app_repo")
    seed_repo = _required_dict(app_repo, "seed_repo")
    repos = _required_dict(workspace_topology, "repos")
    build_app_repo = _required_dict(build_workspace, "app_repo")
    test_targets = _required_dict(build_app_repo, "test_targets")
    toolchain = _required_dict(build_workspace, "toolchain")

    variants = tuple(
        AppVariant(
            name=str(raw["name"]),
            path=_resolve_workspace_manifest_path(workspace_root, raw["path"]),
            branch=str(raw["branch"]),
        )
        for raw in _required_list(app_repo, "variants")
    )
    dependencies = tuple(
        Dependency(
            name=str(raw["name"]),
            path=str(raw["path"]),
            project=str(raw["project"]),
            header_only=bool(raw.get("header_only", False)),
        )
        for raw in _required_list(build_workspace, "dependencies")
    )

    return WorkspaceLayout(
        emule_workspace_root=emule_workspace_root.resolve(),
        workspace_name=resolved_workspace_name,
        workspace_root=workspace_root,
        build_repo_root=repo_root,
        tests_repo_root=_resolve_workspace_manifest_path(workspace_root, repos["tests"]),
        tooling_repo_root=_resolve_workspace_manifest_path(workspace_root, repos["tooling"]),
        ed2k_server_repo_root=_resolve_workspace_manifest_path(workspace_root, repos["ed2k_server"]),
        amule_repo_root=_resolve_workspace_manifest_path(workspace_root, repos["amule"]),
        p2p_overlord_agents_repo_root=_resolve_workspace_manifest_path(workspace_root, repos["p2p_overlord_agents"]),
        p2p_overlord_be_repo_root=_resolve_workspace_manifest_path(workspace_root, repos["p2p_overlord_be"]),
        p2p_overlord_tooling_repo_root=_resolve_workspace_manifest_path(workspace_root, repos["p2p_overlord_tooling"]),
        output_root=output_root.resolve() if output_root is not None else None,
        seed_repo_path=_resolve_workspace_manifest_path(workspace_root, seed_repo["path"]),
        seed_repo_branch=str(seed_repo["branch"]),
        dependencies=dependencies,
        app_variants=variants,
        test_targets=TestTargets(
            test_build_variant=str(test_targets["test_build_variant"]),
            test_run_variant=str(test_targets["test_run_variant"]),
            baseline_variant=str(test_targets["baseline_variant"]),
        ),
        toolset_override_variable=str(toolchain.get("toolset_override_variable") or ""),
    )


def get_test_build_tag(workspace_root: Path, app_root: Path | None = None) -> str:
    """Returns the native-test build tag used by existing harness outputs."""

    resolved_workspace_root = workspace_root.resolve()
    workspace_leaf = resolved_workspace_root.name
    workspace_owner = resolved_workspace_root.parent.parent.name
    segments = [segment for segment in (workspace_owner, workspace_leaf) if segment]
    if app_root is not None:
        segments.append(app_root.resolve().name)
    return re.sub(r"[^A-Za-z0-9._-]", "_", "-".join(segments))


def file_token(value: str) -> str:
    """Converts free-form text into a stable log filename token."""

    token = re.sub(r'[\\/:*?"<>|\s]+', "-", value)
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", token).strip("-")
    return token or "build"


def _resolve_workspace_manifest_path(workspace_root: Path, relative_path: str | Path) -> Path:
    """Resolves a path relative to the workspace manifest's workspace root."""

    return (workspace_root / Path(str(relative_path))).resolve()


def _required_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Manifest is missing object '{key}'.")
    return value


def _required_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"Manifest is missing object list '{key}'.")
    return value
