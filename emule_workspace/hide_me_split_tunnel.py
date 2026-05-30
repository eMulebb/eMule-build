"""Optional developer-local hide.me split-tunnel registration."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

ENABLE_ENV = "EMULEBB_DEVELOPER_HIDE_ME_SPLIT_TUNNEL"
SETTINGS_PATH_ENV = "EMULEBB_DEVELOPER_HIDE_ME_SETTINGS_PATH"


def enabled_from_environment() -> bool:
    """Returns whether the developer-local hide.me integration is enabled."""

    return os.environ.get(ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def default_settings_path() -> Path:
    """Returns the current user's hide.me settings path."""

    configured = os.environ.get(SETTINGS_PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    appdata = os.environ.get("APPDATA", "").strip()
    if not appdata:
        raise RuntimeError(f"{ENABLE_ENV} requires APPDATA or {SETTINGS_PATH_ENV}.")
    return Path(appdata) / "Hide.me" / "vpn.settings"


def ensure_split_tunnel_apps(app_paths: list[Path], *, app_name: str = "eMuleBB") -> dict[str, Any]:
    """Adds executable paths to hide.me split-tunnel lists when explicitly enabled."""

    if not enabled_from_environment():
        return {"enabled": False, "reason": f"{ENABLE_ENV} is not enabled"}

    resolved_paths = _unique_existing_files(app_paths)
    if not resolved_paths:
        raise RuntimeError("hide.me split-tunnel registration was enabled but no executable path exists.")

    settings_path = default_settings_path()
    if not settings_path.is_file():
        raise RuntimeError(f"hide.me settings file is missing: {settings_path}")

    payload = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    split_tunneling = payload.setdefault("SplitTunneling", {})
    if not isinstance(split_tunneling, dict):
        raise RuntimeError("hide.me settings SplitTunneling value is not an object.")

    changed = False
    added: dict[str, list[str]] = {"Whitelisted": [], "LimitToVpn": []}
    for key in ("Whitelisted", "LimitToVpn"):
        entries = split_tunneling.setdefault(key, [])
        if not isinstance(entries, list):
            raise RuntimeError(f"hide.me settings SplitTunneling.{key} value is not an array.")
        existing = {
            _normalize_path(str(entry.get("Path", "")))
            for entry in entries
            if isinstance(entry, dict)
        }
        for path in resolved_paths:
            normalized = _normalize_path(str(path))
            if normalized in existing:
                continue
            entries.append({"Name": app_name, "Path": str(path), "Paths": None, "Icon": None})
            existing.add(normalized)
            added[key].append(str(path))
            changed = True

    backup_path = None
    if changed:
        backup_path = settings_path.with_name(f"{settings_path.name}.emulebb-{time.strftime('%Y%m%dT%H%M%S')}.bak")
        shutil.copy2(settings_path, backup_path)
        settings_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8", newline="")

    return {
        "enabled": True,
        "settings_path": str(settings_path),
        "changed": changed,
        "backup_path": str(backup_path) if backup_path else "",
        "registered_paths": [str(path) for path in resolved_paths],
        "added": added,
    }


def _unique_existing_files(paths: list[Path]) -> list[Path]:
    unique: dict[str, Path] = {}
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if path.is_file():
            unique.setdefault(_normalize_path(str(path)), path)
    return list(unique.values())


def _normalize_path(value: str) -> str:
    return str(Path(value)).casefold()
