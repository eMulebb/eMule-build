"""Product-family bootstrap and validation helpers."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from .layout import WorkspaceLayout
from .process import find_tool, run_native

ProductFamilyValidationTier = Literal["quick", "quality", "full"]


def prepare_product_family_repos(layout: WorkspaceLayout) -> None:
    """Fetches or installs repo-native dependencies for optional product-family repos."""

    agents_root = layout.p2p_overlord_agents_repo_root
    if agents_root is not None and (agents_root / "Cargo.toml").is_file():
        run_native(
            [_required_product_family_command(("cargo.exe", "cargo"), "Rust cargo"), "fetch"],
            label="p2p-overlord-agents cargo fetch",
            cwd=agents_root,
        )

    coordinator_root = _coordinator_root(layout)
    if coordinator_root is not None and (coordinator_root / "package-lock.json").is_file():
        npm = _required_product_family_command(("npm.cmd", "npm.exe", "npm"), "Node npm")
        run_native([npm, "ci"], label="p2p-overlord-be coordinator npm ci", cwd=coordinator_root)
        run_native(
            [npm, "run", "prisma:generate"],
            label="p2p-overlord-be coordinator prisma generate",
            cwd=coordinator_root,
        )

    goed2k_root = layout.ed2k_server_repo_root
    if goed2k_root.is_dir() and (goed2k_root / "go.mod").is_file():
        run_native(
            [_required_product_family_command(("go.exe", "go"), "Go toolchain"), "mod", "download"],
            label="goed2k-server go mod download",
            cwd=goed2k_root,
        )


def validate_product_family_repos(layout: WorkspaceLayout, *, tier: ProductFamilyValidationTier = "quality") -> None:
    """Runs repo-native checks for non-app product-family repositories."""

    if tier not in ("quick", "quality", "full"):
        raise ValueError(f"Unsupported product-family validation tier: {tier}")

    agents_root = layout.p2p_overlord_agents_repo_root
    if agents_root is not None and agents_root.is_dir():
        cargo = _required_product_family_command(("cargo.exe", "cargo"), "Rust cargo")
        run_native(
            [cargo, "fmt", "--all", "--check"],
            label="p2p-overlord-agents cargo fmt",
            cwd=agents_root,
        )
        if tier == "full":
            run_native(
                [
                    cargo,
                    "clippy",
                    "--workspace",
                    "--all-targets",
                    "--all-features",
                    "--",
                    "-D",
                    "warnings",
                    "-W",
                    "clippy::all",
                    "-W",
                    "clippy::too_many_arguments",
                    "-W",
                    "clippy::type_complexity",
                    "-W",
                    "clippy::cognitive_complexity",
                ],
                label="p2p-overlord-agents cargo clippy",
                cwd=agents_root,
            )
            run_native(
                [cargo, "test", "--workspace", "--all-targets", "--all-features"],
                label="p2p-overlord-agents cargo test",
                cwd=agents_root,
            )

    coordinator_root = _coordinator_root(layout)
    if coordinator_root is not None and coordinator_root.is_dir():
        npm = _required_product_family_command(("npm.cmd", "npm.exe", "npm"), "Node npm")
        script = "prisma:validate" if tier == "quick" else "quality"
        run_native(
            [npm, "run", script],
            label=f"p2p-overlord-be coordinator {script}",
            cwd=coordinator_root,
        )

    goed2k_root = layout.ed2k_server_repo_root
    if goed2k_root.is_dir():
        run_native(
            [_required_product_family_command(("go.exe", "go"), "Go toolchain"), "test", "./..."],
            label="goed2k-server go test",
            cwd=goed2k_root,
        )


def _coordinator_root(layout: WorkspaceLayout) -> Path | None:
    be_root = layout.p2p_overlord_be_repo_root
    return be_root / "overlord-be-coordinator" if be_root is not None else None


def _required_product_family_command(names: tuple[str, ...], label: str) -> str:
    for name in names:
        if shutil.which(name):
            return name
    if find_tool(names) is None:
        raise RuntimeError(f"{label} was not found on PATH for product-family operations.")
    return names[0]
