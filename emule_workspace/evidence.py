"""Generated evidence indexing helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .layout import WorkspaceLayout
from .topology import write_json

HEAVY_EVIDENCE_INDEX_NAME = "heavy-evidence-index.json"
HEAVY_EVIDENCE_INDEX_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EvidenceEntry:
    """One generated evidence directory large enough to index."""

    path: Path
    tier: str
    category: str
    bytes: int
    files: int
    last_write_time: datetime


def write_heavy_evidence_index(layout: WorkspaceLayout, *, threshold_mb: float) -> dict[str, Any]:
    """Writes and returns the heavy generated-evidence index."""

    payload = build_heavy_evidence_index(layout, threshold_mb=threshold_mb)
    write_json(_output_root(layout) / "reports" / HEAVY_EVIDENCE_INDEX_NAME, payload)
    return payload


def build_heavy_evidence_index(layout: WorkspaceLayout, *, threshold_mb: float) -> dict[str, Any]:
    """Builds a JSON-friendly index of large generated evidence roots."""

    threshold_bytes = max(0, int(threshold_mb * 1024 * 1024))
    entries = [
        entry
        for entry in _candidate_entries(layout)
        if entry.bytes >= threshold_bytes
    ]
    entries.sort(key=lambda entry: entry.bytes, reverse=True)
    return {
        "schema_version": HEAVY_EVIDENCE_INDEX_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "workspace": layout.workspace_name,
        "threshold_bytes": threshold_bytes,
        "entries": [_entry_payload(layout, entry) for entry in entries],
        "totals": {
            "entries": len(entries),
            "bytes": sum(entry.bytes for entry in entries),
            "files": sum(entry.files for entry in entries),
        },
    }


def print_heavy_evidence_index(layout: WorkspaceLayout, payload: dict[str, Any]) -> None:
    """Prints a concise human summary for one evidence index payload."""

    entries = payload["entries"]
    print(f"Heavy evidence entries: {len(entries)} at >= {_format_bytes(payload['threshold_bytes'])}")
    if not entries:
        return
    print(f"Total indexed: {_format_bytes(payload['totals']['bytes'])} across {payload['totals']['files']} file(s)")
    for entry in entries[:25]:
        print(
            f"  {_format_bytes(entry['bytes']):>9}  {entry['tier']:<14} "
            f"{entry['category']:<18} {entry['path']}"
        )


def _candidate_entries(layout: WorkspaceLayout) -> list[EvidenceEntry]:
    output_root = _output_root(layout)
    roots: list[tuple[Path, str, str]] = []
    known_root_names = {
        "reports",
        "artifacts",
        "release",
        "preserved-evidence",
        "packages",
        "logs",
        "symbols",
        "throwaway-vhd",
        "tools",
    }
    if output_root.is_dir():
        for root_name, tier, category in (
            ("artifacts", "campaign-proof", "test-artifact"),
            ("release", "release-proof", "release"),
            ("preserved-evidence", "release-proof", "preserved-evidence"),
            ("packages/build", "campaign-proof", "package-build"),
            ("logs/builds", "campaign-proof", "build-log"),
            ("symbols", "campaign-proof", "symbols"),
            ("throwaway-vhd", "scratch", "throwaway-vhd"),
            ("tools", "scratch", "tools"),
        ):
            root = output_root / root_name
            if not root.is_dir():
                continue
            children = [child for child in root.iterdir() if child.is_dir()]
            if children:
                roots.extend((child, tier, category) for child in children)
            else:
                roots.append((root, tier, category))

        reports_root = output_root / "reports"
        if reports_root.is_dir():
            for child in reports_root.iterdir():
                if child.is_dir():
                    roots.append((child, *_report_child_tier_and_category(child.name)))

        for child in output_root.iterdir():
            if not child.is_dir() or child.name in known_root_names:
                continue
            roots.append((child, "scratch", "unclassified-output"))

    legacy_reports_root = layout.tests_repo_root / "reports"
    if legacy_reports_root.is_dir():
        roots.extend((child, "legacy-generated", "legacy-test-report") for child in legacy_reports_root.iterdir() if child.is_dir())

    return [_entry_from_directory(path, tier, category) for path, tier, category in roots]


def _report_child_tier_and_category(name: str) -> tuple[str, str]:
    if name == "certification":
        return "release-proof", "certification"
    if name == "release-campaign-runs":
        return "release-proof", "release-campaign"
    if name == "overnight-campaigns":
        return "campaign-proof", "overnight-campaign"
    if name in {"diagnostics", "crash-evidence", "startup-progress-diagnostics"}:
        return "debug-profile", "diagnostic"
    return "campaign-proof", "test-report"


def _entry_from_directory(path: Path, tier: str, category: str) -> EvidenceEntry:
    bytes_total = 0
    files = 0
    last_write_timestamp = path.stat().st_mtime
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    last_write_timestamp = max(last_write_timestamp, stat_result.st_mtime)
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        bytes_total += stat_result.st_size
                        files += 1
        except OSError:
            continue
    return EvidenceEntry(
        path=path,
        tier=tier,
        category=category,
        bytes=bytes_total,
        files=files,
        last_write_time=datetime.fromtimestamp(last_write_timestamp, UTC),
    )


def _entry_payload(layout: WorkspaceLayout, entry: EvidenceEntry) -> dict[str, Any]:
    payload = {
        "path": _workspace_relative(layout, entry.path),
        "tier": entry.tier,
        "category": entry.category,
        "bytes": entry.bytes,
        "files": entry.files,
        "last_write_utc": entry.last_write_time.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    latest_alias = _latest_alias_payload(layout, entry.path)
    if latest_alias is not None:
        payload["latest_alias"] = latest_alias
    return payload


def _latest_alias_payload(layout: WorkspaceLayout, path: Path) -> dict[str, Any] | None:
    if not path.name.endswith("-latest"):
        return None
    base_path = path.with_name(path.name.removesuffix("-latest"))
    return {
        "base_path": _workspace_relative(layout, base_path),
        "base_exists": base_path.exists(),
    }


def _workspace_relative(layout: WorkspaceLayout, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(layout.emule_workspace_root.resolve()))
    except ValueError:
        return str(path)


def _output_root(layout: WorkspaceLayout) -> Path:
    output_root = getattr(layout, "output_root", None)
    if output_root is not None:
        return Path(output_root)
    return layout.workspace_root / "state"


def _format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024.0
    return f"{amount:.1f} TB"
