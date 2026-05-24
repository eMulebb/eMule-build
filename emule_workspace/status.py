"""Workspace status reporting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .git import git_output, repo_branch, repo_head, repo_status_lines
from .layout import WorkspaceLayout
from .topology import canonical_topology


@dataclass(frozen=True)
class RepoStatus:
    """Concise Git state for one workspace repository."""

    role: str
    name: str
    path: Path
    branch: str
    head: str
    upstream: str
    ahead: int
    behind: int
    dirty: bool
    missing: bool = False


def write_dependency_status(layout: WorkspaceLayout) -> None:
    """Prints dependency and app worktree status."""

    for dependency in layout.dependencies:
        repo_path = layout.resolve_workspace_path(dependency.path)
        if not repo_path.exists():
            print(f"MISSING {dependency.name} -> {repo_path}")
            continue
        print(f"DEP {dependency.name} [{repo_branch(repo_path)}] {'; '.join(repo_status_lines(repo_path))}")
    for app in layout.app_variants:
        print(f"APP {app.path} [{repo_branch(app.path)}] {'; '.join(repo_status_lines(app.path))}")


def write_workspace_summary(layout: WorkspaceLayout) -> None:
    """Prints a concise dependency and app commit summary."""

    print("")
    print("Workspace summary")
    for dependency in layout.dependencies:
        repo_path = layout.resolve_workspace_path(dependency.path)
        if not repo_path.exists():
            continue
        print(f"DEP {dependency.name:<12} {repo_branch(repo_path)} {repo_head(repo_path)}")
    for app in layout.app_variants:
        print(f"APP {app.name:<12} {repo_branch(app.path)} {repo_head(app.path)}")


def write_workspace_repo_status(layout: WorkspaceLayout) -> None:
    """Prints dirty-state, branch, and upstream coverage for every managed repo."""

    statuses = collect_workspace_repo_status(layout)
    print(
        "ROLE        NAME                              BRANCH                         HEAD      "
        "UPSTREAM                       AHEAD BEHIND STATE   PATH"
    )
    for status in statuses:
        state = "missing" if status.missing else ("dirty" if status.dirty else "clean")
        print(
            f"{status.role:<11} {status.name:<33} {status.branch:<30} {status.head:<9} "
            f"{status.upstream:<30} {status.ahead:>5} {status.behind:>6} {state:<7} {status.path}"
        )


def collect_workspace_repo_status(layout: WorkspaceLayout) -> list[RepoStatus]:
    """Returns Git state for every clone managed by the canonical topology."""

    topology = canonical_topology()
    statuses: list[RepoStatus] = []
    statuses.append(
        _repo_status("app-seed", topology.app_repo.name, layout.emule_workspace_root / topology.app_repo.relative_path)
    )
    for worktree in topology.app_repo.worktrees:
        if worktree.active:
            statuses.append(
                _repo_status("app-worktree", worktree.name, layout.emule_workspace_root / worktree.relative_path)
            )
    statuses.extend(
        _repo_status("repo", repo.name, layout.emule_workspace_root / repo.relative_path) for repo in topology.repos
    )
    statuses.extend(
        _repo_status("analysis", repo.name, layout.emule_workspace_root / repo.relative_path)
        for repo in topology.analysis_repos
    )
    statuses.extend(
        _repo_status("third-party", repo.name, layout.emule_workspace_root / repo.relative_path)
        for repo in topology.third_party_repos
    )
    return statuses


def _repo_status(role: str, name: str, path: Path) -> RepoStatus:
    if not path.exists():
        return RepoStatus(role, name, path, "-", "-", "-", 0, 0, dirty=False, missing=True)
    branch = repo_branch(path)
    head = repo_head(path)
    upstream = _git_optional(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ahead = 0
    behind = 0
    if upstream:
        counts = _git_optional(path, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        if counts:
            parts = counts.split()
            if len(parts) == 2:
                behind = int(parts[0])
                ahead = int(parts[1])
    dirty = any(not line.startswith("##") for line in repo_status_lines(path))
    return RepoStatus(role, name, path, branch, head, upstream or "-", ahead, behind, dirty)


def _git_optional(repo_root: Path, *args: str) -> str:
    try:
        return git_output(repo_root, *args).strip()
    except Exception:
        return ""
