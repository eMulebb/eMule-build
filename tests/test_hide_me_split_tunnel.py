from __future__ import annotations

import json
from pathlib import Path

from emule_workspace import hide_me_split_tunnel


def stub_hide_me_stop_start(monkeypatch) -> list[str]:
    calls: list[str] = []

    def fake_stop():
        calls.append("stop")
        return {"requested": True, "returncode": 0}

    def fake_start():
        calls.append("start")
        return {"requested": True, "returncode": 0, "vpn_ipv4": "10.54.216.129"}

    monkeypatch.setattr(hide_me_split_tunnel, "stop_hide_me", fake_stop)
    monkeypatch.setattr(hide_me_split_tunnel, "start_hide_me", fake_start)
    return calls


def test_hide_me_split_tunnel_is_opt_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(hide_me_split_tunnel.ENABLE_ENV, raising=False)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([tmp_path / "emulebb.exe"])

    assert result["enabled"] is False


def test_hide_me_split_tunnel_required_mode_ignores_opt_in_env(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "emulebb.exe"
    exe.write_bytes(b"exe")
    settings.write_text(json.dumps({"SplitTunneling": {"Whitelisted": [], "LimitToVpn": []}}), encoding="utf-8")
    monkeypatch.delenv(hide_me_split_tunnel.ENABLE_ENV, raising=False)
    monkeypatch.setenv(hide_me_split_tunnel.SETTINGS_PATH_ENV, str(settings))
    calls = stub_hide_me_stop_start(monkeypatch)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe], required=True)

    payload = json.loads(settings.read_text(encoding="utf-8"))
    assert result["enabled"] is True
    assert result["required"] is True
    assert result["changed"] is True
    assert result["restart"]["requested"] is True
    assert calls == ["stop", "start"]
    assert payload["SplitTunneling"]["Whitelisted"][0]["Path"] == str(exe.resolve())


def test_hide_me_split_tunnel_adds_existing_exe_to_whitelist_by_default(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "apps" / "eMuleBB" / "emulebb.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"exe")
    settings.write_text(
        json.dumps(
            {
                "Version": "4.3.2",
                "KillswitchWhitelist": [],
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
    calls = stub_hide_me_stop_start(monkeypatch)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe])

    payload = json.loads(settings.read_text(encoding="utf-8"))
    assert result["enabled"] is True
    assert result["changed"] is True
    assert Path(result["backup_path"]).is_file()
    assert result["restart"]["requested"] is True
    assert result["restart"]["vpn_ipv4"] == "10.54.216.129"
    assert result["allow_loopback"] is True
    assert result["added_loopback"] is True
    assert calls == ["stop", "start"]
    assert payload["SplitTunneling"]["Mode"] == 2
    assert payload["KillswitchWhitelist"] == [hide_me_split_tunnel.LOOPBACK_CIDR]
    assert payload["SplitTunneling"]["Whitelisted"][0]["Path"] == str(exe.resolve())
    assert payload["SplitTunneling"]["LimitToVpn"] == []


def test_hide_me_split_tunnel_only_updates_whitelisted_apps(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "apps" / "eMuleBB" / "emulebb.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"exe")
    unrelated_limit_entry = {"Name": "Other", "Path": r"C:\Tools\other.exe", "Paths": None, "Icon": None}
    settings.write_text(
        json.dumps(
            {
                "KillswitchWhitelist": [hide_me_split_tunnel.LOOPBACK_CIDR],
                "SplitTunneling": {
                    "Mode": 1,
                    "Whitelisted": [],
                    "LimitToVpn": [unrelated_limit_entry],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(hide_me_split_tunnel.ENABLE_ENV, "1")
    monkeypatch.setenv(hide_me_split_tunnel.SETTINGS_PATH_ENV, str(settings))
    calls = stub_hide_me_stop_start(monkeypatch)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe])

    payload = json.loads(settings.read_text(encoding="utf-8"))
    assert result["added_loopback"] is False
    assert calls == ["stop", "start"]
    assert payload["SplitTunneling"]["Mode"] == 2
    assert payload["SplitTunneling"]["Whitelisted"][0]["Path"] == str(exe.resolve())
    assert payload["SplitTunneling"]["LimitToVpn"] == [unrelated_limit_entry]


def test_hide_me_split_tunnel_can_skip_loopback_allowlist(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "emulebb.exe"
    exe.write_bytes(b"exe")
    settings.write_text(
        json.dumps({"KillswitchWhitelist": [], "SplitTunneling": {"Whitelisted": [], "LimitToVpn": []}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(hide_me_split_tunnel.ENABLE_ENV, "1")
    monkeypatch.setenv(hide_me_split_tunnel.ALLOW_LOOPBACK_ENV, "0")
    monkeypatch.setenv(hide_me_split_tunnel.SETTINGS_PATH_ENV, str(settings))
    calls = stub_hide_me_stop_start(monkeypatch)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe])

    payload = json.loads(settings.read_text(encoding="utf-8"))
    assert result["allow_loopback"] is False
    assert result["added_loopback"] is False
    assert calls == ["stop", "start"]
    assert payload["KillswitchWhitelist"] == []


def test_hide_me_split_tunnel_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "emulebb.exe"
    exe.write_bytes(b"exe")
    entry = {"Name": "eMuleBB", "Path": str(exe.resolve()), "Paths": None, "Icon": None}
    settings.write_text(
        json.dumps(
            {
                "KillswitchWhitelist": [hide_me_split_tunnel.LOOPBACK_CIDR],
                "SplitTunneling": {
                    "Mode": 2,
                    "Whitelisted": [entry],
                    "LimitToVpn": [entry],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(hide_me_split_tunnel.ENABLE_ENV, "true")
    monkeypatch.setenv(hide_me_split_tunnel.SETTINGS_PATH_ENV, str(settings))
    calls = stub_hide_me_stop_start(monkeypatch)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe])

    payload = json.loads(settings.read_text(encoding="utf-8"))
    assert result["changed"] is False
    assert calls == []
    assert len(payload["SplitTunneling"]["Whitelisted"]) == 1
    assert len(payload["SplitTunneling"]["LimitToVpn"]) == 1


def test_hide_me_split_tunnel_stops_before_writing_and_starts_after(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "vpn.settings"
    exe = tmp_path / "emulebb.exe"
    exe.write_bytes(b"exe")
    settings.write_text(json.dumps({"SplitTunneling": {"Whitelisted": [], "LimitToVpn": []}}), encoding="utf-8")
    monkeypatch.setenv(hide_me_split_tunnel.ENABLE_ENV, "1")
    monkeypatch.setenv(hide_me_split_tunnel.SETTINGS_PATH_ENV, str(settings))
    calls: list[str] = []

    def fake_stop():
        calls.append("stop")
        assert json.loads(settings.read_text(encoding="utf-8"))["SplitTunneling"]["Whitelisted"] == []
        return {"requested": True, "returncode": 0}

    def fake_start():
        calls.append("start")
        assert json.loads(settings.read_text(encoding="utf-8"))["SplitTunneling"]["Whitelisted"][0]["Path"] == str(exe.resolve())
        return {"requested": True, "returncode": 0, "vpn_ipv4": "10.54.216.129"}

    monkeypatch.setattr(hide_me_split_tunnel, "stop_hide_me", fake_stop)
    monkeypatch.setattr(hide_me_split_tunnel, "start_hide_me", fake_start)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([exe])

    assert result["restart"]["requested"] is True
    assert result["restart"]["vpn_ipv4"] == "10.54.216.129"
    assert calls == ["stop", "start"]


def test_hide_me_split_tunnel_waits_for_ipv4_after_restart(monkeypatch) -> None:
    calls: list[int] = []

    def fake_run(command, **kwargs):
        calls.append(1)

        class Completed:
            returncode = 0
            stdout = "" if len(calls) == 1 else "10.54.216.129\n"
            stderr = ""

        return Completed()

    monkeypatch.setattr(hide_me_split_tunnel.subprocess, "run", fake_run)
    monkeypatch.setattr(hide_me_split_tunnel.time, "sleep", lambda _seconds: None)

    assert hide_me_split_tunnel.wait_for_hide_me_ipv4_after_restart(timeout_seconds=10) == "10.54.216.129"
    assert len(calls) == 2


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


def test_hide_me_split_tunnel_treats_low_id_firewalled_as_port_failure(monkeypatch) -> None:
    monkeypatch.setenv(hide_me_split_tunnel.RESTART_ON_UPNP_FAILURE_ENV, "1")
    calls: list[bool] = []

    def fake_restart():
        calls.append(True)
        return {"requested": True, "returncode": 0}

    monkeypatch.setattr(hide_me_split_tunnel, "restart_hide_me", fake_restart)

    result = hide_me_split_tunnel.restart_hide_me_after_upnp_failure_if_requested(
        "networkStatus ed2k Low ID and kad Firewalled"
    )

    assert result["requested"] is True
    assert result["reason"] == "upnp_failure"
    assert calls == [True]


def test_hide_me_split_tunnel_skips_non_upnp_failure_restart(monkeypatch) -> None:
    monkeypatch.setenv(hide_me_split_tunnel.RESTART_ON_UPNP_FAILURE_ENV, "1")

    result = hide_me_split_tunnel.restart_hide_me_after_upnp_failure_if_requested("ARR handoff timed out")

    assert result["requested"] is False
    assert result["skipped"] == "failure did not match UPnP markers"
