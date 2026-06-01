from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalPackageArtifacts:
    release_root: Path
    package_build_root: Path
    emule_zip: Path
    emule_manifest: Path
    emule_sbom: Path
    amutorrent_zip: Path
    amutorrent_manifest: Path
    amutorrent_sbom: Path
    package_exe: Path
    package_pdb: Path


@dataclass(frozen=True)
class CoreRelease:
    release_root: Path
    package_zip: Path
    manifest: Path


def write_core_release(
    release_root: Path,
    *,
    version: str = "0.7.3-rc.1",
    arch: str = "x64",
    package_flavor: str = "standard",
    executable_name: str | None = None,
    exe_payload: bytes = b"exe\n",
    installer_payload: bytes | None = None,
) -> CoreRelease:
    if executable_name is None:
        executable_name = "emulebb-diagnostics.exe" if package_flavor == "diagnostics" else "emulebb.exe"
    flavor_asset_suffix = "" if package_flavor == "standard" else f"-{package_flavor}"
    package_zip = release_root / f"emulebb-{version}{flavor_asset_suffix}-{arch}.zip"
    manifest = release_root / f"emulebb-{version}{flavor_asset_suffix}-{arch}.manifest.json"
    if installer_payload is None:
        installer_payload = (
            Path("emule_workspace")
            / "release_assets"
            / "emulebb"
            / "scripts"
            / "Install-eMuleBBSuite.ps1"
        ).read_bytes()
    write_zip(
        package_zip,
        {
            f"eMuleBB/{executable_name}": exe_payload,
            "eMuleBB/scripts/Install-eMuleBBSuite.ps1": installer_payload,
        },
    )
    write_manifest(manifest, package_zip)
    return CoreRelease(release_root=release_root, package_zip=package_zip, manifest=manifest)


def run_installer(
    installer: Path,
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell")
    assert powershell is not None
    return subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer), *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def read_suite_config(install_root: Path) -> dict[str, object]:
    return json.loads((install_root / "manifests" / "suite-config.json").read_text(encoding="utf-8-sig"))


def read_suite_install_manifest(install_root: Path) -> dict[str, object]:
    return json.loads((install_root / "manifests" / "suite-install.json").read_text(encoding="utf-8-sig"))


def read_suite_preferences(install_root: Path) -> str:
    return (install_root / "profiles" / "emulebb" / "config" / "preferences.ini").read_text(encoding="utf-16")


def write_zip(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def write_manifest(path: Path, zip_path: Path) -> None:
    path.write_text(json.dumps({"sha256": sha256_bytes(zip_path.read_bytes())}) + "\n", encoding="utf-8")


def write_local_package_artifacts(
    workspace_root: Path,
    *,
    version: str,
    arch: str = "x64",
    package_flavor: str = "standard",
    package_exe_payload: bytes = b"exe",
    zip_exe_payload: bytes | None = None,
    package_pdb_payload: bytes = b"pdb",
    installer_payload: bytes = b"#Requires -Version 5.1\n",
) -> LocalPackageArtifacts:
    release_root = workspace_root / "state" / "release" / f"emulebb-v{version}"
    package_build_root = workspace_root / "state" / "package-build" / f"emulebb-v{version}" / arch / package_flavor / "app"
    package_build_root.mkdir(parents=True)
    executable_name = "emulebb-diagnostics.exe" if package_flavor == "diagnostics" else "emulebb.exe"
    pdb_name = Path(executable_name).with_suffix(".pdb").name
    package_exe = package_build_root / executable_name
    package_pdb = package_build_root / pdb_name
    package_exe.write_bytes(package_exe_payload)
    package_pdb.write_bytes(package_pdb_payload)

    flavor_asset_suffix = "" if package_flavor == "standard" else f"-{package_flavor}"
    emule_zip = release_root / f"emulebb-{version}{flavor_asset_suffix}-{arch}.zip"
    amutorrent_zip = release_root / f"emulebb-{version}-amutorrent-{arch}.zip"
    write_zip(
        emule_zip,
        {
            f"eMuleBB/{executable_name}": zip_exe_payload if zip_exe_payload is not None else package_exe_payload,
            "eMuleBB/scripts/Install-eMuleBBSuite.ps1": installer_payload,
        },
    )
    write_zip(amutorrent_zip, {"aMuTorrent/server/server.js": b"server\n"})

    emule_manifest = release_root / f"emulebb-{version}{flavor_asset_suffix}-{arch}.manifest.json"
    emule_sbom = release_root / f"emulebb-{version}{flavor_asset_suffix}-{arch}.sbom.spdx.json"
    amutorrent_manifest = release_root / f"emulebb-{version}-amutorrent-{arch}.manifest.json"
    amutorrent_sbom = release_root / f"emulebb-{version}-amutorrent-{arch}.sbom.spdx.json"
    for path in (emule_manifest, emule_sbom, amutorrent_manifest, amutorrent_sbom):
        path.write_text("{}\n", encoding="utf-8")

    return LocalPackageArtifacts(
        release_root=release_root,
        package_build_root=package_build_root,
        emule_zip=emule_zip,
        emule_manifest=emule_manifest,
        emule_sbom=emule_sbom,
        amutorrent_zip=amutorrent_zip,
        amutorrent_manifest=amutorrent_manifest,
        amutorrent_sbom=amutorrent_sbom,
        package_exe=package_exe,
        package_pdb=package_pdb,
    )


def write_dependency_manifest(path: Path, dependency_root: Path) -> None:
    node_zip = dependency_root / "node-v24.15.0-win-x64.zip"
    prowlarr_zip = dependency_root / "prowlarr.zip"
    radarr_zip = dependency_root / "radarr.zip"
    sonarr_zip = dependency_root / "sonarr.zip"
    write_zip(node_zip, {"node-v24.15.0-win-x64/node.exe": b"node\n"})
    write_zip(prowlarr_zip, {"Prowlarr/Prowlarr.exe": b"prowlarr\n"})
    write_zip(radarr_zip, {"Radarr/Radarr.exe": b"radarr\n"})
    write_zip(sonarr_zip, {"Sonarr/Sonarr.exe": b"sonarr\n"})
    payload = {
        "node": dependency_spec(node_zip, file_name=node_zip.name),
        "prowlarr": arr_dependency_spec(prowlarr_zip, "Prowlarr.exe"),
        "radarr": arr_dependency_spec(radarr_zip, "Radarr.exe"),
        "sonarr": arr_dependency_spec(sonarr_zip, "Sonarr.exe"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def dependency_spec(path: Path, *, file_name: str | None = None) -> dict[str, str]:
    payload = {"url": path.as_uri(), "sha256": sha256_bytes(path.read_bytes())}
    if file_name is not None:
        payload["fileName"] = file_name
    return payload


def arr_dependency_spec(path: Path, exe_name: str) -> dict[str, str]:
    return {
        "repo": "",
        "tag": "",
        "assetPattern": "",
        "exeName": exe_name,
        **dependency_spec(path),
    }


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
