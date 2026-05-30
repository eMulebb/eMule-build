"""Optional developer-local hide.me split-tunnel registration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

ENABLE_ENV = "EMULEBB_DEVELOPER_HIDE_ME_SPLIT_TUNNEL"
SETTINGS_PATH_ENV = "EMULEBB_DEVELOPER_HIDE_ME_SETTINGS_PATH"
RESTART_AFTER_REGISTER_ENV = "EMULEBB_DEVELOPER_HIDE_ME_RESTART_AFTER_REGISTER"
RESTART_ON_UPNP_FAILURE_ENV = "EMULEBB_DEVELOPER_HIDE_ME_RESTART_ON_UPNP_FAILURE"
LIMIT_TO_VPN_ENV = "EMULEBB_DEVELOPER_HIDE_ME_LIMIT_TO_VPN"
ALLOW_LOOPBACK_ENV = "EMULEBB_DEVELOPER_HIDE_ME_ALLOW_LOOPBACK"
HIDE_ME_EXE = Path(r"C:\Program Files (x86)\hide.me VPN\Hide.me.exe")
HIDE_ME_SERVICE = "hmevpnsvc"
LOOPBACK_CIDR = "127.0.0.1/8"
UPNP_FAILURE_MARKERS = (
    "upnp",
    "miniupnp",
    "nat_backend_order",
    "nat mapping",
    "port mapping",
    "portmapping",
    "openportsonstartup",
    "lowid",
    "low id",
    "firewalled",
)


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
    allow_loopback = enabled_allow_loopback_from_environment()
    added_loopback = False
    if allow_loopback:
        killswitch_whitelist = payload.setdefault("KillswitchWhitelist", [])
        if not isinstance(killswitch_whitelist, list):
            raise RuntimeError("hide.me settings KillswitchWhitelist value is not an array.")
        if not any(str(entry).casefold() == LOOPBACK_CIDR.casefold() for entry in killswitch_whitelist):
            killswitch_whitelist.append(LOOPBACK_CIDR)
            added_loopback = True
            changed = True

    list_keys = ["Whitelisted"]
    limit_to_vpn = enabled_limit_to_vpn_from_environment()
    if limit_to_vpn:
        list_keys.append("LimitToVpn")
    added: dict[str, list[str]] = {"Whitelisted": [], "LimitToVpn": []}
    for key in list_keys:
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
    restart = restart_hide_me_after_registration_if_requested() if changed else {"requested": False, "skipped": "settings unchanged"}

    return {
        "enabled": True,
        "settings_path": str(settings_path),
        "changed": changed,
        "backup_path": str(backup_path) if backup_path else "",
        "registered_paths": [str(path) for path in resolved_paths],
        "added": added,
        "limit_to_vpn": limit_to_vpn,
        "allow_loopback": allow_loopback,
        "added_loopback": added_loopback,
        "restart": restart,
    }


def restart_hide_me_after_registration_if_requested() -> dict[str, Any]:
    """Restarts hide.me after a registration when the local opt-in is enabled."""

    if not enabled_restart_from_environment():
        return {"requested": False, "skipped": f"{RESTART_AFTER_REGISTER_ENV} is not enabled"}

    return restart_hide_me()


def restart_hide_me_after_upnp_failure_if_requested(failure_text: str) -> dict[str, Any]:
    """Restarts hide.me after a UPnP-looking live failure when explicitly enabled."""

    if not enabled_restart_on_upnp_failure_from_environment():
        return {"requested": False, "skipped": f"{RESTART_ON_UPNP_FAILURE_ENV} is not enabled"}
    if not looks_like_upnp_failure(failure_text):
        return {"requested": False, "skipped": "failure did not match UPnP markers"}
    result = restart_hide_me()
    result["reason"] = "upnp_failure"
    return result


def restart_hide_me() -> dict[str, Any]:
    """Restarts the local hide.me service and desktop process."""

    command = (
        "$ErrorActionPreference = 'Stop'; "
        "Get-Process -Name 'Hide.me' -ErrorAction SilentlyContinue | Stop-Process -Force; "
        f"Restart-Service -Name {HIDE_ME_SERVICE} -Force; "
        "Start-Sleep -Seconds 5; "
        f"if (Test-Path -LiteralPath '{HIDE_ME_EXE}') "
        f"{{ Start-Process -FilePath '{HIDE_ME_EXE}' -WindowStyle Hidden; Start-Sleep -Seconds 8 }}"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"hide.me restart failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return {"requested": True, "returncode": completed.returncode}


def enabled_restart_from_environment() -> bool:
    """Returns whether hide.me should be restarted after settings changes."""

    return os.environ.get(RESTART_AFTER_REGISTER_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def enabled_restart_on_upnp_failure_from_environment() -> bool:
    """Returns whether hide.me should be restarted after UPnP-looking failures."""

    return os.environ.get(RESTART_ON_UPNP_FAILURE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def enabled_limit_to_vpn_from_environment() -> bool:
    """Returns whether registration should also populate hide.me's LimitToVpn list."""

    return os.environ.get(LIMIT_TO_VPN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def enabled_allow_loopback_from_environment() -> bool:
    """Returns whether local loopback should be whitelisted for harness control traffic."""

    value = os.environ.get(ALLOW_LOOPBACK_ENV, "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def looks_like_upnp_failure(failure_text: str) -> bool:
    """Returns whether a live-test failure report points at UPnP/NAT mapping."""

    normalized = failure_text.casefold()
    return any(marker in normalized for marker in UPNP_FAILURE_MARKERS)


def _unique_existing_files(paths: list[Path]) -> list[Path]:
    unique: dict[str, Path] = {}
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if path.is_file():
            unique.setdefault(_normalize_path(str(path)), path)
    return list(unique.values())


def _normalize_path(value: str) -> str:
    return str(Path(value)).casefold()
