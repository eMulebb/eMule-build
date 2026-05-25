"""Workspace test-network selection and interface resolution."""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

TestNetwork = Literal["default", "offline", "lan", "vpn", "all"]
VpnTestNetwork = Literal["vpn", "all"]

DEFAULT_VPN_INTERFACE = "hide.me"
LAN_INTERFACE_ENV = "EMULEBB_TEST_LAN_INTERFACE"
VPN_INTERFACE_ENV = "EMULEBB_TEST_VPN_INTERFACE"
LAN_IP_ENV = "EMULEBB_TEST_LAN_IP"
VPN_IP_ENV = "EMULEBB_TEST_VPN_IP"
LAN_IP_RESOLVED_ENV = "EMULEBB_TEST_LAN_IP_RESOLVED"
VPN_IP_RESOLVED_ENV = "EMULEBB_TEST_VPN_IP_RESOLVED"
NETWORK_ENV = "EMULEBB_TEST_NETWORK"
NETWORK_CONTEXT_JSON_ENV = "EMULEBB_TEST_NETWORK_CONTEXT_JSON"
OVERLORD_LIVE_INTERFACE_ALIAS_ENV = "OVERLORD_LIVE_INTERFACE_ALIAS"

WINDOWS_IPV4_QUERY = (
    "Get-NetIPAddress -AddressFamily IPv4 "
    "| Select-Object InterfaceAlias,IPAddress,SkipAsSource,AddressState "
    "| ConvertTo-Json -Compress"
)


@dataclass(frozen=True)
class InterfaceResolution:
    """Resolved IPv4 binding snapshot for one interface role."""

    role: str
    interface_name: str
    ip_address: str
    source: str
    resolved_utc: str

    def as_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "interface_name": self.interface_name,
            "ip_address": self.ip_address,
            "source": self.source,
            "resolved_utc": self.resolved_utc,
        }


@dataclass(frozen=True)
class WorkspaceNetworkContext:
    """Resolved network context propagated to workspace child runners."""

    test_network: TestNetwork
    context_path: Path
    lan: InterfaceResolution | None = None
    vpn: InterfaceResolution | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "emulebb.test-network-context.v1",
            "generated_utc": utc_timestamp(),
            "test_network": self.test_network,
            "lan": self.lan.as_dict() if self.lan else None,
            "vpn": self.vpn.as_dict() if self.vpn else None,
        }

    def env(self) -> dict[str, str]:
        values = {
            NETWORK_ENV: self.test_network,
            NETWORK_CONTEXT_JSON_ENV: str(self.context_path),
        }
        if self.lan is not None:
            values[LAN_INTERFACE_ENV] = self.lan.interface_name
            values[LAN_IP_RESOLVED_ENV] = self.lan.ip_address
        if self.vpn is not None:
            values[VPN_INTERFACE_ENV] = self.vpn.interface_name
            values[VPN_IP_RESOLVED_ENV] = self.vpn.ip_address
            values[OVERLORD_LIVE_INTERFACE_ALIAS_ENV] = self.vpn.interface_name
        return values


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def utc_file_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def resolve_workspace_network_context(
    *,
    workspace_root: Path,
    test_network: TestNetwork,
    vpn_interface_name: str | None = None,
    require_vpn: bool = False,
    require_lan: bool = False,
) -> WorkspaceNetworkContext:
    """Resolves the workspace test-network context and writes its JSON report."""

    resolved_test_network = normalize_test_network(test_network)
    lan = None
    vpn = None
    if resolved_test_network in {"default", "lan", "all"} or require_lan:
        lan = resolve_lan_interface(required=resolved_test_network in {"lan", "all"} or require_lan)
    if resolved_test_network in {"vpn", "all"} or require_vpn:
        vpn = resolve_vpn_interface(vpn_interface_name=vpn_interface_name)

    context_path = (
        workspace_root.resolve()
        / "state"
        / "network-context"
        / f"{utc_file_stamp()}-{os.getpid()}-{resolved_test_network}.json"
    )
    context = WorkspaceNetworkContext(
        test_network=resolved_test_network,
        context_path=context_path,
        lan=lan,
        vpn=vpn,
    )
    write_network_context(context)
    return context


def normalize_test_network(value: str) -> TestNetwork:
    normalized = value.strip().lower()
    if normalized not in {"default", "offline", "lan", "vpn", "all"}:
        raise ValueError(f"Unsupported test network: {value}")
    return cast(TestNetwork, normalized)


def write_network_context(context: WorkspaceNetworkContext) -> None:
    context.context_path.parent.mkdir(parents=True, exist_ok=True)
    context.context_path.write_text(
        json.dumps(context.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def resolve_lan_interface(*, required: bool) -> InterfaceResolution | None:
    explicit_ip = os.environ.get(LAN_IP_ENV, "").strip()
    explicit_interface = os.environ.get(LAN_INTERFACE_ENV, "").strip()
    if explicit_ip:
        validate_lan_ip(explicit_ip)
        return InterfaceResolution(
            role="lan",
            interface_name=explicit_interface,
            ip_address=explicit_ip,
            source="env-ip",
            resolved_utc=utc_timestamp(),
        )

    try:
        candidates = query_ipv4_candidates()
    except RuntimeError:
        if required or explicit_interface:
            raise
        return None
    if explicit_interface:
        selected = choose_ip_for_interface(candidates, explicit_interface, require_lan=True)
        return InterfaceResolution(
            role="lan",
            interface_name=explicit_interface,
            ip_address=selected["ip_address"],
            source="interface",
            resolved_utc=utc_timestamp(),
        )

    selected = choose_best_lan_candidate(candidates)
    if selected is None:
        if required:
            raise RuntimeError(
                "LAN test network requires a non-loopback private IPv4. "
                f"Set {LAN_INTERFACE_ENV} or {LAN_IP_ENV}."
            )
        return None
    return InterfaceResolution(
        role="lan",
        interface_name=selected["interface_alias"],
        ip_address=selected["ip_address"],
        source="auto",
        resolved_utc=utc_timestamp(),
    )


def resolve_vpn_interface(*, vpn_interface_name: str | None = None) -> InterfaceResolution:
    explicit_ip = os.environ.get(VPN_IP_ENV, "").strip()
    interface_name = (
        os.environ.get(VPN_INTERFACE_ENV, "").strip()
        or (vpn_interface_name or "").strip()
        or DEFAULT_VPN_INTERFACE
    )
    if explicit_ip:
        validate_bind_ip(explicit_ip, role="VPN")
        return InterfaceResolution(
            role="vpn",
            interface_name=interface_name,
            ip_address=explicit_ip,
            source="env-ip",
            resolved_utc=utc_timestamp(),
        )

    selected = choose_ip_for_interface(query_ipv4_candidates(), interface_name, require_lan=False)
    return InterfaceResolution(
        role="vpn",
        interface_name=interface_name,
        ip_address=selected["ip_address"],
        source="interface",
        resolved_utc=utc_timestamp(),
    )


def query_ipv4_candidates() -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", WINDOWS_IPV4_QUERY],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Unable to query Windows IPv4 interfaces: {completed.stderr.strip()}")
    payload = json.loads(completed.stdout or "[]")
    return normalize_interface_candidates(payload)


def normalize_interface_candidates(payload: object) -> list[dict[str, Any]]:
    items: list[dict[str, Any]]
    if isinstance(payload, dict):
        items = [payload]
    elif isinstance(payload, list):
        items = [item for item in payload if isinstance(item, dict)]
    else:
        return []

    normalized: list[dict[str, Any]] = []
    for item in items:
        interface_alias = str(item.get("InterfaceAlias") or "").strip()
        ip_address = str(item.get("IPAddress") or "").strip()
        if not interface_alias or not ip_address:
            continue
        normalized.append(
            {
                "interface_alias": interface_alias,
                "ip_address": ip_address,
                "skip_as_source": bool(item.get("SkipAsSource")),
                "address_state": str(item.get("AddressState") or "").strip(),
            }
        )
    return normalized


def choose_ip_for_interface(
    candidates: list[dict[str, Any]],
    interface_name: str,
    *,
    require_lan: bool,
) -> dict[str, str]:
    matching = [
        candidate
        for candidate in candidates
        if str(candidate.get("interface_alias", "")).casefold() == interface_name.casefold()
    ]
    if require_lan:
        matching = [candidate for candidate in matching if is_valid_lan_ip(str(candidate.get("ip_address", "")))]
    else:
        matching = [candidate for candidate in matching if is_valid_bind_ip(str(candidate.get("ip_address", "")))]
    if not matching:
        aliases = sorted(
            {
                str(candidate.get("interface_alias", "")).strip()
                for candidate in candidates
                if str(candidate.get("interface_alias", "")).strip()
            }
        )
        role = "LAN" if require_lan else "VPN"
        raise RuntimeError(f"{role} interface {interface_name!r} did not resolve to a usable IPv4; available aliases: {aliases}")
    selected = sorted(matching, key=candidate_rank)[0]
    return {
        "interface_alias": str(selected["interface_alias"]),
        "ip_address": str(selected["ip_address"]),
    }


def choose_best_lan_candidate(candidates: list[dict[str, Any]]) -> dict[str, str] | None:
    matching = [candidate for candidate in candidates if is_valid_lan_ip(str(candidate.get("ip_address", "")))]
    if not matching:
        return None
    selected = sorted(matching, key=lan_candidate_rank)[0]
    return {
        "interface_alias": str(selected["interface_alias"]),
        "ip_address": str(selected["ip_address"]),
    }


def candidate_rank(candidate: dict[str, Any]) -> tuple[int, int, str]:
    address_state = str(candidate.get("address_state", "")).casefold()
    skip_as_source = bool(candidate.get("skip_as_source"))
    ip_address = str(candidate.get("ip_address", ""))
    return (
        0 if address_state == "preferred" else 1,
        1 if skip_as_source else 0,
        ip_address,
    )


def lan_candidate_rank(candidate: dict[str, Any]) -> tuple[int, int, int, int, str]:
    alias = str(candidate.get("interface_alias", ""))
    ip_address = str(candidate.get("ip_address", ""))
    return (
        1 if looks_like_vpn_interface(alias) else 0,
        lan_range_rank(ip_address),
        *candidate_rank(candidate),
    )


def looks_like_vpn_interface(interface_name: str) -> bool:
    lowered = interface_name.casefold()
    return any(token in lowered for token in ("vpn", "hide.me", "tap", "tun", "wireguard", "tailscale"))


def lan_range_rank(ip_address: str) -> int:
    if ip_address.startswith("192.168."):
        return 0
    if ip_address.startswith("172."):
        return 1
    if ip_address.startswith("10."):
        return 2
    return 3


def validate_lan_ip(value: str) -> None:
    parsed = validate_bind_ip(value, role="LAN")
    if not parsed.is_private:
        raise ValueError(f"LAN IP {value!r} is not a private IPv4 address.")


def validate_bind_ip(value: str, *, role: str) -> ipaddress.IPv4Address:
    parsed = ipaddress.ip_address(value)
    if parsed.version != 4:
        raise ValueError(f"{role} IP {value!r} is not an IPv4 address.")
    parsed_v4 = cast(ipaddress.IPv4Address, parsed)
    if parsed_v4.is_loopback or parsed_v4.is_link_local or parsed_v4.is_unspecified:
        raise ValueError(f"{role} IP {value!r} is not usable for a test bind.")
    return parsed_v4


def is_valid_bind_ip(value: str) -> bool:
    try:
        validate_bind_ip(value, role="bind")
    except ValueError:
        return False
    return True


def is_valid_lan_ip(value: str) -> bool:
    try:
        validate_lan_ip(value)
    except ValueError:
        return False
    return True
