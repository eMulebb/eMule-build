from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from emule_workspace.config import LocalPackageInstallOptions, WorkspaceOptions
from emule_workspace import local_package_install


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def _write_live_wire(path: Path, target: Path, profile: Path) -> None:
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
                "local_package_install": {
                    "target_path": str(target),
                    "profile_dir": str(profile),
                    "emulebb_id": "emulebb-test",
                    "emulebb_name": "eMuleBB test",
                },
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


def test_local_package_install_deploys_artifacts_and_preserves_runtime_state(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    layout.tests_repo_root.mkdir(parents=True)
    layout.build_repo_root.mkdir(parents=True)
    profile = tmp_path / "profile"
    preferences = profile / "config" / "preferences.ini"
    preferences.parent.mkdir(parents=True)
    preferences.write_text(
        "\n".join(
            [
                "[eMule]",
                r"IncomingDir=F:\incoming",
                r"TempDir=F:\temp",
                "[WebServer]",
                "ApiKey=secret-key",
                "BindAddr=192.168.1.210",
                "Port=4711",
                "UseHTTPS=0",
                "",
            ]
        ),
        encoding="utf-16",
    )
    target = tmp_path / "install"
    live_wire_path = layout.tests_repo_root / "live-wire-inputs.local.json"
    _write_live_wire(live_wire_path, target, profile)

    release_root = layout.workspace_root / "state" / "release" / "emulebb-v0.7.3-rc.1"
    package_build_root = layout.workspace_root / "state" / "package-build" / "emulebb-v0.7.3-rc.1" / "x64" / "app"
    package_build_root.mkdir(parents=True)
    (package_build_root / "emulebb.exe").write_bytes(b"exe")
    (package_build_root / "emulebb.pdb").write_bytes(b"pdb")
    _write_zip(release_root / "emulebb-0.7.3-rc.1-x64.zip", {"eMule/emulebb.exe": b"exe"})
    _write_zip(
        release_root / "emulebb-0.7.3-rc.1-amutorrent-x64.zip",
        {"aMuTorrent/installer/windows/amutorrent.ps1": b"#Requires -Version 5.1\n"},
    )
    for name in (
        "emulebb-0.7.3-rc.1-x64.manifest.json",
        "emulebb-0.7.3-rc.1-x64.sbom.spdx.json",
        "emulebb-0.7.3-rc.1-amutorrent-x64.manifest.json",
        "emulebb-0.7.3-rc.1-amutorrent-x64.sbom.spdx.json",
    ):
        (release_root / name).write_text("{}\n", encoding="utf-8")
    preserved_data = target / "aMuTorrent" / "data" / "keep.db"
    preserved_data.parent.mkdir(parents=True)
    preserved_data.write_text("keep", encoding="utf-8")
    stale_file = target / "aMuTorrent" / "old-package-file.txt"
    stale_file.write_text("stale", encoding="utf-8")

    local_package_install.install_local_package(
        layout,
        _workspace_options(tmp_path),
        LocalPackageInstallOptions(skip_build=True),
    )

    assert (target / "eMule" / "emulebb.exe").read_bytes() == b"exe"
    assert (target / "aMuTorrent" / "installer" / "windows" / "amutorrent.ps1").is_file()
    assert preserved_data.read_text(encoding="utf-8") == "keep"
    assert not stale_file.exists()
    assert (target / "symbols" / "emulebb-v0.7.3-rc.1" / "x64" / "emulebb.pdb").read_bytes() == b"pdb"
    assert (target / "scripts" / "Update-LocalPackage.ps1").is_file()
    assert not (target / "eMule" / "Incoming").exists()
    assert not (target / "eMule" / "Temp").exists()
    assert preferences.read_bytes().startswith(b"\xff\xfe")
    updated_preferences = preferences.read_text(encoding="utf-16")
    assert "IncomingDir=F:\\incoming" in updated_preferences
    assert "TempDir=F:\\temp" in updated_preferences
    assert "Enabled=1" in updated_preferences
    assert "CreateCrashDump=2" in updated_preferences
    assert list(preferences.parent.glob("preferences.ini.local-install-*.bak"))
    manifest = json.loads((target / "manifests" / "local-install.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == local_package_install.INSTALL_MANIFEST_SCHEMA
    assert manifest["rest"]["apiKeyPresent"] is True
    assert "secret-key" not in json.dumps(manifest)


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


def test_update_ini_values_appends_keys_to_existing_sections() -> None:
    text = "[eMule]\nNick=test\n[WebServer]\nApiKey=abc\n"

    updated = local_package_install.update_ini_values(
        text,
        [("eMule", "CreateCrashDump", "2"), ("WebServer", "Enabled", "1")],
    )

    assert "[eMule]\nNick=test\nCreateCrashDump=2\n[WebServer]\nApiKey=abc\nEnabled=1\n" == updated
