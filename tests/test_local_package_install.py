from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import suite_install_fixtures
from emule_workspace.config import LocalPackageInstallOptions, WorkspaceOptions
from emule_workspace import local_package_install
from emule_workspace import suite_installer


def _write_live_wire(path: Path, target: Path, **local_overrides: object) -> None:
    local_config = {
        "target_path": str(target),
        "emulebb_port": 14711,
        "amutorrent_port": 14000,
        "amutorrent_bind_address": "127.0.0.1",
        "p2p_bind_interface": "hide.me",
    }
    local_config.update(local_overrides)
    path.write_text(
        json.dumps(
            {
                "schema": local_package_install.LIVE_WIRE_SCHEMA,
                "search_terms": {
                    "generic_open": ["linux"],
                    "documents": ["linux"],
                    "radarr_movies": ["example"],
                    "sonarr_series": ["example"],
                },
                "auto_browse": {
                    "bootstrap_transfer_hashes": ["0123456789abcdef0123456789abcdef"],
                    "direct_bootstrap_transfers": [
                        {
                            "hash": "0123456789abcdef0123456789abcdef",
                            "name": "example.iso",
                            "size": 1024,
                            "method": "direct_ed2k",
                        }
                    ],
                },
                "local_package_install": local_config,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _layout(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        emule_workspace_root=tmp_path,
        workspace_root=tmp_path / "workspaces" / "workspace",
        build_repo_root=tmp_path / "repos" / "emulebb-build",
        tests_repo_root=tmp_path / "repos" / "emulebb-build-tests",
    )


def _workspace_options(tmp_path: Path) -> WorkspaceOptions:
    return WorkspaceOptions(
        workspace_root=tmp_path,
        workspace_name="workspace",
        configuration="Release",
        platform="x64",
        build_output_mode="ErrorsOnly",
    )


def _write_suite_profile(target: Path, *, exe_payload: bytes = b"exe") -> None:
    app_root = target / "apps" / "eMuleBB"
    profile_config = target / "profiles" / "emulebb" / "config"
    manifest_root = target / "manifests"
    (app_root).mkdir(parents=True, exist_ok=True)
    profile_config.mkdir(parents=True, exist_ok=True)
    manifest_root.mkdir(parents=True, exist_ok=True)
    (app_root / "emulebb.exe").write_bytes(exe_payload)
    (app_root / "emulebb.pdb").write_bytes(b"pdb")
    symbols_dir = target / "symbols" / "emulebb-v0.7.3-rc.1" / "x64"
    symbols_dir.mkdir(parents=True, exist_ok=True)
    (symbols_dir / "emulebb.pdb").write_bytes(b"pdb")
    (target / "apps" / "aMuTorrent" / "server").mkdir(parents=True, exist_ok=True)
    (target / "apps" / "aMuTorrent" / "server" / "server.js").write_text("server\n", encoding="utf-8")
    (profile_config / "preferences.ini").write_text(
        "\n".join(
            [
                "[eMule]",
                r"IncomingDir=C:\suite\incoming",
                r"TempDir=C:\suite\temp",
                "[WebServer]",
                "ApiKey=suite-secret-key",
                "BindAddr=127.0.0.1",
                "Port=14711",
                "UseHTTPS=0",
                "",
            ]
        ),
        encoding="utf-16",
    )
    (manifest_root / "suite-config.json").write_text(
        json.dumps(
            {
                "schema": "emulebb.suite-config.v1",
                "bundle": "Full",
                "services": {
                    "emulebb": {"bindAddress": "127.0.0.1", "port": 14711, "apiKey": "suite-secret-key"},
                    "amutorrent": {"bindAddress": "127.0.0.1", "port": 14000},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (manifest_root / "suite-install.json").write_text(
        json.dumps(
            {
                "schema": "emulebb.suite-install.v1",
                "bundle": "Full",
                "services": {"emulebb": {"apiKeyPresent": True}},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_local_package_install_deploys_artifacts_from_suite_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(tmp_path)
    layout.tests_repo_root.mkdir(parents=True)
    layout.build_repo_root.mkdir(parents=True)
    target = tmp_path / "install"
    live_wire_path = layout.tests_repo_root / "live-wire-inputs.local.json"
    import_profile = tmp_path / "import-profile"
    _write_live_wire(live_wire_path, target, import_profile_dir=str(import_profile))
    suite_install_fixtures.write_local_package_artifacts(
        layout.workspace_root,
        version="0.7.3-rc.1",
    )
    installer_calls: list[suite_installer.SuiteInstallerOptions] = []

    def fake_invoke_suite_installer(options: suite_installer.SuiteInstallerOptions) -> suite_installer.SuiteInstallerInvocation:
        installer_calls.append(options)
        _write_suite_profile(options.install_root)
        return suite_installer.SuiteInstallerInvocation(
            command=(),
            installer_script=options.installer_script,
            staging_root=options.installer_script.parent,
        )

    monkeypatch.setattr(local_package_install.suite_installer, "invoke_suite_installer", fake_invoke_suite_installer)

    result = local_package_install.materialize_local_install(
        layout,
        _workspace_options(tmp_path),
        LocalPackageInstallOptions(skip_build=True),
    )

    assert result.target_path == target.resolve()
    assert result.app_root == target / "apps" / "eMuleBB"
    assert result.app_exe == target / "apps" / "eMuleBB" / "emulebb.exe"
    assert result.profile_dir == target / "profiles" / "emulebb"
    assert result.profile_config_dir == target / "profiles" / "emulebb" / "config"
    assert result.manifest_path == target / "manifests" / "local-install.json"
    assert installer_calls
    assert installer_calls[0].emulebb_port == 14711
    assert installer_calls[0].p2p_bind_interface == "hide.me"
    assert installer_calls[0].import_profile_dir == import_profile.resolve()
    assert installer_calls[0].emulebb_pdb_path.name == "emulebb.pdb"
    assert installer_calls[0].bundle == "Full"
    assert (target / "apps" / "eMuleBB" / "emulebb.exe").read_bytes() == b"exe"
    assert (target / "apps" / "aMuTorrent" / "server" / "server.js").is_file()
    assert (target / "symbols" / "emulebb-v0.7.3-rc.1" / "x64" / "emulebb.pdb").read_bytes() == b"pdb"
    assert (target / "apps" / "eMuleBB" / "emulebb.pdb").read_bytes() == b"pdb"
    assert not (target / "scripts" / "Update-LocalPackage.ps1").exists()
    assert not (target / "scripts" / "Capture-Dump.ps1").exists()
    suite_preferences = (target / "profiles" / "emulebb" / "config" / "preferences.ini").read_text(encoding="utf-16")
    assert "IncomingDir=C:\\suite\\incoming" in suite_preferences
    assert "TempDir=C:\\suite\\temp" in suite_preferences
    assert "Enabled=1" in suite_preferences
    assert "CreateCrashDump=2" in suite_preferences
    assert list((target / "profiles" / "emulebb" / "config").glob("preferences.ini.local-install-*.bak"))
    manifest = json.loads((target / "manifests" / "local-install.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == local_package_install.INSTALL_MANIFEST_SCHEMA
    assert manifest["bundle"] == "Full"
    assert manifest["installKind"] == "Development"
    assert manifest["profileDir"] == str((target / "profiles" / "emulebb").resolve())
    assert manifest["importProfileDir"] == str(import_profile.resolve())
    assert "legacyProfileDir" not in manifest
    assert manifest["rest"]["apiKeyPresent"] is True
    assert manifest["artifacts"]["packageExe"]["sha256"] == manifest["artifacts"]["deployedExe"]["sha256"]
    assert manifest["artifacts"]["packagePdb"]["sha256"] == manifest["artifacts"]["deployedPdb"]["sha256"]
    assert manifest["artifacts"]["packagePdb"]["sha256"] == manifest["artifacts"]["deployedAdjacentPdb"]["sha256"]
    assert manifest["suite"]["config"]["path"].endswith("suite-config.json")
    assert "suite-secret-key" not in json.dumps(manifest)


def test_local_package_install_rejects_zip_exe_without_matching_package_build_exe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(tmp_path)
    layout.tests_repo_root.mkdir(parents=True)
    layout.build_repo_root.mkdir(parents=True)
    target = tmp_path / "install"
    live_wire_path = layout.tests_repo_root / "live-wire-inputs.local.json"
    _write_live_wire(live_wire_path, target)
    suite_install_fixtures.write_local_package_artifacts(
        layout.workspace_root,
        version="0.7.3-rc.1",
        package_exe_payload=b"package-build-exe",
        zip_exe_payload=b"zip-exe",
    )

    def fake_invoke_suite_installer(options: suite_installer.SuiteInstallerOptions) -> suite_installer.SuiteInstallerInvocation:
        _write_suite_profile(options.install_root, exe_payload=b"zip-exe")
        return suite_installer.SuiteInstallerInvocation(
            command=(),
            installer_script=options.installer_script,
            staging_root=options.installer_script.parent,
        )

    monkeypatch.setattr(local_package_install.suite_installer, "invoke_suite_installer", fake_invoke_suite_installer)

    try:
        local_package_install.install_local_package(
            layout,
            _workspace_options(tmp_path),
            LocalPackageInstallOptions(skip_build=True),
        )
    except RuntimeError as exc:
        assert "does not match the package-build executable" in str(exc)
    else:
        raise AssertionError("Expected mismatched package executable to fail")


def test_load_local_install_config_requires_live_wire_object(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    layout.tests_repo_root.mkdir(parents=True)
    live_wire_path = layout.tests_repo_root / "live-wire-inputs.local.json"
    live_wire_path.write_text(json.dumps({"schema": local_package_install.LIVE_WIRE_SCHEMA}) + "\n", encoding="utf-8")

    try:
        local_package_install.load_local_install_config(layout, None)
    except RuntimeError as exc:
        assert "local_package_install" in str(exc)
    else:
        raise AssertionError("Expected missing local_package_install to fail")


@pytest.mark.parametrize("retired_field", ["profile_dir", "procdump_path"])
def test_load_local_install_config_rejects_retired_fields(tmp_path: Path, retired_field: str) -> None:
    layout = _layout(tmp_path)
    layout.tests_repo_root.mkdir(parents=True)
    live_wire_path = layout.tests_repo_root / "live-wire-inputs.local.json"
    _write_live_wire(live_wire_path, tmp_path / "install", **{retired_field: str(tmp_path / "legacy")})

    with pytest.raises(RuntimeError, match="retired field"):
        local_package_install.load_local_install_config(layout, None)


def test_suite_installer_command_uses_full_bundle_and_existing_suite_config(tmp_path: Path) -> None:
    target = tmp_path / "install"
    live_wire_path = tmp_path / "live-wire-inputs.local.json"
    _write_live_wire(live_wire_path, target)
    payload = json.loads(live_wire_path.read_text(encoding="utf-8"))
    payload["local_package_install"]["dependency_manifest"] = str(tmp_path / "deps.json")
    payload["local_package_install"]["import_profile_dir"] = str(tmp_path / "import-profile")
    live_wire_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    layout = _layout(tmp_path)
    layout.tests_repo_root.mkdir(parents=True)
    config = local_package_install.load_local_install_config(layout, str(live_wire_path))
    release_root = tmp_path / "release"
    release_root.mkdir()
    suite_config = target / "manifests" / "suite-config.json"
    suite_config.parent.mkdir(parents=True)
    suite_config.write_text("{}\n", encoding="utf-8")
    artifacts = local_package_install.InstallArtifacts(
        release_root=release_root,
        emule_zip=release_root / "emule.zip",
        amutorrent_zip=release_root / "amutorrent.zip",
        emule_manifest=release_root / "emule.manifest.json",
        emule_sbom=release_root / "emule.sbom.json",
        amutorrent_manifest=release_root / "amutorrent.manifest.json",
        amutorrent_sbom=release_root / "amutorrent.sbom.json",
        package_exe=release_root / "emulebb.exe",
        package_pdb=release_root / "emulebb.pdb",
        arch="x64",
        installer_script=target / ".staging" / "Install-eMuleBBSuite.ps1",
    )

    options = local_package_install.build_suite_installer_options(config, artifacts, "0.7.3-rc.1")
    command = [str(part) for part in suite_installer.build_suite_installer_invocation(
        powershell=Path("powershell.exe"),
        options=options,
    ).command]

    assert command[command.index("-Bundle") + 1] == "Full"
    assert command[command.index("-InstallRoot") + 1] == str(target.resolve())
    assert command[command.index("-InstallKind") + 1] == "Development"
    assert command[command.index("-ConfigFile") + 1] == str(suite_config)
    assert command[command.index("-DependencyManifest") + 1] == str((tmp_path / "deps.json").resolve())
    assert command[command.index("-ImportProfileDir") + 1] == str((tmp_path / "import-profile").resolve())
    assert command[command.index("-EmulebbPdbPath") + 1] == str((release_root / "emulebb.pdb"))
    assert command[command.index("-P2PBindInterface") + 1] == "hide.me"


def test_update_ini_values_appends_keys_to_existing_sections() -> None:
    text = "[eMule]\nNick=test\n[WebServer]\nApiKey=abc\n"

    updated = local_package_install.update_ini_values(
        text,
        [("eMule", "CreateCrashDump", "2"), ("WebServer", "Enabled", "1")],
    )

    assert "[eMule]\nNick=test\nCreateCrashDump=2\n[WebServer]\nApiKey=abc\nEnabled=1\n" == updated
