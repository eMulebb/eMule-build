"""Workspace generated-artifact audit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .layout import WorkspaceLayout

AUDIT_ROOT_NAMES = ("repos", "workspaces")
CACHE_DIRECTORY_NAMES = {".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache"}
GENERATED_DIRECTORY_NAMES = {
    "node_modules",
    "cmake-build-arm64",
    "cmake-build-ARM64",
    "cmake-build-x64",
    "VS2017-ARM64",
    "VS2017-x64",
}
GENERATED_FILE_SUFFIXES = {
    ".dll",
    ".exe",
    ".exp",
    ".idb",
    ".ilk",
    ".iobj",
    ".ipdb",
    ".lastbuildstate",
    ".lib",
    ".obj",
    ".pch",
    ".pdb",
    ".res",
    ".tlog",
}


@dataclass(frozen=True)
class ArtifactAuditFinding:
    """One generated artifact found outside the canonical output root."""

    path: Path
    kind: str
    reason: str


def audit_workspace_artifacts(layout: WorkspaceLayout) -> list[ArtifactAuditFinding]:
    """Returns generated build/package artifacts below repos or workspaces."""

    findings: list[ArtifactAuditFinding] = []
    for root_name in AUDIT_ROOT_NAMES:
        root = layout.emule_workspace_root / root_name
        if not root.is_dir():
            continue
        findings.extend(_audit_tree(root, layout.emule_workspace_root))
    return sorted(findings, key=lambda finding: str(finding.path).lower())


def print_artifact_audit(layout: WorkspaceLayout, findings: list[ArtifactAuditFinding]) -> None:
    """Prints a compact generated-artifact audit summary."""

    if not findings:
        print("Workspace artifact audit passed.")
        return

    print("Workspace artifact audit failed.")
    print(f"Generated repo/workspace artifacts: {len(findings)}")
    for finding in findings[:80]:
        print(f"  {finding.kind}: {_relative_to_workspace(layout, finding.path)} ({finding.reason})")
    if len(findings) > 80:
        print(f"  ... {len(findings) - 80} more")


def _audit_tree(root: Path, workspace_root: Path) -> list[ArtifactAuditFinding]:
    findings: list[ArtifactAuditFinding] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name in CACHE_DIRECTORY_NAMES:
                    continue
                if _is_generated_directory(child):
                    findings.append(ArtifactAuditFinding(child, "directory", "generated build/package directory"))
                    continue
                stack.append(child)
            elif _is_generated_file(child, workspace_root):
                findings.append(ArtifactAuditFinding(child, "file", "generated build/package file"))
    return findings


def _is_generated_directory(path: Path) -> bool:
    if path.name in GENERATED_DIRECTORY_NAMES:
        return True
    if path.name in {"x64", "ARM64"}:
        parts = set(path.parts)
        return bool({"srchybrid", "libprj", "ResizableLib", "cryptlib", "miniupnpc", "vc"} & parts)
    return False


def _is_generated_file(path: Path, workspace_root: Path) -> bool:
    if path.suffix.lower() in GENERATED_FILE_SUFFIXES:
        if _is_under_output_root(path, workspace_root):
            return False
        return True
    return path.name in {"adhoc.cpp", "adhoc.cpp.copied", "miniupnpcstrings.h", "rc_version.h"}


def _is_under_output_root(path: Path, workspace_root: Path) -> bool:
    # The audit roots are repos/workspaces, but keep this defensive check so
    # future layouts with output-root junctions do not report canonical output.
    try:
        path.relative_to(workspace_root / "output")
    except ValueError:
        return False
    return True


def _relative_to_workspace(layout: WorkspaceLayout, path: Path) -> str:
    try:
        return str(path.relative_to(layout.emule_workspace_root))
    except ValueError:
        return str(path)
