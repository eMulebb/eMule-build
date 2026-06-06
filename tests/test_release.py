from __future__ import annotations

import configparser
import hashlib
import json
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from emule_workspace import release
from emule_workspace.layout import AppVariant


@pytest.mark.parametrize(
    "release_version",
    [
        "0.7.3",
        "0.7.3-rc.1",
        "0.7.3-beta.2",
        "0.7.3-nightly.20260524.ae562c1",
        "0.7.3-nightly.20260524.0123456789abcdef",
    ],
)
def test_release_version_accepts_public_and_nightly_formats(release_version: str) -> None:
    assert release._is_release_version(release_version)


@pytest.mark.parametrize(
    "release_version",
    [
        "0.7",
        "0.7.3-nightly",
        "0.7.3-nightly.2026052.ae562c1",
        "0.7.3-nightly.20260524.zzzzzzz",
        "0.7.3-alpha.1",
    ],
)
def test_release_version_rejects_unknown_formats(release_version: str) -> None:
    assert not release._is_release_version(release_version)


def _pe_payload(machine: int) -> bytes:
    payload = bytearray(128)
    payload[0:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x40)
    payload[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<H", payload, 0x44, machine)
    return bytes(payload)


def _parse_rgb(value: str) -> tuple[int, int, int]:
    channels = tuple(int(channel.strip()) for channel in value.split(","))
    assert len(channels) == 3
    assert all(0 <= channel <= 255 for channel in channels)
    return channels


def _linear_channel(channel: int) -> float:
    normalized = channel / 255
    if normalized <= 0.03928:
        return normalized / 12.92
    return ((normalized + 0.055) / 1.055) ** 2.4


def _relative_luminance(color: tuple[int, int, int]) -> float:
    red, green, blue = (_linear_channel(channel) for channel in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _write_release_zip(
    path: Path,
    *,
    executable_name: str = "emulebb.exe",
    language_payloads: dict[str, bytes] | None = None,
    extra_entries: dict[str, bytes] | None = None,
    include_skin_assets: bool = True,
) -> None:
    entries = {
        f"eMuleBB/{executable_name}": _pe_payload(0x8664),
        "eMuleBB/README.md": b"readme\n",
        "eMuleBB/RELEASE-NOTES.md": b"notes\n",
        "eMuleBB/LICENSE-NOTICE.txt": b"notice\n",
        "eMuleBB/GPL-2.0-or-later.txt": b"gpl\n",
        "eMuleBB/THIRD-PARTY-NOTICES.txt": b"third party\n",
        "eMuleBB/SBOM.spdx.json": b'{"spdxVersion":"SPDX-2.3"}\n',
        "eMuleBB/docs/REST-API-CONTRACT.md": b"contract\n",
        "eMuleBB/docs/REST-API-OPENAPI.yaml": b"openapi\n",
        "eMuleBB/docs/REST-API-PARITY-INVENTORY.md": b"parity\n",
    }
    for relative_path in release.EMULEBB_RUNTIME_SCRIPT_PATHS:
        entries[f"eMuleBB/{relative_path}"] = b"#Requires -Version 5.1\n"
    if include_skin_assets:
        for relative_path in release.EMULEBB_SKIN_ASSET_PATHS:
            entries[f"eMuleBB/{relative_path}"] = b"skin-or-toolbar-asset\n"
    for name, payload in (language_payloads or {"de_DE.dll": _pe_payload(0x8664)}).items():
        entries[f"eMuleBB/lang/{name}"] = payload
    entries.update(extra_entries or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def _write_amutorrent_zip(path: Path, *, extra_entries: dict[str, bytes] | None = None) -> None:
    entries = {
        "aMuTorrent/README.md": b"readme\n",
        "aMuTorrent/LICENSE-aMuTorrent.txt": b"license\n",
        "aMuTorrent/SBOM.spdx.json": b'{"spdxVersion":"SPDX-2.3"}\n',
        "aMuTorrent/server/server.js": b"server\n",
        "aMuTorrent/server/package.json": b"{}\n",
        "aMuTorrent/server/package-lock.json": b"{}\n",
        "aMuTorrent/server/node_modules/express/package.json": b"{}\n",
        "aMuTorrent/server/node_modules/better-sqlite3/package.json": b"{}\n",
        "aMuTorrent/static/index.html": b"<html></html>\n",
        "aMuTorrent/static/output.css": b"body{}\n",
        "aMuTorrent/static/dist/app.bundle.js": b"console.log('ok');\n",
    }
    entries.update(extra_entries or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def test_package_release_dirty_guard_reports_all_provenance_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_root = tmp_path / "workspaces" / "workspace" / "app" / "emulebb-main"
    build_root = tmp_path / "repos" / "emulebb-build"
    tests_root = tmp_path / "repos" / "emulebb-build-tests"
    tooling_root = tmp_path / "repos" / "emulebb-tooling"
    for path in (app_root, build_root, tests_root, tooling_root):
        path.mkdir(parents=True)

    dirty = {
        app_root: ["## main...origin/main", " M srchybrid/Preferences.cpp"],
        build_root: ["## main...origin/main"],
        tests_root: ["## main...origin/main", "?? tests/python/test_release_update_urls.py"],
        tooling_root: ["## main...origin/main", " M docs/active/RELEASE-0.7.3.md"],
    }
    monkeypatch.setattr(release, "repo_status_lines", lambda repo: dirty[repo])
    layout = SimpleNamespace(
        build_repo_root=build_root,
        tests_repo_root=tests_root,
        tooling_repo_root=tooling_root,
    )

    with pytest.raises(RuntimeError, match="clean provenance inputs") as excinfo:
        release._assert_clean_release_inputs(layout, app_root)

    message = str(excinfo.value)
    assert "app source" in message
    assert "build orchestration" not in message
    assert "build tests" in message
    assert "tooling docs" in message
    assert "Preferences.cpp" in message
    assert "test_release_update_urls.py" in message
    assert "RELEASE-0.7.3.md" in message


def test_package_release_requires_main_app_source_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_root = tmp_path / "workspaces" / "workspace" / "app" / "emulebb-main"
    app_root.mkdir(parents=True)
    app_variant = AppVariant(name="main", path=app_root, branch="main")
    monkeypatch.setattr(release, "repo_branch", lambda repo: "feature/release-drift")

    with pytest.raises(RuntimeError, match="requires app variant 'main'.*branch 'main'"):
        release._assert_release_source_branch(app_variant)


def test_package_build_disables_startup_profiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_root = tmp_path / "app"
    captured: dict[str, object] = {}
    session = SimpleNamespace(
        layout=SimpleNamespace(toolset_override_variable="EMULEBB_TEST_TOOLSET"),
        options=SimpleNamespace(configuration="Release", platform="x64"),
    )

    monkeypatch.setattr(release, "ensure_app_dependency_artifacts", lambda _layout, _options, *, clean: None)
    monkeypatch.setattr(release, "app_property_overrides", lambda _layout, _platform: ("/p:DependencyRoot=test",))
    monkeypatch.setattr(release, "env_override", lambda _name: None)
    package_app_output_root = tmp_path / "state" / "package-build" / "emulebb-v0.7.3-rc.1" / "x64" / "app"
    package_app_intermediate_root = tmp_path / "state" / "package-build" / "emulebb-v0.7.3-rc.1" / "x64" / "app-obj"
    cfg_checks: list[Path] = []

    def fake_verify_app_control_flow_guard(*_args, **kwargs):
        cfg_checks.append(kwargs["binary_path"])

    monkeypatch.setattr(release, "verify_app_control_flow_guard", fake_verify_app_control_flow_guard)

    def fake_invoke_msbuild_project(*_args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(release, "invoke_msbuild_project", fake_invoke_msbuild_project)

    release._build_package_app(
        session,
        app_root,
        package_app_output_root=package_app_output_root,
        package_app_intermediate_root=package_app_intermediate_root,
        clean=True,
    )

    assert captured["project_path"] == app_root / "srchybrid" / "emule.vcxproj"
    assert captured["target"] == "Rebuild"
    assert "/p:DependencyRoot=test" in captured["extra_properties"]
    assert "/p:EnableStartupProfiling=false" in captured["extra_properties"]
    assert "/p:EnablePacketDiagnostics=false" in captured["extra_properties"]
    assert f"/p:OutDir={release.with_trailing_separator(package_app_output_root)}" in captured["extra_properties"]
    assert f"/p:IntDir={release.with_trailing_separator(package_app_intermediate_root)}" in captured["extra_properties"]
    assert cfg_checks == [package_app_output_root / "emulebb.exe"]


def test_diagnostics_package_build_enables_diagnostic_features(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_root = tmp_path / "app"
    captured: dict[str, object] = {}
    session = SimpleNamespace(
        layout=SimpleNamespace(toolset_override_variable="EMULEBB_TEST_TOOLSET"),
        options=SimpleNamespace(configuration="Release", platform="x64"),
    )

    monkeypatch.setattr(release, "ensure_app_dependency_artifacts", lambda _layout, _options, *, clean: None)
    monkeypatch.setattr(release, "app_property_overrides", lambda _layout, _platform: ())
    monkeypatch.setattr(release, "env_override", lambda _name: None)
    monkeypatch.setattr(release, "verify_app_control_flow_guard", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(release, "invoke_msbuild_project", lambda *_args, **kwargs: captured.update(kwargs))

    release._build_package_app(
        session,
        app_root,
        flavor=release.RELEASE_PACKAGE_FLAVORS[1],
        package_app_output_root=tmp_path / "out",
        package_app_intermediate_root=tmp_path / "obj",
        clean=False,
    )

    assert "/p:EnableStartupProfiling=true" in captured["extra_properties"]
    assert "/p:EnablePacketDiagnostics=true" in captured["extra_properties"]
    assert "/p:TargetName=emulebb-diagnostics" in captured["extra_properties"]
    assert captured["step_name"] == "APP main diagnostics package binary"


def test_release_package_rejects_startup_profiling_binary_marker(tmp_path: Path) -> None:
    exe_path = tmp_path / "emulebb.exe"
    exe_path.write_bytes(_pe_payload(0x8664) + "startup-profile.trace.json".encode("utf-16le"))

    with pytest.raises(RuntimeError, match="startup profiling support"):
        release._assert_startup_profiling_not_compiled(exe_path)


def test_release_package_accepts_binary_without_startup_profiling_marker(tmp_path: Path) -> None:
    exe_path = tmp_path / "emulebb.exe"
    exe_path.write_bytes(_pe_payload(0x8664) + b"regular release payload")

    release._assert_startup_profiling_not_compiled(exe_path)


def test_release_package_validates_diagnostics_markers(tmp_path: Path) -> None:
    exe_path = tmp_path / "emulebb.exe"
    exe_path.write_bytes(
        _pe_payload(0x8664)
        + "startup-profile.trace.json".encode("utf-16le")
        + b"emulebb-packet-diagnostics.log"
    )

    release._assert_release_binary_diagnostics(exe_path, release.RELEASE_PACKAGE_FLAVORS[1])


def test_standard_release_package_rejects_packet_diagnostics_marker(tmp_path: Path) -> None:
    exe_path = tmp_path / "emulebb.exe"
    exe_path.write_bytes(_pe_payload(0x8664) + b"emulebb-packet-diagnostics.log")

    with pytest.raises(RuntimeError, match="packet diagnostics support"):
        release._assert_release_binary_diagnostics(exe_path, release.RELEASE_PACKAGE_FLAVORS[0])


def test_package_language_resources_rebuild_serializes_msbuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_root = tmp_path / "app"
    language_solution = app_root / "srchybrid" / "lang" / "lang.sln"
    language_solution.parent.mkdir(parents=True)
    language_solution.write_text("solution\n", encoding="utf-8")
    captured: dict[str, object] = {}
    session = SimpleNamespace(
        layout=SimpleNamespace(toolset_override_variable="EMULEBB_TEST_TOOLSET"),
        options=SimpleNamespace(configuration="Release", platform="x64"),
    )

    monkeypatch.setattr(release, "_default_platform_toolset_property", lambda _layout: "/p:PlatformToolset=vTest")

    def fake_invoke_msbuild_project(*_args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(release, "invoke_msbuild_project", fake_invoke_msbuild_project)

    release._build_language_resources(session, app_root, clean=True)

    assert captured["project_path"] == language_solution
    assert captured["configuration"] == "Dynamic"
    assert captured["target"] == "Rebuild"
    assert captured["max_cpu_count"] == 1


def test_release_manifest_records_explicit_source_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_root = tmp_path / "workspaces" / "workspace" / "app" / "emulebb-main"
    build_root = tmp_path / "repos" / "emulebb-build"
    tests_root = tmp_path / "repos" / "emulebb-build-tests"
    tooling_root = tmp_path / "repos" / "emulebb-tooling"
    release_root = tmp_path / "workspaces" / "workspace" / "state" / "release" / "emulebb-v0.7.3-rc.1"
    zip_path = release_root / "emulebb-0.7.3-rc.1-x64.zip"
    for path in (app_root, build_root, tests_root, tooling_root, release_root):
        path.mkdir(parents=True)

    branches = {
        app_root: "main",
        build_root: "main",
        tests_root: "main",
        tooling_root: "main",
    }
    heads = {
        app_root: "app1234",
        build_root: "build12",
        tests_root: "tests12",
        tooling_root: "tools12",
    }
    monkeypatch.setattr(release, "repo_branch", lambda repo: branches[repo])
    monkeypatch.setattr(release, "repo_head", lambda repo: heads[repo])

    manifest = release._build_release_manifest(
        layout=SimpleNamespace(
            build_repo_root=build_root,
            tests_repo_root=tests_root,
            tooling_repo_root=tooling_root,
        ),
        workspace_options=SimpleNamespace(configuration="Release", platform="x64"),
        package_options=SimpleNamespace(release_version="0.7.3-rc.1"),
        app_variant=AppVariant(name="main", path=app_root, branch="main"),
        app_root=app_root,
        zip_path=zip_path,
        release_root=release_root,
        zip_hash="zip-sha",
        sbom_path=release_root / "emulebb-0.7.3-rc.1-x64.sbom.spdx.json",
        sbom_hash="sbom-sha",
        exe_hash="exe-sha",
        expected_language_dlls=("de_DE.dll", "fr_FR.dll"),
        package_file_hashes={"eMuleBB/emulebb.exe": "exe-entry-sha"},
        bootstrapper_asset_path=release_root / "Bootstrap-eMuleBBSuite.ps1",
        bootstrapper_hash_path=release_root / "Bootstrap-eMuleBBSuite.ps1.sha256",
        bootstrapper_hash="bootstrapper-sha",
        signature_policy={"mode": "unsigned", "required": False, "signedFiles": []},
    )

    assert manifest["appVariant"] == "main"
    assert manifest["packageFlavor"] == "standard"
    assert manifest["diagnosticFeatures"] == []
    assert manifest["executableName"] == "emulebb.exe"
    assert manifest["executablePath"] == "eMuleBB/emulebb.exe"
    assert manifest["appBranch"] == "main"
    assert manifest["appCommit"] == "app1234"
    assert manifest["buildBranch"] == "main"
    assert manifest["buildCommit"] == "build12"
    assert manifest["buildTestsBranch"] == "main"
    assert manifest["buildTestsCommit"] == "tests12"
    assert manifest["toolingBranch"] == "main"
    assert manifest["toolingCommit"] == "tools12"
    assert manifest["languageDllCount"] == 2
    assert manifest["languageDlls"] == ["de_DE.dll", "fr_FR.dll"]
    assert manifest["packageFileSha256"] == {"eMuleBB/emulebb.exe": "exe-entry-sha"}
    assert manifest["sbomFormat"] == "SPDX-2.3 JSON"
    assert manifest["sbomPath"] == "emulebb-0.7.3-rc.1-x64.sbom.spdx.json"
    assert manifest["sbomSha256"] == "sbom-sha"
    assert manifest["bootstrapperAsset"] == "Bootstrap-eMuleBBSuite.ps1"
    assert manifest["bootstrapperSha256"] == "bootstrapper-sha"
    assert manifest["bootstrapperSha256Path"] == "Bootstrap-eMuleBBSuite.ps1.sha256"
    assert manifest["signaturePolicy"] == {"mode": "unsigned", "required": False, "signedFiles": []}
    assert "eMuleBB/SBOM.spdx.json" in manifest["includedPaths"]
    assert "eMuleBB/scripts" in manifest["includedPaths"]
    assert "eMuleBB/skins" in manifest["includedPaths"]
    assert "eMuleBB/webserver" not in manifest["includedPaths"]


def test_expected_language_dlls_uses_release_language_manifest(tmp_path: Path) -> None:
    tooling_root = tmp_path / "repos" / "emulebb-tooling"
    manifest_path = tooling_root / "helpers" / "rc-release-languages.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"languages": [{"rc": "fr_FR.rc"}, {"rc": "de_DE.rc"}]}) + "\n",
        encoding="utf-8",
    )

    assert release._expected_language_dlls(tooling_root) == ("de_DE.dll", "fr_FR.dll")


def test_standalone_bootstrapper_asset_is_hashed_next_to_release(tmp_path: Path) -> None:
    package_root = tmp_path / "staging" / "eMuleBB"
    release_root = tmp_path / "release"
    bootstrapper = package_root / "scripts" / "Bootstrap-eMuleBBSuite.ps1"
    bootstrapper.parent.mkdir(parents=True)
    bootstrapper.write_text("#Requires -Version 5.1\nWrite-Host 'bootstrap'\n", encoding="utf-8")
    release_root.mkdir(parents=True)

    asset_path, hash_path, digest = release._write_standalone_bootstrapper_asset(
        package_root=package_root,
        release_root=release_root,
    )

    assert asset_path == release_root / "Bootstrap-eMuleBBSuite.ps1"
    assert hash_path == release_root / "Bootstrap-eMuleBBSuite.ps1.sha256"
    assert asset_path.read_text(encoding="utf-8") == bootstrapper.read_text(encoding="utf-8")
    assert digest == hashlib.sha256(asset_path.read_bytes()).hexdigest()
    assert hash_path.read_text(encoding="ascii") == f"{digest}  Bootstrap-eMuleBBSuite.ps1\n"


def test_release_signing_required_rejects_missing_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMULEBB_RELEASE_SIGN_CERT_SHA1", raising=False)
    monkeypatch.delenv("EMULEBB_RELEASE_SIGN_CERT_PATH", raising=False)

    with pytest.raises(RuntimeError, match="signing is required"):
        release._sign_release_package_files(Path("eMuleBB"), require_signing=True)


def test_release_signing_uses_signtool_for_authenticode_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = tmp_path / "staging" / "eMuleBB"
    (package_root / "scripts").mkdir(parents=True)
    (package_root / "lang").mkdir()
    (package_root / "emulebb.exe").write_bytes(b"exe")
    (package_root / "lang" / "de_DE.dll").write_bytes(b"dll")
    (package_root / "scripts" / "Install-eMuleBBSuite.ps1").write_text("#Requires -Version 5.1\n", encoding="utf-8")
    (package_root / "README.md").write_text("readme\n", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setenv("EMULEBB_RELEASE_SIGN_CERT_SHA1", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setenv("EMULEBB_SIGNTOOL", str(tmp_path / "signtool.exe"))
    monkeypatch.setattr(release.subprocess, "run", lambda command, check: commands.append([str(part) for part in command]))

    result = release._sign_release_package_files(package_root, require_signing=True)

    assert result["mode"] == "authenticode"
    assert result["required"] is True
    assert result["signedFiles"] == [
        "eMuleBB/emulebb.exe",
        "eMuleBB/lang/de_DE.dll",
        "eMuleBB/scripts/Install-eMuleBBSuite.ps1",
    ]
    assert len(commands) == 3
    assert all("/fd" in command and "SHA256" in command for command in commands)
    assert all("/sha1" in command and "0123456789abcdef0123456789abcdef01234567" in command for command in commands)


def test_spdx_sbom_describes_staged_package_files_without_self_reference(tmp_path: Path) -> None:
    release_root = tmp_path / "state" / "release" / "emulebb-v0.7.3-rc.1"
    package_root = release_root / "staging" / "x64" / "eMuleBB"
    package_root.mkdir(parents=True)
    (package_root / "emulebb.exe").write_bytes(b"exe")
    (package_root / "SBOM.spdx.json").write_text("old\n", encoding="utf-8")

    document = release._build_spdx_sbom(
        name="test sbom",
        namespace="https://example.invalid/sbom",
        package_name="emulebb-0.7.3-rc.1-x64",
        package_version="0.7.3-rc.1",
        package_license="GPL-2.0-or-later",
        package_comment="test package",
        package_root=package_root,
        release_root=release_root,
        components=[
            release._component_spdx_package(
                name="component",
                declared_license="MIT",
                version="abc123",
                download_location="https://example.invalid/component.git",
            )
        ],
    )

    file_names = {entry["fileName"] for entry in document["files"]}
    assert document["spdxVersion"] == "SPDX-2.3"
    assert document["documentDescribes"] == ["SPDXRef-Package"]
    assert document["packages"][0]["packageVerificationCode"]["packageVerificationCodeValue"]
    assert "eMuleBB/emulebb.exe" in file_names
    assert "eMuleBB/SBOM.spdx.json" not in file_names
    assert any(package["name"] == "component" for package in document["packages"])
    assert any(relationship["relationshipType"] == "DEPENDS_ON" for relationship in document["relationships"])


def test_release_package_contents_require_exact_language_set(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(zip_path, language_payloads={"de_DE.dll": _pe_payload(0x8664)})

    with pytest.raises(RuntimeError, match="missing language DLLs"):
        release._assert_release_package_contents(zip_path, ("de_DE.dll", "fr_FR.dll"), "x64")


def test_release_package_contents_reject_unexpected_language_dll(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(
        zip_path,
        language_payloads={"de_DE.dll": _pe_payload(0x8664), "extra.dll": _pe_payload(0x8664)},
    )

    with pytest.raises(RuntimeError, match="unexpected language DLLs"):
        release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")


def test_release_package_contents_reject_wrong_architecture(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(zip_path, language_payloads={"de_DE.dll": _pe_payload(0xAA64)})

    with pytest.raises(RuntimeError, match="PE architecture mismatch"):
        release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")


def test_release_package_contents_reject_forbidden_artifacts(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(zip_path, extra_entries={"eMuleBB/build/emule.pdb": b"symbols"})

    with pytest.raises(RuntimeError, match="build/source artifacts"):
        release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")


def test_release_package_contents_reject_legacy_webserver_payload(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(zip_path, extra_entries={"eMuleBB/webserver/eMule.tmpl": b"template\n"})

    with pytest.raises(RuntimeError, match="legacy webserver payload"):
        release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")


def test_release_package_contents_reject_retired_emule_root(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(zip_path, extra_entries={"eMule/emulebb.exe": _pe_payload(0x8664)})

    with pytest.raises(RuntimeError, match="retired eMule root"):
        release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")


def test_diagnostics_release_package_contents_require_named_executable_without_alias(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(zip_path, executable_name="emulebb-diagnostics.exe")

    release._assert_release_package_contents(
        zip_path,
        ("de_DE.dll",),
        "x64",
        flavor=release.RELEASE_PACKAGE_FLAVORS[1],
    )

    zip_with_alias = tmp_path / "package-with-alias.zip"
    _write_release_zip(
        zip_with_alias,
        executable_name="emulebb-diagnostics.exe",
        extra_entries={"eMuleBB/emulebb.exe": _pe_payload(0x8664)},
    )
    with pytest.raises(RuntimeError, match="compatibility alias"):
        release._assert_release_package_contents(
            zip_with_alias,
            ("de_DE.dll",),
            "x64",
            flavor=release.RELEASE_PACKAGE_FLAVORS[1],
        )


def test_release_package_contents_reject_runtime_script_without_powershell_51_header(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(
        zip_path,
        extra_entries={"eMuleBB/scripts/Register-Prowlarr.ps1": b"#Requires -Version 7.6\n"},
    )

    with pytest.raises(RuntimeError, match="PowerShell 5.1 compatibility"):
        release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")


def test_release_package_contents_require_skin_and_toolbar_assets(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(zip_path, include_skin_assets=False)

    with pytest.raises(RuntimeError, match="missing required entry"):
        release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")


def test_release_skin_assets_are_name_paired_without_source_theme_names() -> None:
    skin_names = {
        Path(relative_path).name.replace(".eMuleSkin.ini", "")
        for relative_path in release.EMULEBB_SKIN_ASSET_PATHS
        if relative_path.endswith(".eMuleSkin.ini")
    }
    toolbar_names = {
        Path(relative_path).name.replace(".eMuleToolbar.kad02.bmp", "")
        for relative_path in release.EMULEBB_SKIN_ASSET_PATHS
        if relative_path.endswith(".eMuleToolbar.kad02.bmp")
    }

    assert skin_names == toolbar_names
    assert len(skin_names) == 8
    forbidden_terms = ("bor" + "land", "mat" + "rix")
    assert not any(term in relative_path.lower() for term in forbidden_terms for relative_path in release.EMULEBB_SKIN_ASSET_PATHS)


def test_release_skin_profiles_define_readable_semantic_colors() -> None:
    required_keys = {
        "SearchResultsLvFg_AvblyBase",
        "SearchResultsLvFg_Downloading",
        "Fg_DownloadStopped",
        "SearchResultsLvFg_Sharing",
        "SearchResultsLvFg_Known",
        "SearchResultsLvFg_Cancelled",
        "SearchResultsLvFg_Incomplete",
        "TransferBarBackground",
        "TransferBarComplete",
        "TransferBarHave",
        "TransferBarMissing",
        "TransferBarPending",
        "TransferBarFileOp",
        "TransferBarPercentFg",
        "TransferBarSourceBase",
        "TransferBarSourceHot",
        "SharedPartsBarBackground",
        "SharedPartsBarMissing",
        "SharedPartsBarUnrequested",
        "SharedPartsBarAvailabilityBase",
        "SharedPartsBarAvailabilityHot",
        "TransferBarPeerBoth",
        "TransferBarPeerOnly",
        "TransferBarPeerActive",
        "TransferBarPeerNext",
        "UploadBarBackground",
        "UploadBarHave",
        "UploadBarSending",
        "UploadBarNext",
        "DetailProgressBackground",
        "DetailProgressStart",
        "DetailProgressEnd",
        "DetailProgressText",
        "ChatStatusFg",
        "ChatSentFg",
        "ChatReceivedFg",
        "ServersLvFg_Connected",
        "ServersLvFg_Failed",
        "ServersLvFg_Warning",
        "TreeGuideFg",
        "TreeBoxFg",
        "TooltipBk",
        "TooltipFg",
    }
    semantic_text_keys = {
        "SearchResultsLvFg_AvblyBase",
        "SearchResultsLvFg_Downloading",
        "Fg_DownloadStopped",
        "SearchResultsLvFg_Sharing",
        "SearchResultsLvFg_Known",
        "SearchResultsLvFg_Cancelled",
        "SearchResultsLvFg_Incomplete",
    }

    assets_root = Path(release.__file__).parent / "release_assets" / "emulebb"
    skin_paths = [
        assets_root / relative_path
        for relative_path in release.EMULEBB_SKIN_ASSET_PATHS
        if relative_path.endswith(".eMuleSkin.ini")
    ]

    for skin_path in skin_paths:
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read(skin_path, encoding="utf-8")
        colors = parser["Colors"]
        assert required_keys <= set(colors.keys()), skin_path.name

        background = _parse_rgb(colors["SearchResultsLvBk"])
        for key in semantic_text_keys:
            assert _contrast_ratio(background, _parse_rgb(colors[key])) >= 3.0, f"{skin_path.name}: {key}"
        for key in ("ChatStatusFg", "ChatSentFg", "ChatReceivedFg"):
            assert _contrast_ratio(_parse_rgb(colors["ChatBk"]), _parse_rgb(colors[key])) >= 3.0, f"{skin_path.name}: {key}"
        for key in ("ServersLvFg_Connected", "ServersLvFg_Failed", "ServersLvFg_Warning"):
            assert _contrast_ratio(_parse_rgb(colors["ServersLvBk"]), _parse_rgb(colors[key])) >= 3.0, f"{skin_path.name}: {key}"
        assert _contrast_ratio(_parse_rgb(colors["TooltipBk"]), _parse_rgb(colors["TooltipFg"])) >= 4.5, skin_path.name


def test_release_package_contents_accept_full_bundle_and_hash_entries(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(zip_path)

    release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")

    hashes = release._zip_entry_hashes(zip_path)
    assert hashes["eMuleBB/README.md"] == hashlib.sha256(b"readme\n").hexdigest()
    assert "eMuleBB/THIRD-PARTY-NOTICES.txt" in hashes
    assert "eMuleBB/SBOM.spdx.json" in hashes
    assert "eMuleBB/scripts/Bootstrap-eMuleBBSuite.ps1" in hashes
    assert "eMuleBB/scripts/Install-eMuleBBSuite.ps1" in hashes
    assert "eMuleBB/scripts/Register-Prowlarr.ps1" in hashes
    assert "eMuleBB/skins/emulebb-slate.eMuleSkin.ini" in hashes
    assert "eMuleBB/skins/emulebb-slate.eMuleToolbar.kad02.bmp" in hashes
    assert "eMuleBB/skins/emulebb-retro-teal.eMuleSkin.ini" in hashes
    assert "eMuleBB/skins/emulebb-retro-teal.eMuleToolbar.kad02.bmp" in hashes


def test_amutorrent_manifest_records_runtime_policy_and_source_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    amutorrent_root = tmp_path / "repos" / "amutorrent"
    build_root = tmp_path / "repos" / "emulebb-build"
    tests_root = tmp_path / "repos" / "emulebb-build-tests"
    tooling_root = tmp_path / "repos" / "emulebb-tooling"
    release_root = tmp_path / "state" / "release" / "emulebb-v0.7.3-rc.1"
    zip_path = release_root / "emulebb-0.7.3-rc.1-amutorrent-arm64.zip"
    for path in (amutorrent_root, build_root, tests_root, tooling_root, release_root):
        path.mkdir(parents=True)
    (amutorrent_root / "fork-delta.json").write_text(
        json.dumps(
            {
                "upstream": {
                    "url": "https://github.com/got3nks/amutorrent.git",
                    "branch": "main",
                    "baseCommit": "24b13e440d39c3c4dc9ed4516d59e304ec1e61f0",
                    "baseVersion": "3.8.5",
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    branches = {
        amutorrent_root: "main",
        build_root: "main",
        tests_root: "main",
        tooling_root: "main",
    }
    heads = {
        amutorrent_root: "amut123",
        build_root: "build12",
        tests_root: "tests12",
        tooling_root: "tools12",
    }
    monkeypatch.setattr(release, "repo_branch", lambda repo: branches[repo])
    monkeypatch.setattr(release, "repo_head", lambda repo: heads[repo])

    manifest = release._build_amutorrent_manifest(
        layout=SimpleNamespace(
            build_repo_root=build_root,
            tests_repo_root=tests_root,
            tooling_repo_root=tooling_root,
        ),
        workspace_options=SimpleNamespace(configuration="Release", platform="ARM64"),
        package_options=SimpleNamespace(release_version="0.7.3-rc.1"),
        amutorrent_root=amutorrent_root,
        zip_path=zip_path,
        release_root=release_root,
        zip_hash="zip-sha",
        sbom_path=release_root / "emulebb-0.7.3-rc.1-amutorrent-arm64.sbom.spdx.json",
        sbom_hash="sbom-sha",
        package_file_hashes={"aMuTorrent/server/server.js": "server-sha"},
    )

    assert manifest["package"] == "aMuTorrent optional controller"
    assert manifest["amutorrentBranch"] == "main"
    assert manifest["amutorrentCommit"] == "amut123"
    assert manifest["runtimePolicy"]["minimumPathNodeMajor"] == 24
    assert manifest["runtimePolicy"]["pinnedFallbackNodeVersion"] == "v24.15.0"
    assert manifest["runtimePolicy"]["pinnedFallbackNodeArchive"] == "node-v24.15.0-win-arm64.zip"
    assert manifest["runtimePolicy"]["runnerOwner"] == "eMuleBB suite installer"
    assert manifest["runtimePolicy"]["localAppDataUsed"] is False
    assert manifest["runtimePolicy"]["spacesInInstallPathAllowed"] is False
    assert manifest["upstreamBase"] == {
        "url": "https://github.com/got3nks/amutorrent.git",
        "branch": "main",
        "baseCommit": "24b13e440d39c3c4dc9ed4516d59e304ec1e61f0",
        "baseVersion": "3.8.5",
    }
    assert manifest["packageFileSha256"] == {"aMuTorrent/server/server.js": "server-sha"}
    assert manifest["sbomFormat"] == "SPDX-2.3 JSON"
    assert manifest["sbomPath"] == "emulebb-0.7.3-rc.1-amutorrent-arm64.sbom.spdx.json"
    assert manifest["sbomSha256"] == "sbom-sha"
    assert "aMuTorrent/SBOM.spdx.json" in manifest["includedPaths"]


def test_amutorrent_package_contents_accept_runtime_bundle(tmp_path: Path) -> None:
    zip_path = tmp_path / "amutorrent.zip"
    _write_amutorrent_zip(zip_path)

    release._assert_amutorrent_package_contents(zip_path)

    hashes = release._zip_entry_hashes(zip_path)
    assert hashes["aMuTorrent/README.md"] == hashlib.sha256(b"readme\n").hexdigest()
    assert "aMuTorrent/installer/windows/amutorrent.ps1" not in hashes
    assert "aMuTorrent/SBOM.spdx.json" in hashes


def test_amutorrent_package_contents_reject_generated_state_and_source_maps(tmp_path: Path) -> None:
    zip_path = tmp_path / "amutorrent.zip"
    _write_amutorrent_zip(
        zip_path,
        extra_entries={
            "aMuTorrent/server/data/config.json": b"{}\n",
            "aMuTorrent/static/dist/app.bundle.js.map": b"{}\n",
        },
    )

    with pytest.raises(RuntimeError, match="forbidden generated or source artifacts"):
        release._assert_amutorrent_package_contents(zip_path)


def test_amutorrent_package_contents_reject_standalone_installer_payload(tmp_path: Path) -> None:
    zip_path = tmp_path / "amutorrent.zip"
    _write_amutorrent_zip(zip_path, extra_entries={"aMuTorrent/installer/windows/amutorrent.ps1": b"#Requires -Version 5.1\n"})

    with pytest.raises(RuntimeError, match="forbidden generated or source artifacts"):
        release._assert_amutorrent_package_contents(zip_path)


def test_amutorrent_packaging_node_guard_accepts_matching_arch(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = SimpleNamespace(stdout="24.15.0|x64\n")
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: completed)

    release._assert_packaging_node_supported("x64")


def test_amutorrent_packaging_node_guard_rejects_cross_arch_native_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = SimpleNamespace(stdout="24.15.0|x64\n")
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(RuntimeError, match="native modules"):
        release._assert_packaging_node_supported("ARM64")
