"""Release package orchestration."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .build import APP_EXE_NAME, app_property_overrides, ensure_app_dependency_artifacts, verify_app_control_flow_guard, with_trailing_separator
from .artifact_names import utc_run_id
from .build_state import BuildSession
from .config import AmutorrentPackageOptions, ReleasePackageOptions, WorkspaceOptions
from .git import git_output, repo_branch, repo_head, repo_status_lines
from .layout import AppVariant, WorkspaceLayout
from .msbuild import env_override, invoke_msbuild_project

PE_MACHINES = {"x64": 0x8664, "ARM64": 0xAA64}
STARTUP_PROFILING_BINARY_MARKERS = (
    b"startup-profile.trace.json",
    "startup-profile.trace.json".encode("utf-16le"),
    b"EMULE_STARTUP_PROFILE",
    "EMULE_STARTUP_PROFILE".encode("utf-16le"),
)
AMUTORRENT_NODE_VERSION = "v24.15.0"
AMUTORRENT_NODE_ARCHIVES = {
    "x64": (
        "node-v24.15.0-win-x64.zip",
        "cc5149eabd53779ce1e7bdc5401643622d0c7e6800ade18928a767e940bb0e62",
    ),
    "ARM64": (
        "node-v24.15.0-win-arm64.zip",
        "c9eb7402eda26e2ba7e44b6727fc85a8de56c5095b1f71ebd3062892211aa116",
    ),
}
RELEASE_THIRD_PARTY_COMPONENTS = (
    ("Crypto++", "Boost-1.0"),
    ("id3lib", "LGPL-2.0-only"),
    ("miniupnpc", "BSD-3-Clause"),
    ("libpcpnatpmp", "NOASSERTION"),
    ("ResizableLib", "Artistic-2.0"),
    ("zlib", "Zlib"),
    ("Mbed TLS / TF-PSA-Crypto", "Apache-2.0 OR GPL-2.0-or-later"),
    ("nlohmann/json", "MIT"),
)
RELEASE_VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:-(?:rc|beta)\.\d+)?")


def create_amutorrent_package(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    package_options: AmutorrentPackageOptions,
) -> None:
    """Builds the optional aMuTorrent controller ZIP plus manifest."""

    if workspace_options.configuration != "Release":
        raise RuntimeError("package amutorrent requires --config Release.")
    if not _is_release_version(package_options.release_version):
        raise RuntimeError(
            "Release version must use MAJOR.MINOR.PATCH[-rc.N|-beta.N] format: "
            f"{package_options.release_version}"
        )

    amutorrent_root = layout.resolve_workspace_path("repos/amutorrent")
    _assert_clean_amutorrent_package_inputs(layout, amutorrent_root)
    _assert_packaging_node_supported(workspace_options.platform)
    _build_amutorrent_webapp(amutorrent_root, package_options.clean)

    asset_arch = "arm64" if workspace_options.platform == "ARM64" else "x64"
    release_root = layout.workspace_root / "state" / "release" / f"emulebb-v{package_options.release_version}"
    staging_root = release_root / "staging" / f"amutorrent-{asset_arch}"
    package_root = staging_root / "aMuTorrent"
    zip_path = release_root / f"emulebb-{package_options.release_version}-amutorrent-{asset_arch}.zip"
    manifest_path = release_root / f"emulebb-{package_options.release_version}-amutorrent-{asset_arch}.manifest.json"
    sbom_path = release_root / f"emulebb-{package_options.release_version}-amutorrent-{asset_arch}.sbom.spdx.json"
    for path_to_check in (staging_root, package_root, zip_path, manifest_path, sbom_path):
        _assert_path_under_root(path_to_check, release_root, "aMuTorrent package path")

    if staging_root.exists():
        shutil.rmtree(staging_root)
    package_root.mkdir(parents=True, exist_ok=True)
    _copy_amutorrent_runtime(amutorrent_root, package_root)
    _write_amutorrent_readme(package_root, package_options.release_version, workspace_options.platform)
    _copy_package_file(amutorrent_root / "LICENSE", package_root, Path("LICENSE-aMuTorrent.txt"))
    _write_amutorrent_sbom(
        layout=layout,
        workspace_options=workspace_options,
        package_options=package_options,
        amutorrent_root=amutorrent_root,
        package_root=package_root,
        release_root=release_root,
        asset_name=zip_path.name,
    )

    if zip_path.exists():
        zip_path.unlink()
    release_root.mkdir(parents=True, exist_ok=True)
    _write_zip(staging_root, package_root, zip_path)
    _assert_amutorrent_package_contents(zip_path)

    zip_hash = _sha256(zip_path)
    package_file_hashes = _zip_entry_hashes(zip_path)
    shutil.copy2(package_root / "SBOM.spdx.json", sbom_path)
    sbom_hash = _sha256(sbom_path)
    manifest = _build_amutorrent_manifest(
        layout=layout,
        workspace_options=workspace_options,
        package_options=package_options,
        amutorrent_root=amutorrent_root,
        zip_path=zip_path,
        release_root=release_root,
        zip_hash=zip_hash,
        sbom_path=sbom_path,
        sbom_hash=sbom_hash,
        package_file_hashes=package_file_hashes,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"aMuTorrent package: {zip_path}")
    print(f"aMuTorrent manifest: {manifest_path}")
    print(f"aMuTorrent SBOM: {sbom_path}")
    print(f"SHA256: {zip_hash}")


def create_release_package(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    package_options: ReleasePackageOptions,
) -> None:
    """Builds the main app and creates a release ZIP plus manifest."""

    if workspace_options.configuration != "Release":
        raise RuntimeError("package release requires --config Release.")
    if not _is_release_version(package_options.release_version):
        raise RuntimeError(
            "Release version must use MAJOR.MINOR.PATCH[-rc.N|-beta.N] format: "
            f"{package_options.release_version}"
        )

    ensure_canonical_app_anchor(layout)
    app_variant = layout.get_app_variant("main")
    app_root = app_variant.path
    _assert_release_source_branch(app_variant)
    _assert_clean_release_inputs(layout, app_root)
    _assert_package_version_matches_app(app_root, package_options.release_version)

    asset_arch = _release_asset_arch(workspace_options.platform)
    release_root = _release_root(layout, package_options)
    package_build_root = _package_build_root(layout, package_options, workspace_options.platform)
    package_app_output_root = package_build_root / "app"
    package_app_intermediate_root = package_build_root / "app-obj"
    _assert_path_under_root(package_build_root, layout.workspace_root / "state", "release package build path")
    if package_options.clean and package_build_root.exists():
        shutil.rmtree(package_build_root)

    session = BuildSession(
        layout=layout,
        options=workspace_options,
        command_name="package release",
        clean=package_options.clean,
        stamp=utc_run_id(),
    )
    try:
        _build_package_app(
            session,
            app_root,
            package_app_output_root=package_app_output_root,
            package_app_intermediate_root=package_app_intermediate_root,
            clean=package_options.clean,
        )
        _build_language_resources(session, app_root, package_options.clean)
    finally:
        session.write_recap()

    exe_path = package_app_output_root / APP_EXE_NAME
    expected_language_dlls = _expected_language_dlls(layout.tooling_repo_root)
    lang_path = _package_language_path(app_root, workspace_options.platform, expected_language_dlls)
    webserver_path = _package_webserver_path(app_root, package_app_output_root)
    for required_path in (exe_path, lang_path, webserver_path):
        if not required_path.exists():
            raise RuntimeError(f"Cannot package missing release runtime path: {required_path}")
    _assert_pe_machine(exe_path, workspace_options.platform)
    _assert_startup_profiling_not_compiled(exe_path)

    staging_root = release_root / "staging" / asset_arch
    package_root = staging_root / "eMule"
    zip_path = release_root / f"emulebb-{package_options.release_version}-{asset_arch}.zip"
    manifest_path = release_root / f"emulebb-{package_options.release_version}-{asset_arch}.manifest.json"
    sbom_path = release_root / f"emulebb-{package_options.release_version}-{asset_arch}.sbom.spdx.json"
    for path_to_check in (staging_root, package_root, zip_path, manifest_path, sbom_path):
        _assert_path_under_root(path_to_check, release_root, "release package path")

    if staging_root.exists():
        shutil.rmtree(staging_root)
    package_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe_path, package_root / APP_EXE_NAME)
    _copy_directory_contents(lang_path, package_root / "lang")
    _copy_directory_contents(webserver_path, package_root / "webserver")
    _write_package_readme(package_root, package_options.release_version, workspace_options.platform)
    _write_package_release_notes(package_root, package_options.release_version)
    _write_package_license_notice(package_root)
    _write_package_third_party_notices(package_root)
    _write_package_gpl_text(layout, package_root)
    _copy_package_file(
        layout.tooling_repo_root / "docs" / "rest" / "REST-API-CONTRACT.md",
        package_root,
        Path("docs/REST-API-CONTRACT.md"),
    )
    _copy_package_file(
        layout.tooling_repo_root / "docs" / "rest" / "REST-API-OPENAPI.yaml",
        package_root,
        Path("docs/REST-API-OPENAPI.yaml"),
    )
    _copy_package_file(
        layout.tooling_repo_root / "docs" / "rest" / "REST-API-PARITY-INVENTORY.md",
        package_root,
        Path("docs/REST-API-PARITY-INVENTORY.md"),
    )
    _write_release_sbom(
        layout=layout,
        workspace_options=workspace_options,
        package_options=package_options,
        app_variant=app_variant,
        app_root=app_root,
        package_root=package_root,
        release_root=release_root,
        asset_name=zip_path.name,
    )

    if zip_path.exists():
        zip_path.unlink()
    release_root.mkdir(parents=True, exist_ok=True)
    _write_zip(staging_root, package_root, zip_path)
    _assert_release_package_contents(zip_path, expected_language_dlls, workspace_options.platform)

    zip_hash = _sha256(zip_path)
    exe_hash = _sha256(exe_path)
    package_file_hashes = _zip_entry_hashes(zip_path)
    shutil.copy2(package_root / "SBOM.spdx.json", sbom_path)
    sbom_hash = _sha256(sbom_path)
    manifest = _build_release_manifest(
        layout=layout,
        workspace_options=workspace_options,
        package_options=package_options,
        app_variant=app_variant,
        app_root=app_root,
        zip_path=zip_path,
        release_root=release_root,
        zip_hash=zip_hash,
        sbom_path=sbom_path,
        sbom_hash=sbom_hash,
        exe_hash=exe_hash,
        expected_language_dlls=expected_language_dlls,
        package_file_hashes=package_file_hashes,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Release package: {zip_path}")
    print(f"Release manifest: {manifest_path}")
    print(f"Release SBOM: {sbom_path}")
    print(f"SHA256: {zip_hash}")


def _build_release_manifest(
    *,
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    package_options: ReleasePackageOptions,
    app_variant: AppVariant,
    app_root: Path,
    zip_path: Path,
    release_root: Path,
    zip_hash: str,
    sbom_path: Path,
    sbom_hash: str,
    exe_hash: str,
    expected_language_dlls: tuple[str, ...],
    package_file_hashes: dict[str, str],
) -> dict[str, object]:
    """Builds the provenance manifest written next to one release asset."""

    return {
        "product": "eMule broadband edition",
        "compactName": "eMuleBB",
        "version": package_options.release_version,
        "tag": f"emulebb-v{package_options.release_version}",
        "configuration": workspace_options.configuration,
        "platform": workspace_options.platform,
        "asset": zip_path.name,
        "assetPath": zip_path.relative_to(release_root).as_posix(),
        "sha256": zip_hash,
        "sbomFormat": "SPDX-2.3 JSON",
        "sbomPath": sbom_path.relative_to(release_root).as_posix(),
        "sbomSha256": sbom_hash,
        "emulebbExeSha256": exe_hash,
        "languageDllCount": len(expected_language_dlls),
        "languageDlls": list(expected_language_dlls),
        "packageFileSha256": package_file_hashes,
        "appVariant": app_variant.name,
        "appBranch": repo_branch(app_root),
        "appCommit": repo_head(app_root),
        "buildBranch": repo_branch(layout.build_repo_root),
        "buildCommit": repo_head(layout.build_repo_root),
        "buildTestsBranch": repo_branch(layout.tests_repo_root),
        "buildTestsCommit": repo_head(layout.tests_repo_root),
        "toolingBranch": repo_branch(layout.tooling_repo_root),
        "toolingCommit": repo_head(layout.tooling_repo_root),
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "includedPaths": [
            f"eMule/{APP_EXE_NAME}",
            "eMule/lang",
            "eMule/webserver",
            "eMule/README.md",
            "eMule/RELEASE-NOTES.md",
            "eMule/LICENSE-NOTICE.txt",
            "eMule/GPL-2.0-or-later.txt",
            "eMule/THIRD-PARTY-NOTICES.txt",
            "eMule/SBOM.spdx.json",
            "eMule/docs/REST-API-CONTRACT.md",
            "eMule/docs/REST-API-OPENAPI.yaml",
            "eMule/docs/REST-API-PARITY-INVENTORY.md",
        ],
    }


def _build_amutorrent_manifest(
    *,
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    package_options: AmutorrentPackageOptions,
    amutorrent_root: Path,
    zip_path: Path,
    release_root: Path,
    zip_hash: str,
    sbom_path: Path,
    sbom_hash: str,
    package_file_hashes: dict[str, str],
) -> dict[str, object]:
    """Builds the provenance manifest for one optional aMuTorrent asset."""

    node_archive_name, node_archive_sha256 = AMUTORRENT_NODE_ARCHIVES[workspace_options.platform]
    return {
        "product": "eMule broadband edition",
        "compactName": "eMuleBB",
        "package": "aMuTorrent optional controller",
        "version": package_options.release_version,
        "tag": f"emulebb-v{package_options.release_version}",
        "configuration": workspace_options.configuration,
        "platform": workspace_options.platform,
        "asset": zip_path.name,
        "assetPath": zip_path.relative_to(release_root).as_posix(),
        "sha256": zip_hash,
        "sbomFormat": "SPDX-2.3 JSON",
        "sbomPath": sbom_path.relative_to(release_root).as_posix(),
        "sbomSha256": sbom_hash,
        "packageFileSha256": package_file_hashes,
        "runtimePolicy": {
            "minimumPathNodeMajor": 24,
            "pinnedFallbackNodeVersion": AMUTORRENT_NODE_VERSION,
            "pinnedFallbackNodeArchive": node_archive_name,
            "pinnedFallbackNodeArchiveSha256": node_archive_sha256,
            "pathPm2Allowed": True,
            "packageLocalPm2Allowed": True,
            "packageLocalDataRoot": "aMuTorrent/data",
            "packageLocalLogRoot": "aMuTorrent/logs",
            "packageLocalRuntimeRoot": "aMuTorrent/runtime",
            "localAppDataUsed": False,
            "spacesInInstallPathAllowed": False,
        },
        "amutorrentBranch": repo_branch(amutorrent_root),
        "amutorrentCommit": repo_head(amutorrent_root),
        "buildBranch": repo_branch(layout.build_repo_root),
        "buildCommit": repo_head(layout.build_repo_root),
        "buildTestsBranch": repo_branch(layout.tests_repo_root),
        "buildTestsCommit": repo_head(layout.tests_repo_root),
        "toolingBranch": repo_branch(layout.tooling_repo_root),
        "toolingCommit": repo_head(layout.tooling_repo_root),
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "includedPaths": [
            "aMuTorrent/server",
            "aMuTorrent/server/node_modules",
            "aMuTorrent/static",
            "aMuTorrent/installer/windows/amutorrent.ps1",
            "aMuTorrent/README.md",
            "aMuTorrent/LICENSE-aMuTorrent.txt",
            "aMuTorrent/SBOM.spdx.json",
        ],
    }


def _write_release_sbom(
    *,
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    package_options: ReleasePackageOptions,
    app_variant: AppVariant,
    app_root: Path,
    package_root: Path,
    release_root: Path,
    asset_name: str,
) -> None:
    """Writes a package-local SPDX SBOM for the main release asset."""

    sbom_path = package_root / "SBOM.spdx.json"
    _assert_path_under_root(sbom_path, package_root, "release package SBOM")
    components = [
        _repo_spdx_package("eMuleBB app source", app_root, declared_license="GPL-2.0-or-later"),
        _repo_spdx_package("eMule build orchestration", layout.build_repo_root),
        _repo_spdx_package("eMule build tests", layout.tests_repo_root),
        _repo_spdx_package("eMule tooling docs", layout.tooling_repo_root),
    ]
    components.extend(_third_party_spdx_packages())
    document = _build_spdx_sbom(
        name=f"eMuleBB {package_options.release_version} {workspace_options.platform} release package",
        namespace=f"https://github.com/emulebb/emulebb/releases/download/emulebb-v{package_options.release_version}/{asset_name}.sbom",
        package_name=f"emulebb-{package_options.release_version}-{workspace_options.platform}",
        package_version=package_options.release_version,
        package_license="GPL-2.0-or-later",
        package_comment=f"Main app release package built from app variant {app_variant.name}.",
        package_root=package_root,
        release_root=release_root,
        components=components,
    )
    sbom_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def _write_amutorrent_sbom(
    *,
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    package_options: AmutorrentPackageOptions,
    amutorrent_root: Path,
    package_root: Path,
    release_root: Path,
    asset_name: str,
) -> None:
    """Writes a package-local SPDX SBOM for the optional aMuTorrent asset."""

    node_archive_name, node_archive_sha256 = AMUTORRENT_NODE_ARCHIVES[workspace_options.platform]
    sbom_path = package_root / "SBOM.spdx.json"
    _assert_path_under_root(sbom_path, package_root, "aMuTorrent package SBOM")
    components = [
        _repo_spdx_package("aMuTorrent source", amutorrent_root),
        _repo_spdx_package("eMule build orchestration", layout.build_repo_root),
        _repo_spdx_package("eMule build tests", layout.tests_repo_root),
        _repo_spdx_package("eMule tooling docs", layout.tooling_repo_root),
        _component_spdx_package(
            name=f"Node.js runtime fallback {AMUTORRENT_NODE_VERSION}",
            declared_license="MIT",
            version=AMUTORRENT_NODE_VERSION,
            download_location=f"https://nodejs.org/dist/{AMUTORRENT_NODE_VERSION}/{node_archive_name}",
            checksums=[{"algorithm": "SHA256", "checksumValue": node_archive_sha256}],
        ),
    ]
    document = _build_spdx_sbom(
        name=f"eMuleBB aMuTorrent {package_options.release_version} {workspace_options.platform} package",
        namespace=f"https://github.com/emulebb/emulebb/releases/download/emulebb-v{package_options.release_version}/{asset_name}.sbom",
        package_name=f"emulebb-{package_options.release_version}-amutorrent-{workspace_options.platform}",
        package_version=package_options.release_version,
        package_license="NOASSERTION",
        package_comment="Optional aMuTorrent controller package.",
        package_root=package_root,
        release_root=release_root,
        components=components,
    )
    sbom_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def _build_spdx_sbom(
    *,
    name: str,
    namespace: str,
    package_name: str,
    package_version: str,
    package_license: str,
    package_comment: str,
    package_root: Path,
    release_root: Path,
    components: list[dict[str, object]],
) -> dict[str, object]:
    """Builds a compact SPDX 2.3 JSON document for one staged package."""

    root_package = _component_spdx_package(
        name=package_name,
        declared_license=package_license,
        version=package_version,
        comment=package_comment,
    )
    root_package["SPDXID"] = "SPDXRef-Package"
    root_package["filesAnalyzed"] = True

    files = []
    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": root_package["SPDXID"],
        }
    ]
    file_sha1s = []
    for relative_name, digest in _staged_package_file_hashes(package_root).items():
        file_id = _spdx_ref("File", relative_name)
        sha1_digest = _sha1(package_root.parent / relative_name)
        file_sha1s.append(sha1_digest)
        files.append(
            {
                "SPDXID": file_id,
                "fileName": relative_name,
                "checksums": [
                    {"algorithm": "SHA1", "checksumValue": sha1_digest},
                    {"algorithm": "SHA256", "checksumValue": digest},
                ],
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": root_package["SPDXID"],
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": file_id,
            }
        )

    root_package["packageVerificationCode"] = {
        "packageVerificationCodeValue": hashlib.sha1("".join(sorted(file_sha1s)).encode("ascii")).hexdigest()
    }
    packages = [root_package, *components]
    for component in components:
        relationships.append(
            {
                "spdxElementId": root_package["SPDXID"],
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": component["SPDXID"],
            }
        )

    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": name,
        "documentNamespace": namespace,
        "creationInfo": {
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "creators": ["Tool: emule_workspace.release"],
        },
        "packages": packages,
        "files": files,
        "relationships": relationships,
        "documentDescribes": [root_package["SPDXID"]],
        "comment": f"Generated from staged package files under {release_root.name}.",
    }


def _staged_package_file_hashes(package_root: Path) -> dict[str, str]:
    """Returns SHA-256 hashes for staged package files, excluding the SBOM itself."""

    hashes: dict[str, str] = {}
    staging_root = package_root.parent
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or path.name == "SBOM.spdx.json":
            continue
        hashes[path.relative_to(staging_root).as_posix()] = _sha256(path)
    return hashes


def _repo_spdx_package(name: str, repo_path: Path, *, declared_license: str = "NOASSERTION") -> dict[str, object]:
    package = _component_spdx_package(
        name=name,
        declared_license=declared_license,
        version=_git_value(repo_path, "rev-parse", "HEAD"),
        download_location=_git_value(repo_path, "config", "--get", "remote.origin.url") or "NOASSERTION",
    )
    try:
        branch = repo_branch(repo_path)
    except Exception:
        branch = ""
    if branch:
        package["comment"] = f"Git branch: {branch}"
    return package


def _third_party_spdx_packages() -> list[dict[str, object]]:
    return [
        _component_spdx_package(name=name, declared_license=declared_license)
        for name, declared_license in RELEASE_THIRD_PARTY_COMPONENTS
    ]


def _component_spdx_package(
    *,
    name: str,
    declared_license: str,
    version: str | None = None,
    download_location: str = "NOASSERTION",
    checksums: list[dict[str, str]] | None = None,
    comment: str | None = None,
) -> dict[str, object]:
    package: dict[str, object] = {
        "name": name,
        "SPDXID": _spdx_ref("Package", name),
        "downloadLocation": download_location,
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": declared_license,
        "copyrightText": "NOASSERTION",
    }
    if version:
        package["versionInfo"] = version
    if checksums:
        package["checksums"] = checksums
    if comment:
        package["comment"] = comment
    return package


def _git_value(repo_path: Path, *args: str) -> str:
    try:
        return git_output(repo_path, *args).strip()
    except Exception:
        return ""


def _spdx_ref(prefix: str, value: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9.-]+", "-", value).strip(".-")
    return f"SPDXRef-{prefix}-{suffix or 'unknown'}"


def _assert_release_source_branch(app_variant: AppVariant) -> None:
    """Requires release packages to come from the configured source branch."""

    current_branch = repo_branch(app_variant.path)
    if current_branch != app_variant.branch:
        raise RuntimeError(
            "package release requires app variant "
            f"'{app_variant.name}' at {app_variant.path} to be on branch "
            f"'{app_variant.branch}', not '{current_branch}'."
        )


def _assert_clean_release_inputs(layout: WorkspaceLayout, app_root: Path) -> None:
    """Rejects dirty inputs whose exact commits are recorded in the manifest."""

    repos = (
        ("app source", app_root),
        ("build orchestration", layout.build_repo_root),
        ("build tests", layout.tests_repo_root),
        ("tooling docs", layout.tooling_repo_root),
    )
    dirty_inputs: list[str] = []
    for label, repo_path in repos:
        changes = [line for line in repo_status_lines(repo_path) if not line.startswith("## ")]
        if changes:
            sample = "\n    ".join(changes[:20])
            dirty_inputs.append(f"- {label}: {repo_path}\n    {sample}")
    if dirty_inputs:
        raise RuntimeError(
            "package release requires clean provenance inputs before writing assets:\n"
            + "\n".join(dirty_inputs)
        )


def _assert_clean_amutorrent_package_inputs(layout: WorkspaceLayout, amutorrent_root: Path) -> None:
    """Rejects dirty inputs whose exact commits are recorded in the aMuTorrent manifest."""

    repos = (
        ("aMuTorrent source", amutorrent_root),
        ("build orchestration", layout.build_repo_root),
        ("build tests", layout.tests_repo_root),
        ("tooling docs", layout.tooling_repo_root),
    )
    dirty_inputs: list[str] = []
    for label, repo_path in repos:
        changes = [line for line in repo_status_lines(repo_path) if not line.startswith("## ")]
        if changes:
            sample = "\n    ".join(changes[:20])
            dirty_inputs.append(f"- {label}: {repo_path}\n    {sample}")
    if dirty_inputs:
        raise RuntimeError(
            "package amutorrent requires clean provenance inputs before writing assets:\n"
            + "\n".join(dirty_inputs)
        )


def ensure_canonical_app_anchor(layout: WorkspaceLayout) -> None:
    """Ensures the canonical app repo is clean and detached at origin/main."""

    canonical_repo_path = layout.seed_repo_path
    if not canonical_repo_path.is_dir():
        raise RuntimeError(f"Canonical app repo is missing: {canonical_repo_path}")
    status_lines = repo_status_lines(canonical_repo_path)
    if len(status_lines) > 1:
        raise RuntimeError(f"Canonical app repo has local changes and cannot be re-anchored automatically: {canonical_repo_path}")
    expected_revision = f"refs/remotes/origin/{layout.seed_repo_branch}"
    expected_head = git_output(canonical_repo_path, "rev-parse", expected_revision).strip()
    current_branch = repo_branch(canonical_repo_path)
    current_head = git_output(canonical_repo_path, "rev-parse", "HEAD").strip()
    if current_branch == "HEAD" and current_head == expected_head:
        return
    print(f"Reanchoring canonical app repo to detached origin/{layout.seed_repo_branch} at {expected_head}")
    git_output(canonical_repo_path, "checkout", "--detach", expected_revision)


def _release_asset_arch(platform: str) -> str:
    """Returns the release asset architecture token for one build platform."""

    return "arm64" if platform == "ARM64" else "x64"


def _release_root(layout: WorkspaceLayout, package_options: ReleasePackageOptions) -> Path:
    """Returns the release artifact root for one package version."""

    return layout.workspace_root / "state" / "release" / f"emulebb-v{package_options.release_version}"


def _package_build_root(layout: WorkspaceLayout, package_options: ReleasePackageOptions, platform: str) -> Path:
    """Returns the package-only app build output root for one release asset."""

    return layout.workspace_root / "state" / "package-build" / f"emulebb-v{package_options.release_version}" / _release_asset_arch(platform)


def _build_package_app(
    session: BuildSession,
    app_root: Path,
    *,
    package_app_output_root: Path,
    package_app_intermediate_root: Path,
    clean: bool,
) -> None:
    target = "Rebuild" if clean else "Build"
    ensure_app_dependency_artifacts(session.layout, session.options, clean=clean)
    extra_properties = [*app_property_overrides(session.layout, session.options.platform)]
    extra_properties.append("/p:EnableStartupProfiling=false")
    extra_properties.append(f"/p:OutDir={with_trailing_separator(package_app_output_root)}")
    extra_properties.append(f"/p:IntDir={with_trailing_separator(package_app_intermediate_root)}")
    override = env_override(session.layout.toolset_override_variable)
    if override:
        extra_properties.append(f"/p:PlatformToolset={override}")
    invoke_msbuild_project(
        session,
        project_path=app_root / "srchybrid" / "emule.vcxproj",
        extra_properties=extra_properties,
        target=target,
        step_name="APP main package binary",
    )
    verify_app_control_flow_guard(
        session,
        binary_path=package_app_output_root / APP_EXE_NAME,
        step_name="APP main package binary CFG",
    )


def _build_language_resources(session: BuildSession, app_root: Path, clean: bool) -> None:
    language_solution = app_root / "srchybrid" / "lang" / "lang.sln"
    if not language_solution.is_file():
        raise RuntimeError(f"Cannot build missing language solution: {language_solution}")
    target = "Rebuild" if clean else "Build"
    invoke_msbuild_project(
        session,
        project_path=language_solution,
        configuration="Dynamic",
        platform=session.options.platform,
        extra_properties=(_default_platform_toolset_property(session.layout),),
        max_cpu_count=1,
        target=target,
        step_name="APP main language resources",
    )


def _default_platform_toolset_property(layout: WorkspaceLayout) -> str:
    override = env_override(layout.toolset_override_variable)
    return f"/p:PlatformToolset={override}" if override else "/p:PlatformToolset=v143"


def _assert_packaging_node_supported(platform: str) -> None:
    """Requires PATH Node to support the requested native module package platform."""

    try:
        completed = subprocess.run(
            ["node", "-p", "`${process.versions.node}|${process.arch}`"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("package amutorrent requires Node 24 or newer on PATH.") from exc
    version, node_arch = completed.stdout.strip().split("|", 1)
    try:
        major = int(version.split(".", 1)[0])
    except ValueError as exc:
        raise RuntimeError(f"Cannot parse Node version from PATH: {version!r}") from exc
    if major < 24:
        raise RuntimeError(f"package amutorrent requires Node 24 or newer on PATH, found {version}.")
    expected_arch = "arm64" if platform == "ARM64" else "x64"
    if node_arch != expected_arch:
        raise RuntimeError(
            "package amutorrent target architecture must match PATH Node because "
            f"server dependencies include native modules: target {platform} requires "
            f"Node process.arch '{expected_arch}', found '{node_arch}'."
        )


def _build_amutorrent_webapp(amutorrent_root: Path, clean: bool) -> None:
    """Installs runtime dependencies and refreshes bundled frontend assets."""

    if clean:
        for generated_path in (
            amutorrent_root / "node_modules",
            amutorrent_root / "server" / "node_modules",
        ):
            if generated_path.exists():
                shutil.rmtree(generated_path)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("package amutorrent requires npm on PATH.")
    subprocess.run([npm, "ci"], cwd=amutorrent_root, check=True)
    subprocess.run([npm, "ci", "--prefix", "server", "--omit=dev"], cwd=amutorrent_root, check=True)
    subprocess.run([npm, "run", "build"], cwd=amutorrent_root, check=True)


def _copy_amutorrent_runtime(amutorrent_root: Path, package_root: Path) -> None:
    """Copies the aMuTorrent runtime payload and owned installer asset."""

    server_root = amutorrent_root / "server"
    static_root = amutorrent_root / "static"
    installer_script = amutorrent_root / "installer" / "windows" / "amutorrent.ps1"
    if not (server_root / "node_modules").is_dir():
        raise RuntimeError(f"Cannot package missing aMuTorrent production node_modules: {server_root / 'node_modules'}")
    if not (static_root / "dist" / "app.bundle.js").is_file():
        raise RuntimeError(f"Cannot package missing built aMuTorrent frontend bundle: {static_root / 'dist' / 'app.bundle.js'}")
    if not installer_script.is_file():
        raise RuntimeError(f"Cannot package missing aMuTorrent Windows setup script: {installer_script}")

    _copy_tree_filtered(server_root, package_root / "server", _exclude_amutorrent_server_runtime)
    _copy_tree_filtered(static_root, package_root / "static", _exclude_amutorrent_static_runtime)
    _copy_package_file(installer_script, package_root, Path("installer/windows/amutorrent.ps1"))


def _exclude_amutorrent_server_runtime(relative_path: Path, source_path: Path) -> bool:
    parts = relative_path.parts
    if parts and parts[0] in {"data", "logs"}:
        return True
    if any(part in {".cache", "__pycache__"} for part in parts):
        return True
    if source_path.is_file() and source_path.suffix.lower() == ".map":
        return True
    if "node_modules" not in parts and source_path.is_file() and source_path.suffix.lower() in {".log", ".db", ".sqlite", ".sqlite3"}:
        return True
    return False


def _exclude_amutorrent_static_runtime(relative_path: Path, source_path: Path) -> bool:
    parts = relative_path.parts
    if parts and parts[0] in {"components", "contexts", "hooks", "utils"}:
        return True
    if relative_path.name == "app.js":
        return True
    if source_path.is_file() and source_path.suffix.lower() in {".map", ".sh"}:
        return True
    return False


def _expected_language_dlls(tooling_repo_root: Path) -> tuple[str, ...]:
    """Returns the release language DLL names from the stock language manifest."""

    manifest_path = tooling_repo_root / "helpers" / "rc-release-languages.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"Cannot package without release language manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    languages = manifest.get("languages")
    if not isinstance(languages, list) or not languages:
        raise RuntimeError(f"Release language manifest has no languages: {manifest_path}")
    dlls: list[str] = []
    for entry in languages:
        rc_name = entry.get("rc") if isinstance(entry, dict) else None
        if not isinstance(rc_name, str) or not rc_name.endswith(".rc"):
            raise RuntimeError(f"Release language manifest entry is missing an .rc file name: {entry!r}")
        dlls.append(Path(rc_name).with_suffix(".dll").name)
    return tuple(sorted(dlls))


def _package_language_path(app_root: Path, platform: str, expected_language_dlls: tuple[str, ...]) -> Path:
    lang_path = app_root / "srchybrid" / platform / "lang"
    if not lang_path.is_dir():
        raise RuntimeError(f"Cannot package missing built language DLLs: {lang_path}")
    missing = [dll for dll in expected_language_dlls if not (lang_path / dll).is_file()]
    if missing:
        raise RuntimeError(f"Cannot package missing built language DLLs in {lang_path}:\n" + "\n".join(missing))
    extra = sorted(path.name for path in lang_path.glob("*.dll") if path.name not in expected_language_dlls)
    if extra:
        raise RuntimeError(f"Cannot package unexpected language DLLs in {lang_path}:\n" + "\n".join(extra))
    for dll in expected_language_dlls:
        _assert_pe_machine(lang_path / dll, platform)
    return lang_path


def _package_webserver_path(app_root: Path, build_output_root: Path) -> Path:
    webserver_path = build_output_root / "webserver"
    if webserver_path.is_dir() and any(path.is_file() for path in webserver_path.rglob("*")):
        return webserver_path
    return app_root / "srchybrid" / "webinterface"


def _copy_package_file(source_path: Path, package_root: Path, relative_destination_path: Path) -> None:
    if not source_path.is_file():
        raise RuntimeError(f"Cannot package missing file: {source_path}")
    destination_path = package_root / relative_destination_path
    _assert_path_under_root(destination_path, package_root, "release package file")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)


def _copy_directory_contents(source_path: Path, destination_path: Path) -> None:
    destination_path.mkdir(parents=True, exist_ok=True)
    for child in source_path.iterdir():
        target = destination_path / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)


def _copy_tree_filtered(source_path: Path, destination_path: Path, exclude) -> None:
    """Copies a tree while allowing package-specific runtime exclusions."""

    destination_path.mkdir(parents=True, exist_ok=True)
    for source_child in sorted(source_path.rglob("*")):
        relative_path = source_child.relative_to(source_path)
        if exclude(relative_path, source_child):
            continue
        target = destination_path / relative_path
        _assert_path_under_root(target, destination_path, "filtered package file")
        if source_child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source_child.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_child, target)


def _write_package_readme(package_root: Path, release_version: str, platform: str) -> None:
    """Writes the package-facing README."""

    readme_path = package_root / "README.md"
    _assert_path_under_root(readme_path, package_root, "release package README")
    asset_arch = "arm64" if platform == "ARM64" else "x64"
    readme_path.write_text(
        "\n".join(
            (
                "# eMule broadband edition",
                "",
                f"Version: {release_version}",
                f"Architecture: {asset_arch}",
                "",
                f"Run `{APP_EXE_NAME}` from this directory. The package is portable and keeps the",
                "stock eMule language DLLs under `lang/` and the legacy web template under",
                "`webserver/`.",
                "",
                "REST API documentation is included under `docs/`. Language DLLs are built",
                "from the stock eMule language resource set and are architecture-specific.",
                "`SBOM.spdx.json` records the package files and source/dependency",
                "components in SPDX 2.3 JSON format.",
                "",
                "MediaInfo integration remains optional. To enable audio/video metadata,",
                f"install a compatible external `MediaInfo.dll` next to `{APP_EXE_NAME}`; it is not",
                "bundled in this ZIP.",
                "",
                "This ZIP is not code-signed and does not include debug symbols.",
            )
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_package_release_notes(package_root: Path, release_version: str) -> None:
    """Writes concise release notes for the binary package."""

    notes_path = package_root / "RELEASE-NOTES.md"
    _assert_path_under_root(notes_path, package_root, "release package notes")
    notes_path.write_text(
        "\n".join(
            (
                "# Release Notes",
                "",
                f"eMule broadband edition {release_version} is the first public beta line",
                "for eMuleBB.",
                "",
                "- Preserves stock eD2K/Kad protocol compatibility.",
                "- Ships x64 and ARM64 portable ZIP assets.",
                "- Bundles the full stock language DLL set for the selected architecture.",
                "- Includes the in-process REST API documentation used by controller integrations.",
                "- Includes an SPDX 2.3 JSON SBOM in the package root.",
                "- Does not bundle optional external MediaInfo runtime DLLs.",
            )
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_package_license_notice(package_root: Path) -> None:
    notice_path = package_root / "LICENSE-NOTICE.txt"
    _assert_path_under_root(notice_path, package_root, "release package license notice")
    notice_path.write_text(
        "\n".join(
            (
                "eMule broadband edition contains eMule-derived application code licensed under GPL-2.0-or-later.",
                "The source tree retains the per-file GPL notices from the original eMule project and eMuleBB changes.",
                "Third-party libraries are linked from the canonical workspace dependency pins and retain their upstream licenses.",
                "See GPL-2.0-or-later.txt and THIRD-PARTY-NOTICES.txt in this package.",
                "For complete corresponding source, use the eMuleBB source repositories "
                "at the app commit recorded in the package manifest.",
            )
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_package_third_party_notices(package_root: Path) -> None:
    """Writes third-party dependency notices for the bundled binary."""

    notice_path = package_root / "THIRD-PARTY-NOTICES.txt"
    _assert_path_under_root(notice_path, package_root, "release package third-party notices")
    notice_path.write_text(
        "\n".join(
            (
                "Third-party notices for eMule broadband edition",
                "",
                "The binary is built from the canonical workspace dependency pins recorded",
                "in the release manifest. The package does not redistribute separate",
                "third-party DLLs except stock eMule language resource DLLs.",
                "",
                "Linked dependencies and license families:",
                "- Crypto++: Boost Software License 1.0",
                "- id3lib: GNU Library General Public License 2.0",
                "- miniupnpc: BSD-style license from the MiniUPnP project",
                "- libpcpnatpmp: PCP/NAT-PMP client library license from the pinned fork",
                "- ResizableLib: Artistic License 2.0",
                "- zlib: zlib license",
                "- Mbed TLS / TF-PSA-Crypto: Apache-2.0 OR GPL-2.0-or-later",
                "- nlohmann/json: MIT license",
                "",
                "Complete corresponding source and full upstream license files are available",
                "from the eMuleBB source repositories at the commits recorded in the",
                "release manifest.",
            )
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_package_gpl_text(layout: WorkspaceLayout, package_root: Path) -> None:
    """Writes the GPL-2.0-or-later license text from a pinned local dependency."""

    license_path = layout.resolve_workspace_path("repos/third_party/emulebb-mbedtls/LICENSE")
    if not license_path.is_file():
        raise RuntimeError(f"Cannot package missing GPL license source: {license_path}")
    text = license_path.read_text(encoding="utf-8", errors="replace")
    start = text.find("                    GNU GENERAL PUBLIC LICENSE")
    if start < 0:
        raise RuntimeError(f"Cannot find GPL text in license source: {license_path}")
    gpl_text = text[start:].strip() + "\n"
    destination_path = package_root / "GPL-2.0-or-later.txt"
    _assert_path_under_root(destination_path, package_root, "release package GPL text")
    destination_path.write_text(gpl_text, encoding="utf-8", newline="\n")


def _write_amutorrent_readme(package_root: Path, release_version: str, platform: str) -> None:
    """Writes the optional aMuTorrent package README."""

    asset_arch = "arm64" if platform == "ARM64" else "x64"
    readme_path = package_root / "README.md"
    _assert_path_under_root(readme_path, package_root, "aMuTorrent package README")
    readme_path.write_text(
        "\n".join(
            (
                "# aMuTorrent optional controller",
                "",
                f"eMule broadband edition package version: {release_version}",
                f"Architecture: {asset_arch}",
                "",
                "Extract this folder to a path without spaces, then run the Windows",
                "PowerShell setup runner from the package root:",
                "",
                "```powershell",
                "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\installer\\windows\\amutorrent.ps1 Doctor",
                "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\installer\\windows\\amutorrent.ps1 Start",
                "```",
                "",
                "The runner uses Node 24 or newer from PATH when available. Otherwise it",
                f"downloads the pinned {AMUTORRENT_NODE_VERSION} Windows runtime into `runtime\\node`.",
                "`SBOM.spdx.json` records the packaged controller files and runtime",
                "components in SPDX 2.3 JSON format.",
                "Persistent mode is optional and uses PM2 only when PM2 is already on PATH",
                "or after you explicitly run the `Install-Pm2` command.",
                "",
                "Runtime state is package-local:",
                "- `data\\` stores aMuTorrent configuration and databases through `AMUTORRENT_DATA_DIR`.",
                "- `logs\\` is reserved for package-local logs.",
                "- `runtime\\` stores downloaded Node, package-local PM2, and PM2 state.",
                "",
                "This package is a portable multi-client aMuTorrent controller. It keeps",
                "runtime defaults under the package root.",
            )
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_zip(staging_root: Path, package_root: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging_root).as_posix())


def _assert_release_package_contents(zip_path: Path, expected_language_dlls: tuple[str, ...], platform: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        entry_names = [name.replace("\\", "/") for name in archive.namelist()]
        entry_set = set(entry_names)
        required_entries = (
            f"eMule/{APP_EXE_NAME}",
            "eMule/README.md",
            "eMule/RELEASE-NOTES.md",
            "eMule/LICENSE-NOTICE.txt",
            "eMule/GPL-2.0-or-later.txt",
            "eMule/THIRD-PARTY-NOTICES.txt",
            "eMule/SBOM.spdx.json",
            "eMule/docs/REST-API-CONTRACT.md",
            "eMule/docs/REST-API-OPENAPI.yaml",
            "eMule/docs/REST-API-PARITY-INVENTORY.md",
        )
        for required_entry in required_entries:
            if required_entry not in entry_set:
                raise RuntimeError(f"Release package is missing required entry '{required_entry}': {zip_path}")
        language_dlls = sorted(name for name in entry_names if re.fullmatch(r"eMule/lang/[^/]+\.dll", name))
        expected_language_entries = tuple(f"eMule/lang/{dll}" for dll in expected_language_dlls)
        missing_language_entries = [name for name in expected_language_entries if name not in entry_set]
        extra_language_entries = [name for name in language_dlls if name not in expected_language_entries]
        if missing_language_entries:
            raise RuntimeError("Release package is missing language DLLs:\n" + "\n".join(missing_language_entries))
        if extra_language_entries:
            raise RuntimeError("Release package contains unexpected language DLLs:\n" + "\n".join(extra_language_entries))
        for entry_name in (f"eMule/{APP_EXE_NAME}", *language_dlls):
            _assert_pe_machine_bytes(archive.read(entry_name), platform, entry_name)
        webserver_files = [name for name in entry_names if re.fullmatch(r"eMule/webserver/.+[^/]", name)]
        if not webserver_files:
            raise RuntimeError(f"Release package has no webserver payload under eMule/webserver: {zip_path}")
        forbidden_entries = [
            name
            for name in entry_names
            if re.search(r"(^|/)(Win32|x86)(/|$)", name)
            or re.search(r"\.(pdb|obj|ilk|idb|iobj|ipdb|tlog|lastbuildstate|vcxproj|filters|sln|aps|res|rc|rc2|cpp|c|h|hpp)$", name)
        ]
        if forbidden_entries:
            sample = "\n".join(forbidden_entries[:20])
            raise RuntimeError(f"Release package contains build/source artifacts:\n{sample}")
    print(f"Package content check: {zip_path} ({len(entry_names)} entries, {len(language_dlls)} language DLLs)")


def _assert_amutorrent_package_contents(zip_path: Path) -> None:
    """Checks the optional aMuTorrent package for required runtime files and forbidden state."""

    with zipfile.ZipFile(zip_path, "r") as archive:
        entry_names = [name.replace("\\", "/") for name in archive.namelist()]
        entry_set = set(entry_names)
        required_entries = (
            "aMuTorrent/README.md",
            "aMuTorrent/LICENSE-aMuTorrent.txt",
            "aMuTorrent/SBOM.spdx.json",
            "aMuTorrent/installer/windows/amutorrent.ps1",
            "aMuTorrent/server/server.js",
            "aMuTorrent/server/package.json",
            "aMuTorrent/server/package-lock.json",
            "aMuTorrent/server/node_modules/express/package.json",
            "aMuTorrent/server/node_modules/better-sqlite3/package.json",
            "aMuTorrent/static/index.html",
            "aMuTorrent/static/output.css",
            "aMuTorrent/static/dist/app.bundle.js",
        )
        for required_entry in required_entries:
            if required_entry not in entry_set:
                raise RuntimeError(f"aMuTorrent package is missing required entry '{required_entry}': {zip_path}")
        forbidden_entries = [
            name
            for name in entry_names
            if name.startswith("aMuTorrent/server/data/")
            or name.startswith("aMuTorrent/server/logs/")
            or name.startswith("aMuTorrent/data/")
            or name.startswith("aMuTorrent/logs/")
            or name.startswith("aMuTorrent/runtime/")
            or name.startswith("aMuTorrent/node_modules/")
            or name.startswith("aMuTorrent/static/components/")
            or name.startswith("aMuTorrent/static/contexts/")
            or name.startswith("aMuTorrent/static/hooks/")
            or name.startswith("aMuTorrent/static/utils/")
            or name == "aMuTorrent/static/app.js"
            or "/.git/" in name
            or "/tests/" in name
            or name.endswith(".map")
            or name.endswith(".log")
            or name.endswith(".db")
            or name.endswith(".sqlite")
            or name.endswith(".sqlite3")
            or name == "aMuTorrent/server/node_modules/nodemon/package.json"
            or " " in name
        ]
        if forbidden_entries:
            sample = "\n".join(forbidden_entries[:20])
            raise RuntimeError(f"aMuTorrent package contains forbidden generated or source artifacts:\n{sample}")

        script = archive.read("aMuTorrent/installer/windows/amutorrent.ps1").decode("utf-8")
        if "#Requires -Version 5.1" not in script:
            raise RuntimeError("aMuTorrent package script must declare Windows PowerShell 5.1 compatibility.")
        if "LOCALAPPDATA" in script.upper() or "APPDATA" in script.upper():
            raise RuntimeError("aMuTorrent package script must not use Windows app data defaults.")
        if "$env:AMUTORRENT_DATA_DIR = $DataRoot" not in script:
            raise RuntimeError("aMuTorrent package script does not set AMUTORRENT_DATA_DIR to package-local data.")
        if "PackageRoot -match \"\\s\"" not in script:
            raise RuntimeError("aMuTorrent package script does not reject install paths containing spaces.")
    print(f"aMuTorrent package content check: {zip_path} ({len(entry_names)} entries)")


def _assert_pe_machine(path: Path, platform: str) -> None:
    """Checks that one PE file matches the selected package platform."""

    if _pe_machine(path.read_bytes(), str(path)) != PE_MACHINES[platform]:
        raise RuntimeError(f"PE architecture mismatch for {path}: expected {platform}.")


def _assert_startup_profiling_not_compiled(path: Path) -> None:
    """Rejects release package binaries that still include startup profiling support."""

    payload = path.read_bytes()
    for marker in STARTUP_PROFILING_BINARY_MARKERS:
        if marker in payload:
            raise RuntimeError(
                "Release package binary still contains startup profiling support; "
                f"rebuild {path} with /p:EnableStartupProfiling=false."
            )


def _assert_pe_machine_bytes(payload: bytes, platform: str, label: str) -> None:
    """Checks that one PE payload from a ZIP matches the selected package platform."""

    machine = _pe_machine(payload, label)
    expected = PE_MACHINES[platform]
    if machine != expected:
        raise RuntimeError(f"PE architecture mismatch for {label}: got 0x{machine:04X}, expected {platform}.")


def _pe_machine(payload: bytes, label: str) -> int:
    """Returns the COFF machine type from a PE payload."""

    if len(payload) < 0x40 or payload[:2] != b"MZ":
        raise RuntimeError(f"Not a PE file: {label}")
    pe_offset = struct.unpack_from("<I", payload, 0x3C)[0]
    if pe_offset < 0 or pe_offset + 6 > len(payload):
        raise RuntimeError(f"Invalid PE header offset in {label}")
    if payload[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise RuntimeError(f"Invalid PE signature in {label}")
    return struct.unpack_from("<H", payload, pe_offset + 4)[0]


def _app_mod_release_version(app_root: Path) -> str:
    version_header_path = app_root / "srchybrid" / "Version.h"
    if not version_header_path.is_file():
        raise RuntimeError(f"Cannot read missing app version header: {version_header_path}")
    parts: dict[str, int] = {}
    pattern = re.compile(r"^\s*#define\s+MOD_RELEASE_VERSION_(MAJOR|MINOR|PATCH)\s+(\d+)\s*$")
    for line in version_header_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if match:
            parts[match.group(1)] = int(match.group(2))
    for required_part in ("MAJOR", "MINOR", "PATCH"):
        if required_part not in parts:
            raise RuntimeError(f"Cannot find MOD_RELEASE_VERSION_{required_part} in {version_header_path}")
    return f"{parts['MAJOR']}.{parts['MINOR']}.{parts['PATCH']}"


def _assert_package_version_matches_app(app_root: Path, release_version: str) -> None:
    app_release_version = _app_mod_release_version(app_root)
    if _base_release_version(release_version) != app_release_version:
        raise RuntimeError(
            f"package release version mismatch: --release-version is '{release_version}' "
            f"but app MOD_RELEASE_VERSION is '{app_release_version}'."
        )


def _is_release_version(release_version: str) -> bool:
    return RELEASE_VERSION_PATTERN.fullmatch(release_version) is not None


def _base_release_version(release_version: str) -> str:
    return release_version.split("-", 1)[0]


def _assert_path_under_root(path: Path, root: Path, label: str) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"{label} resolved outside expected root: {resolved_path}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_entry_hashes(zip_path: Path) -> dict[str, str]:
    """Returns SHA-256 hashes for every file entry in a release ZIP."""

    hashes: dict[str, str] = {}
    with zipfile.ZipFile(zip_path, "r") as archive:
        for name in sorted(archive.namelist()):
            if name.endswith("/"):
                continue
            hashes[name.replace("\\", "/")] = hashlib.sha256(archive.read(name)).hexdigest()
    return hashes
