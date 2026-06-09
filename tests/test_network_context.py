from __future__ import annotations

import json

import pytest

from emule_workspace import network_context


def test_default_context_auto_resolves_lan_and_writes_json(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(network_context.LAN_IP_ENV, raising=False)
    monkeypatch.delenv(network_context.LAN_INTERFACE_ENV, raising=False)
    monkeypatch.delenv(network_context.X_LOCAL_IP_ENV, raising=False)
    monkeypatch.delenv(network_context.VPN_IP_ENV, raising=False)
    monkeypatch.setattr(
        network_context,
        "query_ipv4_candidates",
        lambda: [
            {
                "interface_alias": "hide.me",
                "ip_address": "10.9.0.5",
                "skip_as_source": False,
                "address_state": "Preferred",
            },
            {
                "interface_alias": "Wi-Fi",
                "ip_address": "192.168.1.42",
                "skip_as_source": False,
                "address_state": "Preferred",
            },
        ],
    )

    context = network_context.resolve_workspace_network_context(
        workspace_root=tmp_path,
        output_root=tmp_path / "output",
        test_network="default",
    )

    assert context.test_network == "default"
    assert context.lan is not None
    assert context.lan.interface_name == "Wi-Fi"
    assert context.lan.ip_address == "192.168.1.42"
    assert context.vpn is None
    assert context.context_path.is_file()
    assert context.context_path.parent == tmp_path / "output" / "reports" / "network-context"
    payload = json.loads(context.context_path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "emulebb.test-network-context.v1"
    assert payload["lan"]["ip_address"] == "192.168.1.42"
    assert context.env()[network_context.LAN_IP_RESOLVED_ENV] == "192.168.1.42"
    assert network_context.VPN_IP_RESOLVED_ENV not in context.env()


def test_lan_explicit_ip_takes_precedence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(network_context.LAN_IP_ENV, "192.168.1.80")
    monkeypatch.setenv(network_context.LAN_INTERFACE_ENV, "Ethernet")
    monkeypatch.setattr(network_context, "query_ipv4_candidates", lambda: [])

    context = network_context.resolve_workspace_network_context(
        workspace_root=tmp_path,
        output_root=tmp_path / "output",
        test_network="lan",
    )

    assert context.lan is not None
    assert context.lan.interface_name == "Ethernet"
    assert context.lan.ip_address == "192.168.1.80"
    assert context.lan.source == "env-ip"


def test_lan_uses_x_local_ip_when_harness_lan_ip_is_unset(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(network_context.LAN_IP_ENV, raising=False)
    monkeypatch.setenv(network_context.X_LOCAL_IP_ENV, "192.168.1.81")
    monkeypatch.setattr(network_context, "query_ipv4_candidates", lambda: [])

    context = network_context.resolve_workspace_network_context(
        workspace_root=tmp_path,
        output_root=tmp_path / "output",
        test_network="lan",
    )

    assert context.lan is not None
    assert context.lan.ip_address == "192.168.1.81"
    assert context.lan.source == "env-ip"


def test_lan_rejects_non_private_explicit_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(network_context.LAN_IP_ENV, "8.8.8.8")

    with pytest.raises(ValueError, match="not a private IPv4"):
        network_context.resolve_lan_interface(required=True)


def test_lan_auto_does_not_select_hideme_10_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(network_context.LAN_IP_ENV, raising=False)
    monkeypatch.delenv(network_context.X_LOCAL_IP_ENV, raising=False)
    monkeypatch.delenv(network_context.LAN_INTERFACE_ENV, raising=False)
    monkeypatch.setattr(
        network_context,
        "query_ipv4_candidates",
        lambda: [
            {
                "interface_alias": "hide.me",
                "ip_address": "10.9.0.5",
                "skip_as_source": False,
                "address_state": "Preferred",
            },
        ],
    )

    assert network_context.resolve_lan_interface(required=False) is None
    with pytest.raises(RuntimeError, match="non-loopback private IPv4"):
        network_context.resolve_lan_interface(required=True)


def test_lan_rejects_explicit_hideme_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(network_context.LAN_IP_ENV, raising=False)
    monkeypatch.delenv(network_context.X_LOCAL_IP_ENV, raising=False)
    monkeypatch.setenv(network_context.LAN_INTERFACE_ENV, "hide.me")
    monkeypatch.setattr(
        network_context,
        "query_ipv4_candidates",
        lambda: [
            {
                "interface_alias": "hide.me",
                "ip_address": "10.9.0.5",
                "skip_as_source": False,
                "address_state": "Preferred",
            },
        ],
    )

    with pytest.raises(RuntimeError, match="looks like a VPN adapter"):
        network_context.resolve_lan_interface(required=True)


def test_vpn_context_uses_explicit_ip_and_maps_overlord_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(network_context.VPN_IP_ENV, "10.8.0.4")
    monkeypatch.setenv(network_context.VPN_INTERFACE_ENV, "hide.me")
    monkeypatch.setattr(network_context, "query_ipv4_candidates", lambda: [])

    context = network_context.resolve_workspace_network_context(
        workspace_root=tmp_path,
        output_root=tmp_path / "output",
        test_network="vpn",
    )

    assert context.vpn is not None
    assert context.vpn.interface_name == "hide.me"
    assert context.vpn.ip_address == "10.8.0.4"
    env = context.env()
    assert env[network_context.VPN_IP_RESOLVED_ENV] == "10.8.0.4"
    assert env[network_context.OVERLORD_LIVE_INTERFACE_ALIAS_ENV] == "hide.me"
