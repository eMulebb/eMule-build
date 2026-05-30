from __future__ import annotations

import json
from pathlib import Path

from emule_workspace import hide_me_split_tunnel


def test_hide_me_split_tunnel_is_opt_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(hide_me_split_tunnel.ENABLE_ENV, raising=False)

    result = hide_me_split_tunnel.ensure_split_tunnel_apps([tmp_path / "emulebb.exe"])

    assert result["enabled"] is False


def test_hide_me_split_tunnel_adds_existing_exe_to_app_lists(tmp_path: Path, monkeypatch) -> None:
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
