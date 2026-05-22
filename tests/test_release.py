from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from emule_workspace import release
from emule_workspace.layout import AppVariant


def _pe_payload(machine: int) -> bytes:
    payload = bytearray(128)
    payload[0:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x40)
    payload[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<H", payload, 0x44, machine)
    return bytes(payload)


def _write_release_zip(path: Path, *, language_payloads: dict[str, bytes] | None = None, extra_entries: dict[str, bytes] | None = None) -> None:
    entries = {
        "eMule/emule.exe": _pe_payload(0x8664),
        "eMule/README.md": b"readme\n",
        "eMule/RELEASE-NOTES.md": b"notes\n",
        "eMule/LICENSE-NOTICE.txt": b"notice\n",
        "eMule/GPL-2.0-or-later.txt": b"gpl\n",
        "eMule/THIRD-PARTY-NOTICES.txt": b"third party\n",
        "eMule/SBOM.spdx.json": b'{"spdxVersion":"SPDX-2.3"}\n',
        "eMule/docs/REST-API-CONTRACT.md": b"contract\n",
        "eMule/docs/REST-API-OPENAPI.yaml": b"openapi\n",
        "eMule/docs/REST-API-PARITY-INVENTORY.md": b"parity\n",
        "eMule/webserver/eMule.tmpl": b"template\n",
    }
    for name, payload in (language_payloads or {"de_DE.dll": _pe_payload(0x8664)}).items():
        entries[f"eMule/lang/{name}"] = payload
    entries.update(extra_entries or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def _amutorrent_script(*, data_dir: bool = True, space_check: bool = True, appdata: bool = False) -> bytes:
    lines = ["#Requires -Version 5.1"]
    if space_check:
        lines.append('if ($PackageRoot -match "\\s") { throw "path contains spaces" }')
    if data_dir:
        lines.append("$env:AMUTORRENT_DATA_DIR = $DataRoot")
    if appdata:
        lines.append("$env:LOCALAPPDATA")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_amutorrent_zip(path: Path, *, extra_entries: dict[str, bytes] | None = None, script_payload: bytes | None = None) -> None:
    entries = {
        "aMuTorrent/README.md": b"readme\n",
        "aMuTorrent/LICENSE-aMuTorrent.txt": b"license\n",
        "aMuTorrent/SBOM.spdx.json": b'{"spdxVersion":"SPDX-2.3"}\n',
        "aMuTorrent/installer/windows/amutorrent.ps1": script_payload or _amutorrent_script(),
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
    app_root = tmp_path / "workspaces" / "workspace" / "app" / "eMule-main"
    build_root = tmp_path / "repos" / "eMule-build"
    tests_root = tmp_path / "repos" / "eMule-build-tests"
    tooling_root = tmp_path / "repos" / "eMule-tooling"
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
    app_root = tmp_path / "workspaces" / "workspace" / "app" / "eMule-main"
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
        layout=SimpleNamespace(toolset_override_variable="EMULE_TEST_TOOLSET"),
        options=SimpleNamespace(configuration="Release", platform="x64"),
    )

    monkeypatch.setattr(release, "ensure_app_dependency_artifacts", lambda _layout, _options, *, clean: None)
    monkeypatch.setattr(release, "app_property_overrides", lambda _layout, _platform: ("/p:DependencyRoot=test",))
    monkeypatch.setattr(release, "env_override", lambda _name: None)
    package_app_output_root = tmp_path / "state" / "package-build" / "emule-bb-v0.7.3" / "x64" / "app"
    package_app_intermediate_root = tmp_path / "state" / "package-build" / "emule-bb-v0.7.3" / "x64" / "app-obj"
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
    assert f"/p:OutDir={release.with_trailing_separator(package_app_output_root)}" in captured["extra_properties"]
    assert f"/p:IntDir={release.with_trailing_separator(package_app_intermediate_root)}" in captured["extra_properties"]
    assert cfg_checks == [package_app_output_root / "emule.exe"]


def test_release_package_rejects_startup_profiling_binary_marker(tmp_path: Path) -> None:
    exe_path = tmp_path / "emule.exe"
    exe_path.write_bytes(_pe_payload(0x8664) + "startup-profile.trace.json".encode("utf-16le"))

    with pytest.raises(RuntimeError, match="startup profiling support"):
        release._assert_startup_profiling_not_compiled(exe_path)


def test_release_package_accepts_binary_without_startup_profiling_marker(tmp_path: Path) -> None:
    exe_path = tmp_path / "emule.exe"
    exe_path.write_bytes(_pe_payload(0x8664) + b"regular release payload")

    release._assert_startup_profiling_not_compiled(exe_path)


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
        layout=SimpleNamespace(toolset_override_variable="EMULE_TEST_TOOLSET"),
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
    app_root = tmp_path / "workspaces" / "workspace" / "app" / "eMule-main"
    build_root = tmp_path / "repos" / "eMule-build"
    tests_root = tmp_path / "repos" / "eMule-build-tests"
    tooling_root = tmp_path / "repos" / "eMule-tooling"
    release_root = tmp_path / "workspaces" / "workspace" / "state" / "release" / "emule-bb-v0.7.3"
    zip_path = release_root / "eMule-broadband-0.7.3-x64.zip"
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
        package_options=SimpleNamespace(release_version="0.7.3"),
        app_variant=AppVariant(name="main", path=app_root, branch="main"),
        app_root=app_root,
        zip_path=zip_path,
        release_root=release_root,
        zip_hash="zip-sha",
        sbom_path=release_root / "eMule-broadband-0.7.3-x64.sbom.spdx.json",
        sbom_hash="sbom-sha",
        exe_hash="exe-sha",
        expected_language_dlls=("de_DE.dll", "fr_FR.dll"),
        package_file_hashes={"eMule/emule.exe": "exe-entry-sha"},
    )

    assert manifest["appVariant"] == "main"
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
    assert manifest["packageFileSha256"] == {"eMule/emule.exe": "exe-entry-sha"}
    assert manifest["sbomFormat"] == "SPDX-2.3 JSON"
    assert manifest["sbomPath"] == "eMule-broadband-0.7.3-x64.sbom.spdx.json"
    assert manifest["sbomSha256"] == "sbom-sha"
    assert "eMule/SBOM.spdx.json" in manifest["includedPaths"]


def test_expected_language_dlls_uses_release_language_manifest(tmp_path: Path) -> None:
    tooling_root = tmp_path / "repos" / "eMule-tooling"
    manifest_path = tooling_root / "helpers" / "rc-release-languages.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"languages": [{"rc": "fr_FR.rc"}, {"rc": "de_DE.rc"}]}) + "\n",
        encoding="utf-8",
    )

    assert release._expected_language_dlls(tooling_root) == ("de_DE.dll", "fr_FR.dll")


def test_spdx_sbom_describes_staged_package_files_without_self_reference(tmp_path: Path) -> None:
    release_root = tmp_path / "state" / "release" / "emule-bb-v0.7.3"
    package_root = release_root / "staging" / "x64" / "eMule"
    (package_root / "webserver").mkdir(parents=True)
    (package_root / "emule.exe").write_bytes(b"exe")
    (package_root / "webserver" / "eMule.tmpl").write_bytes(b"template")
    (package_root / "SBOM.spdx.json").write_text("old\n", encoding="utf-8")

    document = release._build_spdx_sbom(
        name="test sbom",
        namespace="https://example.invalid/sbom",
        package_name="eMule-broadband-0.7.3-x64",
        package_version="0.7.3",
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
    assert "eMule/emule.exe" in file_names
    assert "eMule/webserver/eMule.tmpl" in file_names
    assert "eMule/SBOM.spdx.json" not in file_names
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
    _write_release_zip(zip_path, extra_entries={"eMule/build/emule.pdb": b"symbols"})

    with pytest.raises(RuntimeError, match="build/source artifacts"):
        release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")


def test_release_package_contents_accept_full_bundle_and_hash_entries(tmp_path: Path) -> None:
    zip_path = tmp_path / "package.zip"
    _write_release_zip(zip_path)

    release._assert_release_package_contents(zip_path, ("de_DE.dll",), "x64")

    hashes = release._zip_entry_hashes(zip_path)
    assert hashes["eMule/README.md"] == hashlib.sha256(b"readme\n").hexdigest()
    assert "eMule/THIRD-PARTY-NOTICES.txt" in hashes
    assert "eMule/SBOM.spdx.json" in hashes


def test_amutorrent_manifest_records_runtime_policy_and_source_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    amutorrent_root = tmp_path / "repos" / "amutorrent"
    build_root = tmp_path / "repos" / "eMule-build"
    tests_root = tmp_path / "repos" / "eMule-build-tests"
    tooling_root = tmp_path / "repos" / "eMule-tooling"
    release_root = tmp_path / "state" / "release" / "emule-bb-v0.7.3"
    zip_path = release_root / "eMule-broadband-0.7.3-amutorrent-arm64.zip"
    for path in (amutorrent_root, build_root, tests_root, tooling_root, release_root):
        path.mkdir(parents=True)

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
        package_options=SimpleNamespace(release_version="0.7.3"),
        amutorrent_root=amutorrent_root,
        zip_path=zip_path,
        release_root=release_root,
        zip_hash="zip-sha",
        sbom_path=release_root / "eMule-broadband-0.7.3-amutorrent-arm64.sbom.spdx.json",
        sbom_hash="sbom-sha",
        package_file_hashes={"aMuTorrent/installer/windows/amutorrent.ps1": "script-sha"},
    )

    assert manifest["package"] == "aMuTorrent optional controller"
    assert manifest["amutorrentBranch"] == "main"
    assert manifest["amutorrentCommit"] == "amut123"
    assert manifest["runtimePolicy"]["minimumPathNodeMajor"] == 24
    assert manifest["runtimePolicy"]["pinnedFallbackNodeVersion"] == "v24.15.0"
    assert manifest["runtimePolicy"]["pinnedFallbackNodeArchive"] == "node-v24.15.0-win-arm64.zip"
    assert manifest["runtimePolicy"]["localAppDataUsed"] is False
    assert manifest["runtimePolicy"]["spacesInInstallPathAllowed"] is False
    assert manifest["packageFileSha256"] == {"aMuTorrent/installer/windows/amutorrent.ps1": "script-sha"}
    assert manifest["sbomFormat"] == "SPDX-2.3 JSON"
    assert manifest["sbomPath"] == "eMule-broadband-0.7.3-amutorrent-arm64.sbom.spdx.json"
    assert manifest["sbomSha256"] == "sbom-sha"
    assert "aMuTorrent/SBOM.spdx.json" in manifest["includedPaths"]


def test_amutorrent_package_contents_accept_runtime_bundle(tmp_path: Path) -> None:
    zip_path = tmp_path / "amutorrent.zip"
    _write_amutorrent_zip(zip_path)

    release._assert_amutorrent_package_contents(zip_path)

    hashes = release._zip_entry_hashes(zip_path)
    assert hashes["aMuTorrent/README.md"] == hashlib.sha256(b"readme\n").hexdigest()
    assert "aMuTorrent/installer/windows/amutorrent.ps1" in hashes
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


def test_amutorrent_package_contents_require_package_local_data_script(tmp_path: Path) -> None:
    zip_path = tmp_path / "amutorrent.zip"
    _write_amutorrent_zip(zip_path, script_payload=_amutorrent_script(data_dir=False))

    with pytest.raises(RuntimeError, match="AMUTORRENT_DATA_DIR"):
        release._assert_amutorrent_package_contents(zip_path)


def test_amutorrent_package_contents_reject_appdata_defaults(tmp_path: Path) -> None:
    zip_path = tmp_path / "amutorrent.zip"
    _write_amutorrent_zip(zip_path, script_payload=_amutorrent_script(appdata=True))

    with pytest.raises(RuntimeError, match="app data"):
        release._assert_amutorrent_package_contents(zip_path)


def test_amutorrent_package_contents_require_space_path_rejection(tmp_path: Path) -> None:
    zip_path = tmp_path / "amutorrent.zip"
    _write_amutorrent_zip(zip_path, script_payload=_amutorrent_script(space_check=False))

    with pytest.raises(RuntimeError, match="spaces"):
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
