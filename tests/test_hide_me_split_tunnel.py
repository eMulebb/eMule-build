from __future__ import annotations

import json
from pathlib import Path

from emule_workspace import hide_me_split_tunnel


def test_hide_me_split_tunnel_is_opt_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(hide_me_split_tunnel.ENABLE_ENV, raising=False)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([tmp_path / "emulebb.exe"])

    assert result["enabled"] is False


def test_hide_me_split_tunnel_adds_existing_exe_to_whitelist_by_default(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "apps" / "eMuleBB" / "emulebb.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"exe")
    settings.write_text(
        json.dumps(
            {
                "Version": "4.3.2",
                "SplitTunneling": {
                    "Mode": 2,
                    "Whitelisted": [],
                    "LimitToVpn": [],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(hide_me_split_tunnel.ENABLE_ENV, "1")
    monkeypatch.setenv(hide_me_split_tunnel.SETTINGS_PATH_ENV, str(settings))

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe])

    payload = json.loads(settings.read_text(encoding="utf-8"))
    assert result["enabled"] is True
    assert result["changed"] is True
    assert Path(result["backup_path"]).is_file()
    assert result["restart"]["requested"] is False
    assert result["limit_to_vpn"] is False
    assert payload["SplitTunneling"]["Whitelisted"][0]["Path"] == str(exe.resolve())
    assert payload["SplitTunneling"]["LimitToVpn"] == []


def test_hide_me_split_tunnel_can_add_existing_exe_to_limit_to_vpn(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "apps" / "eMuleBB" / "emulebb.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"exe")
    settings.write_text(
        json.dumps(
            {
                "SplitTunneling": {
                    "Whitelisted": [],
                    "LimitToVpn": [],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(hide_me_split_tunnel.ENABLE_ENV, "1")
    monkeypatch.setenv(hide_me_split_tunnel.LIMIT_TO_VPN_ENV, "1")
    monkeypatch.setenv(hide_me_split_tunnel.SETTINGS_PATH_ENV, str(settings))

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe])

    payload = json.loads(settings.read_text(encoding="utf-8"))
    assert result["limit_to_vpn"] is True
    assert payload["SplitTunneling"]["Whitelisted"][0]["Path"] == str(exe.resolve())
    assert payload["SplitTunneling"]["LimitToVpn"][0]["Path"] == str(exe.resolve())


def test_hide_me_split_tunnel_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "emulebb.exe"
    exe.write_bytes(b"exe")
    entry = {"Name": "eMuleBB", "Path": str(exe.resolve()), "Paths": None, "Icon": None}
    settings.write_text(
        json.dumps(
            {
                "SplitTunneling": {
                    "Whitelisted": [entry],
                    "LimitToVpn": [entry],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(hide_me_split_tunnel.ENABLE_ENV, "true")
    monkeypatch.setenv(hide_me_split_tunnel.SETTINGS_PATH_ENV, str(settings))

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe])

    payload = json.loads(settings.read_text(encoding="utf-8"))
    assert result["changed"] is False
    assert len(payload["SplitTunneling"]["Whitelisted"]) == 1
    assert len(payload["SplitTunneling"]["LimitToVpn"]) == 1


def test_hide_me_split_tunnel_can_restart_after_registration(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "emulebb.exe"
    exe.write_bytes(b"exe")
    settings.write_text(json.dumps({"SplitTunneling": {"Whitelisted": [], "LimitToVpn": []}}), encoding="utf-8")
    monkeypatch.setenv(hide_me_split_tunnel.ENABLE_ENV, "1")
    monkeypatch.setenv(hide_me_split_tunnel.RESTART_AFTER_REGISTER_ENV, "1")
    monkeypatch.setenv(hide_me_split_tunnel.SETTINGS_PATH_ENV, str(settings))
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr(hide_me_split_tunnel.subprocess, "run", fake_run)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe])

    assert result["restart"]["requested"] is True
    assert calls and calls[0][0] == "powershell"


def test_hide_me_split_tunnel_can_restart_after_upnp_failure(monkeypatch) -> None:
    monkeypatch.setenv(hide_me_split_tunnel.RESTART_ON_UPNP_FAILURE_ENV, "1")
    calls: list[bool] = []

    def fake_restart():
        calls.append(True)
        return {"requested": True, "returncode": 0}

    monkeypatch.setattr(hide_me_split_tunnel, "restart_hide_me", fake_restart)

    result = hide_me_split_tunnel.restart_hide_me_after_upnp_failure_if_requested(
        "Timed out waiting for UPnP NAT backend order"
    )

    assert result["requested"] is True
    assert result["reason"] == "upnp_failure"
    assert calls == [True]


def test_hide_me_split_tunnel_skips_non_upnp_failure_restart(monkeypatch) -> None:
    monkeypatch.setenv(hide_me_split_tunnel.RESTART_ON_UPNP_FAILURE_ENV, "1")

    result = hide_me_split_tunnel.restart_hide_me_after_upnp_failure_if_requested("ARR handoff timed out")

    assert result["requested"] is False
    assert result["skipped"] == "failure did not match UPnP markers"
