"""Local package-style install orchestration for operator live-wire profiles."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .build import APP_EXE_NAME
from .config import AmutorrentPackageOptions, LocalPackageInstallOptions, ReleasePackageOptions, WorkspaceOptions
from .layout import WorkspaceLayout
from .release import EMULEBB_PACKAGE_ROOT_NAME, create_amutorrent_package, create_release_package

LIVE_WIRE_SCHEMA = "emulebb-build-tests.live-wire-inputs.v1"
LEGACY_LIVE_WIRE_SCHEMAS = ("emule-build-tests.live-wire-inputs.v1",)
LOCAL_INSTALL_KEY = "local_package_install"
INSTALL_MANIFEST_SCHEMA = "emulebb.local-package-install.v1"
PRESERVED_AMUTORRENT_DIRS = {"data", "logs", "runtime", ".pm2"}
DEFAULT_AMUTORRENT_PORT = 4000
DEFAULT_AMUTORRENT_BIND_ADDRESS = "0.0.0.0"
DEFAULT_REST_PORT = 4711
DEFAULT_PROCDUMP_PATH = Path(r"C:\bin\sysin\procdump.exe")


@dataclass(frozen=True)
class LocalInstallConfig:
    """Resolved local install settings loaded from ignored live-wire JSON."""

    live_wire_inputs_file: Path
    target_path: Path
    profile_dir: Path
    amutorrent_port: int
    amutorrent_bind_address: str
    emulebb_id: str
    emulebb_name: str
    procdump_path: Path
    enable_rest: bool
    enable_crash_dumps: bool
    rest_host_override: str | None
    rest_port_override: int | None
    rest_use_ssl_override: bool | None


@dataclass(frozen=True)
class ProfileRestConfig:
    """REST configuration read from the selected eMuleBB profile."""

    api_key: str
    host: str
    port: int
    use_ssl: bool


@dataclass(frozen=True)
class InstallArtifacts:
    """Release artifact paths consumed by the local installer."""

    release_root: Path
    emule_zip: Path
    amutorrent_zip: Path
    emule_manifest: Path
    emule_sbom: Path
    amutorrent_manifest: Path
    amutorrent_sbom: Path
    package_exe: Path
    package_pdb: Path
    arch: str


@dataclass(frozen=True)
class DecodedText:
    """Text decoded from disk with the encoding needed for round-trip writes."""

    text: str
    encoding: str


def install_local_package(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    options: LocalPackageInstallOptions,
) -> None:
    """Builds and deploys a local package install from ignored live-wire inputs."""

    if workspace_options.configuration != "Release":
        raise RuntimeError("install local package requires --config Release.")
    config = load_local_install_config(layout, options.live_wire_inputs_file)
    if not options.skip_build:
        create_release_package(
            layout,
            workspace_options,
            ReleasePackageOptions(release_version=options.release_version, clean=options.clean),
        )
        create_amutorrent_package(
            layout,
            workspace_options,
            AmutorrentPackageOptions(release_version=options.release_version, clean=options.clean),
        )

    artifacts = resolve_install_artifacts(layout, workspace_options, options.release_version)
    rest_config = prepare_profile_preferences(config)
    deploy_local_install(layout, config, rest_config, artifacts, options.release_version)


def load_local_install_config(layout: WorkspaceLayout, raw_inputs_path: str | None) -> LocalInstallConfig:
    """Loads local package install settings from the ignored live-wire JSON."""

    inputs_path = resolve_live_wire_inputs_path(layout, raw_inputs_path)
    payload = _load_json_object(inputs_path, "live-wire inputs file")
    schema = payload.get("schema")
    if schema not in (LIVE_WIRE_SCHEMA, *LEGACY_LIVE_WIRE_SCHEMAS):
        raise RuntimeError(f"Live-wire inputs schema must be {LIVE_WIRE_SCHEMA!r}.")
    raw_config = payload.get(LOCAL_INSTALL_KEY)
    if not isinstance(raw_config, dict):
        raise RuntimeError(f"Live-wire inputs field {LOCAL_INSTALL_KEY!r} must be an object.")

    target_path = _required_path(raw_config, "target_path")
    profile_dir = _required_path(raw_config, "profile_dir")
    if " " in str(target_path):
        raise RuntimeError(f"Local install target path must not contain spaces for aMuTorrent packaging: {target_path}")

    return LocalInstallConfig(
        live_wire_inputs_file=inputs_path,
        target_path=target_path,
        profile_dir=profile_dir,
        amutorrent_port=_optional_int(raw_config, "amutorrent_port", DEFAULT_AMUTORRENT_PORT),
        amutorrent_bind_address=_optional_string(raw_config, "amutorrent_bind_address", DEFAULT_AMUTORRENT_BIND_ADDRESS),
        emulebb_id=_optional_string(raw_config, "emulebb_id", "emulebb-local"),
        emulebb_name=_optional_string(raw_config, "emulebb_name", "eMuleBB local"),
        procdump_path=_optional_path(raw_config, "procdump_path", DEFAULT_PROCDUMP_PATH),
        enable_rest=_optional_bool(raw_config, "enable_rest", True),
        enable_crash_dumps=_optional_bool(raw_config, "enable_crash_dumps", True),
        rest_host_override=_optional_nullable_string(raw_config, "rest_host"),
        rest_port_override=_optional_nullable_int(raw_config, "rest_port"),
        rest_use_ssl_override=_optional_nullable_bool(raw_config, "rest_use_ssl"),
    )


def resolve_live_wire_inputs_path(layout: WorkspaceLayout, raw_inputs_path: str | None) -> Path:
    """Resolves the operator live-wire JSON path."""

    if not raw_inputs_path:
        return (layout.tests_repo_root / "live-wire-inputs.local.json").resolve()
    candidate = Path(raw_inputs_path)
    if candidate.is_absolute():
        return candidate.resolve()
    workspace_relative = (layout.emule_workspace_root / candidate).resolve()
    if workspace_relative.exists():
        return workspace_relative
    return (layout.tests_repo_root / candidate).resolve()


def resolve_install_artifacts(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    release_version: str,
) -> InstallArtifacts:
    """Returns the release artifacts and private symbols used by the installer."""

    arch = "arm64" if workspace_options.platform == "ARM64" else "x64"
    release_root = layout.workspace_root / "state" / "release" / f"emulebb-v{release_version}"
    package_build_root = layout.workspace_root / "state" / "package-build" / f"emulebb-v{release_version}" / arch / "app"
    artifacts = InstallArtifacts(
        release_root=release_root,
        emule_zip=release_root / f"emulebb-{release_version}-{arch}.zip",
        amutorrent_zip=release_root / f"emulebb-{release_version}-amutorrent-{arch}.zip",
        emule_manifest=release_root / f"emulebb-{release_version}-{arch}.manifest.json",
        emule_sbom=release_root / f"emulebb-{release_version}-{arch}.sbom.spdx.json",
        amutorrent_manifest=release_root / f"emulebb-{release_version}-amutorrent-{arch}.manifest.json",
        amutorrent_sbom=release_root / f"emulebb-{release_version}-amutorrent-{arch}.sbom.spdx.json",
        package_exe=package_build_root / APP_EXE_NAME,
        package_pdb=package_build_root / "emulebb.pdb",
        arch=arch,
    )
    missing = [
        path
        for path in (
            artifacts.emule_zip,
            artifacts.amutorrent_zip,
            artifacts.emule_manifest,
            artifacts.emule_sbom,
            artifacts.amutorrent_manifest,
            artifacts.amutorrent_sbom,
            artifacts.package_exe,
            artifacts.package_pdb,
        )
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError("Local package install is missing required artifacts:\n" + "\n".join(str(path) for path in missing))
    return artifacts


def prepare_profile_preferences(config: LocalInstallConfig) -> ProfileRestConfig:
    """Ensures required profile preferences and returns REST connection settings."""

    profile_config_dir = config.profile_dir / "config"
    preferences_path = profile_config_dir / "preferences.ini"
    if not preferences_path.is_file():
        raise RuntimeError(f"Profile preferences.ini is missing: {preferences_path}")

    decoded_preferences = read_text_preserving_encoding(preferences_path)
    values = parse_ini_values(decoded_preferences.text)
    webserver = values.get("webserver", {})
    emule = values.get("emule", {})
    api_key = webserver.get("apikey", "").strip()
    if not api_key:
        raise RuntimeError(f"Profile WebServer ApiKey is missing: {preferences_path}")

    host = config.rest_host_override or webserver.get("bindaddr", "").strip() or "127.0.0.1"
    port = config.rest_port_override or _parse_int(webserver.get("port", ""), DEFAULT_REST_PORT)
    use_ssl = config.rest_use_ssl_override if config.rest_use_ssl_override is not None else _parse_bool(webserver.get("usehttps", ""), False)

    updates: list[tuple[str, str, str]] = []
    if config.enable_rest and not _parse_bool(webserver.get("enabled", ""), False):
        updates.append(("WebServer", "Enabled", "1"))
    if config.enable_crash_dumps and emule.get("createcrashdump", "") != "2":
        updates.append(("eMule", "CreateCrashDump", "2"))

    if updates:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = preferences_path.with_name(f"{preferences_path.name}.local-install-{timestamp}.bak")
        shutil.copy2(preferences_path, backup_path)
        updated_text = update_ini_values(decoded_preferences.text, updates)
        preferences_path.write_text(updated_text, encoding=decoded_preferences.encoding, newline="")
        print(f"Updated profile preferences: {preferences_path}")
        print(f"Profile preferences backup: {backup_path}")

    return ProfileRestConfig(api_key=api_key, host=host, port=port, use_ssl=use_ssl)


def deploy_local_install(
    layout: WorkspaceLayout,
    config: LocalInstallConfig,
    rest_config: ProfileRestConfig,
    artifacts: InstallArtifacts,
    release_version: str,
) -> None:
    """Extracts release packages, symbols, manifests, and local scripts."""

    target_root = config.target_path
    target_root.mkdir(parents=True, exist_ok=True)
    staging_root = target_root / ".staging" / f"emulebb-v{release_version}-{_timestamp_for_path()}"
    _assert_under_root(staging_root, target_root, "install staging path")
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    try:
        emule_stage = staging_root / "emule"
        amutorrent_stage = staging_root / "amutorrent"
        _extract_zip_safe(artifacts.emule_zip, emule_stage)
        _extract_zip_safe(artifacts.amutorrent_zip, amutorrent_stage)
        _replace_emule_tree(emule_stage / EMULEBB_PACKAGE_ROOT_NAME, target_root / EMULEBB_PACKAGE_ROOT_NAME, target_root)
        _replace_amutorrent_tree(amutorrent_stage / "aMuTorrent", target_root / "aMuTorrent", target_root)
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)

    symbols_dir = target_root / "symbols" / f"emulebb-v{release_version}" / artifacts.arch
    manifests_dir = target_root / "manifests" / f"emulebb-v{release_version}"
    diagnostics_dir = target_root / "diagnostics"
    scripts_dir = target_root / "scripts"
    for path in (symbols_dir, manifests_dir, diagnostics_dir, scripts_dir):
        path.mkdir(parents=True, exist_ok=True)
    deployed_exe = target_root / EMULEBB_PACKAGE_ROOT_NAME / APP_EXE_NAME
    if _sha256(deployed_exe) != _sha256(artifacts.package_exe):
        raise RuntimeError(
            "Local package install extracted an emulebb.exe that does not match the package-build executable "
            f"used for symbols:\n{deployed_exe}\n{artifacts.package_exe}"
        )

    versioned_pdb = symbols_dir / "emulebb.pdb"
    adjacent_pdb = target_root / EMULEBB_PACKAGE_ROOT_NAME / "emulebb.pdb"
    shutil.copy2(artifacts.package_pdb, versioned_pdb)
    shutil.copy2(artifacts.package_pdb, adjacent_pdb)
    for manifest in (artifacts.emule_manifest, artifacts.emule_sbom, artifacts.amutorrent_manifest, artifacts.amutorrent_sbom):
        shutil.copy2(manifest, manifests_dir / manifest.name)

    write_local_scripts(layout, config, rest_config, release_version)
    write_install_manifest(layout, config, rest_config, artifacts, release_version)
    print(f"Local package install: {target_root}")
    print(f"Profile: {config.profile_dir}")
    print(f"Symbols: {symbols_dir}")
    print(f"Adjacent debug info: {adjacent_pdb}")


def write_local_scripts(
    layout: WorkspaceLayout,
    config: LocalInstallConfig,
    rest_config: ProfileRestConfig,
    release_version: str,
) -> None:
    """Writes package-local scripts that start, update, and diagnose the install."""

    scripts_dir = config.target_path / "scripts"
    emule_exe = config.target_path / EMULEBB_PACKAGE_ROOT_NAME / APP_EXE_NAME
    amutorrent_root = config.target_path / "aMuTorrent"
    amutorrent_server = amutorrent_root / "server" / "server.js"
    live_wire_path = config.live_wire_inputs_file
    build_repo = layout.build_repo_root
    workspace_root = layout.emule_workspace_root
    scheme = "https" if rest_config.use_ssl else "http"

    _write_text(
        scripts_dir / "Start-EmuleBB.ps1",
        f"""#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$Exe = {ps_string(emule_exe)}
$ProfileDir = {ps_string(config.profile_dir)}
Start-Process -FilePath $Exe -ArgumentList @('-c', $ProfileDir)
""",
    )
    _write_text(
        scripts_dir / "Start-aMuTorrent.ps1",
        f"""#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$env:EMULEBB_ENABLED = 'true'
$env:EMULEBB_HOST = {ps_string(rest_config.host)}
$env:EMULEBB_PORT = '{rest_config.port}'
$env:EMULEBB_API_KEY = {ps_string(rest_config.api_key)}
$env:EMULEBB_USE_SSL = '{str(rest_config.use_ssl).lower()}'
$env:EMULEBB_ID = {ps_string(config.emulebb_id)}
$env:EMULEBB_NAME = {ps_string(config.emulebb_name)}
$env:AMUTORRENT_DATA_DIR = {ps_string(config.target_path / "aMuTorrent" / "data")}
$env:PORT = '{config.amutorrent_port}'
$env:BIND_ADDRESS = {ps_string(config.amutorrent_bind_address)}
$Node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
if (-not $Node) {{
    $Node = Join-Path {ps_string(config.target_path)} 'runtime\node\node.exe'
}}
if (-not (Test-Path -LiteralPath $Node)) {{
    throw 'Node 24 or newer is required to start aMuTorrent. Install Node or use Install-eMuleBBSuite.ps1 to provision the pinned runtime.'
}}
Push-Location {ps_string(amutorrent_root)}
try {{
    & $Node {ps_string(amutorrent_server)}
}} finally {{
    Pop-Location
}}
""",
    )
    _write_text(
        scripts_dir / "Start-All.ps1",
        f"""#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Start-EmuleBB.ps1')
$Headers = @{{ 'X-API-Key' = {ps_string(rest_config.api_key)} }}
$Uri = {ps_string(f"{scheme}://{rest_config.host}:{rest_config.port}/api/v1/app")}
for ($i = 0; $i -lt 60; $i++) {{
    try {{
        Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec 2 | Out-Null
        break
    }} catch {{
        Start-Sleep -Seconds 1
    }}
}}
& (Join-Path $PSScriptRoot 'Start-aMuTorrent.ps1')
""",
    )
    _write_text(
        scripts_dir / "Status-aMuTorrent.ps1",
        f"""#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Invoke-RestMethod -Uri 'http://127.0.0.1:{config.amutorrent_port}/health' -TimeoutSec 5 | ConvertTo-Json -Compress
""",
    )
    _write_text(
        scripts_dir / "Capture-Dump.ps1",
        f"""#Requires -Version 5.1
param(
    [int]$Pid = 0,
    [switch]$Full
)
$ErrorActionPreference = 'Stop'
$ProcDump = {ps_string(config.procdump_path)}
$Diagnostics = {ps_string(config.target_path / "diagnostics")}
$Exe = {ps_string(emule_exe)}
if ($Pid -eq 0) {{
    $Process = Get-Process emulebb -ErrorAction Stop | Where-Object {{ $_.Path -eq $Exe }} | Select-Object -First 1
    if ($null -eq $Process) {{ throw "No emulebb process found for $Exe." }}
    $Pid = $Process.Id
}}
$Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Kind = if ($Full) {{ 'full' }} else {{ 'mini' }}
$DumpPath = Join-Path $Diagnostics ("emulebb-dump-$Timestamp-pid$Pid-$Kind.dmp")
$Mode = if ($Full) {{ '-ma' }} else {{ '-mp' }}
& $ProcDump -accepteula $Mode $Pid $DumpPath
""",
    )
    _write_text(
        scripts_dir / "Update-LocalPackage.ps1",
        f"""#Requires -Version 5.1
param(
    [switch]$Clean,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
Push-Location {ps_string(build_repo)}
try {{
    $Args = @(
        'install-local-package',
        '--workspace-root', {ps_string(workspace_root)},
        '--release-version', {ps_string(release_version)},
        '--live-wire-inputs-file', {ps_string(live_wire_path)}
    )
    if ($Clean) {{ $Args += '--clean' }}
    if ($SkipBuild) {{ $Args += '--skip-build' }}
    python -m emule_workspace @Args
}} finally {{
    Pop-Location
}}
""",
    )


def write_install_manifest(
    layout: WorkspaceLayout,
    config: LocalInstallConfig,
    rest_config: ProfileRestConfig,
    artifacts: InstallArtifacts,
    release_version: str,
) -> None:
    """Writes a local manifest with hashes needed to match dumps to symbols."""

    target_root = config.target_path
    manifest_path = target_root / "manifests" / "local-install.json"
    emule_exe = target_root / EMULEBB_PACKAGE_ROOT_NAME / APP_EXE_NAME
    pdb_path = target_root / "symbols" / f"emulebb-v{release_version}" / artifacts.arch / "emulebb.pdb"
    adjacent_pdb_path = target_root / EMULEBB_PACKAGE_ROOT_NAME / "emulebb.pdb"
    payload = {
        "schema": INSTALL_MANIFEST_SCHEMA,
        "installedAtUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "releaseVersion": release_version,
        "platform": artifacts.arch,
        "workspaceRoot": str(layout.emule_workspace_root),
        "liveWireInputsFile": str(config.live_wire_inputs_file),
        "targetPath": str(target_root),
        "profileDir": str(config.profile_dir),
        "rest": {
            "host": rest_config.host,
            "port": rest_config.port,
            "useSsl": rest_config.use_ssl,
            "apiKeyPresent": bool(rest_config.api_key),
        },
        "artifacts": {
            "emuleZip": _file_record(artifacts.emule_zip),
            "amutorrentZip": _file_record(artifacts.amutorrent_zip),
            "emuleManifest": _file_record(artifacts.emule_manifest),
            "amutorrentManifest": _file_record(artifacts.amutorrent_manifest),
            "packageExe": _file_record(artifacts.package_exe),
            "packagePdb": _file_record(artifacts.package_pdb),
            "deployedExe": _file_record(emule_exe),
            "deployedPdb": _file_record(pdb_path),
            "deployedAdjacentPdb": _file_record(adjacent_pdb_path),
        },
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def parse_ini_values(text: str) -> dict[str, dict[str, str]]:
    """Parses INI values into case-insensitive section/key dictionaries."""

    result: dict[str, dict[str, str]] = {}
    current_section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].strip().lower()
            result.setdefault(current_section, {})
            continue
        if "=" in line and current_section:
            key, value = line.split("=", 1)
            result.setdefault(current_section, {})[key.strip().lower()] = value.strip()
    return result


def update_ini_values(text: str, updates: list[tuple[str, str, str]]) -> str:
    """Updates or appends INI keys while preserving unrelated lines."""

    pending = {(section.lower(), key.lower()): (section, key, value) for section, key, value in updates}
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    current_section = ""
    seen_sections: set[str] = set()

    for raw_line in lines:
        line_body = raw_line.rstrip("\r\n")
        newline = raw_line[len(line_body) :]
        stripped = line_body.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            _append_pending_for_section(output, pending, current_section, newline or "\n")
            current_section = stripped[1:-1].strip().lower()
            seen_sections.add(current_section)
            output.append(raw_line)
            continue
        if "=" in line_body and current_section:
            key, _value = line_body.split("=", 1)
            pending_key = (current_section, key.strip().lower())
            if pending_key in pending:
                _section, original_key, value = pending.pop(pending_key)
                line_newline = newline or "\n"
                output.append(f"{original_key}={value}{line_newline}")
                continue
        output.append(raw_line)

    final_newline = "\n"
    if lines:
        last = lines[-1]
        line_body = last.rstrip("\r\n")
        final_newline = last[len(line_body) :] or "\n"
    _append_pending_for_section(output, pending, current_section, final_newline)
    for section, key, value in list(pending.values()):
        if section.lower() not in seen_sections:
            if output and not output[-1].endswith(("\n", "\r")):
                output.append(final_newline)
            output.append(f"[{section}]{final_newline}")
            output.append(f"{key}={value}{final_newline}")
            pending.pop((section.lower(), key.lower()), None)
    return "".join(output)


def read_text_preserving_encoding(path: Path) -> DecodedText:
    """Reads text while preserving common Windows profile encodings for writes."""

    data = path.read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return DecodedText(data.decode("utf-16"), "utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return DecodedText(data.decode("utf-8-sig"), "utf-8-sig")
    try:
        return DecodedText(data.decode("utf-8"), "utf-8")
    except UnicodeDecodeError:
        return DecodedText(data.decode("mbcs"), "mbcs")


def _append_pending_for_section(
    output: list[str],
    pending: dict[tuple[str, str], tuple[str, str, str]],
    section: str,
    newline: str,
) -> None:
    for pending_key, (_section, key, value) in list(pending.items()):
        if pending_key[0] == section:
            output.append(f"{key}={value}{newline}")
            pending.pop(pending_key)


def _replace_emule_tree(source: Path, destination: Path, target_root: Path) -> None:
    if not source.is_dir():
        raise RuntimeError(f"Extracted eMule package root is missing: {source}")
    _assert_under_root(destination, target_root, "eMule install path")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(source), str(destination))


def _replace_amutorrent_tree(source: Path, destination: Path, target_root: Path) -> None:
    if not source.is_dir():
        raise RuntimeError(f"Extracted aMuTorrent package root is missing: {source}")
    _assert_under_root(destination, target_root, "aMuTorrent install path")
    destination.mkdir(parents=True, exist_ok=True)
    for child in list(destination.iterdir()):
        if child.name in PRESERVED_AMUTORRENT_DIRS:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    _copy_directory_contents(source, destination)


def _copy_directory_contents(source: Path, destination: Path) -> None:
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _extract_zip_safe(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target = (destination_root / member.filename).resolve()
            _assert_under_root_or_equal(target, destination_root, f"ZIP member '{member.filename}'")
        archive.extractall(destination_root)


def _load_json_object(path: Path, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"{description} is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{description} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{description} must contain one JSON object: {path}")
    return payload


def _required_path(payload: dict[str, Any], key: str) -> Path:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Local package install field {key!r} must be a non-empty path string.")
    return Path(value.strip()).expanduser().resolve()


def _optional_path(payload: dict[str, Any], key: str, default: Path) -> Path:
    value = payload.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Local package install field {key!r} must be a non-empty path string.")
    return Path(value.strip()).expanduser().resolve()


def _optional_string(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Local package install field {key!r} must be a non-empty string.")
    return value.strip()


def _optional_nullable_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Local package install field {key!r} must be null or a non-empty string.")
    return value.strip()


def _optional_int(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"Local package install field {key!r} must be a positive integer.")
    return value


def _optional_nullable_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"Local package install field {key!r} must be null or a positive integer.")
    return value


def _optional_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"Local package install field {key!r} must be a boolean.")
    return value


def _optional_nullable_bool(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise RuntimeError(f"Local package install field {key!r} must be null or a boolean.")
    return value


def _parse_int(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_bool(value: str, default: bool) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _sha256(path: Path) -> str:
    hasher = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _timestamp_for_path() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _assert_under_root(path: Path, root: Path, description: str) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path == resolved_root or not _is_relative_to(resolved_path, resolved_root):
        raise RuntimeError(f"{description} must stay under {resolved_root}: {resolved_path}")


def _assert_under_root_or_equal(path: Path, root: Path, description: str) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path != resolved_root and not _is_relative_to(resolved_path, resolved_root):
        raise RuntimeError(f"{description} must stay under {resolved_root}: {resolved_path}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\r\n")


def ps_string(value: str | Path) -> str:
    """Returns a single-quoted PowerShell literal."""

    return "'" + str(value).replace("'", "''") + "'"
