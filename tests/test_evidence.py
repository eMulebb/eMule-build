from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from emule_workspace.evidence import build_heavy_evidence_index, write_heavy_evidence_index


def test_heavy_evidence_index_classifies_large_state_roots(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    write_file(layout.workspace_root / "state" / "test-reports" / "live-e2e-suite" / "payload.dmp", 2048)
    write_file(layout.workspace_root / "state" / "diagnostics" / "pid-100" / "cpu.etl", 2048)
    write_file(layout.workspace_root / "state" / "notes" / "scratch.txt", 2048)
    write_file(layout.workspace_root / "state" / "test-reports" / "tiny" / "result.json", 16)

    payload = build_heavy_evidence_index(layout, threshold_mb=0.001)
    entries = {entry["path"]: entry for entry in payload["entries"]}

    assert entries["workspaces\\workspace\\state\\test-reports\\live-e2e-suite"]["tier"] == "campaign-proof"
    assert entries["workspaces\\workspace\\state\\diagnostics\\pid-100"]["tier"] == "debug-profile"
    assert entries["workspaces\\workspace\\state\\notes"]["tier"] == "scratch"
    assert "workspaces\\workspace\\state\\test-reports\\tiny" not in entries
    assert payload["totals"]["entries"] == 3


def test_heavy_evidence_index_write_uses_generated_state_file(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    write_file(layout.workspace_root / "state" / "release" / "emulebb-v0.7.3-rc.1" / "manifest.json", 2048)

    payload = write_heavy_evidence_index(layout, threshold_mb=0.001)
    index_path = layout.workspace_root / "state" / "heavy-evidence-index.json"

    assert index_path.is_file()
    written = json.loads(index_path.read_text(encoding="utf-8"))
    assert written["schema_version"] == 1
    assert written["entries"] == payload["entries"]
    assert written["entries"][0]["tier"] == "release-proof"


def write_file(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def make_layout(tmp_path: Path):
    return SimpleNamespace(
        emule_workspace_root=tmp_path,
        workspace_name="workspace",
        workspace_root=tmp_path / "workspaces" / "workspace",
    )
