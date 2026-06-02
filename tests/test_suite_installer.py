from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import suite_install_fixtures


INSTALLER = Path("emule_workspace/release_assets/emulebb/scripts/Install-eMuleBBSuite.ps1")
BOOTSTRAPPER = Path("emule_workspace/release_assets/emulebb/scripts/Bootstrap-eMuleBBSuite.ps1")


def _write_manifest(path: Path, zip_path: Path) -> None:
    path.write_text(
        json.dumps({"sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest()}) + "\n",
        encoding="utf-8",
    )


def _run_powershell(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell")
    assert powershell is not None
    return subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )


def _assert_powershell_parse(path: Path, *, cwd: Path) -> None:
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors) { $errors | Format-List *; exit 1 }"
    )
    _run_powershell(["-Command", command], cwd=cwd)


def test_suite_installer_core_install_writes_bind_aware_config_and_scripts(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    control_bind = "127.0.0.1"
    suite_install_fixtures.write_core_release(release_root)

    repo_root = Path.cwd()
    _run_powershell(
        [
            "-File",
            str((repo_root / INSTALLER).resolve()),
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Core",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
            "-ControlBindAddress",
            control_bind,
            "-P2PBindInterface",
            "hide.me",
            "-EmulebbPort",
            "14711",
        ],
        cwd=repo_root,
    )

    preferences = (install_root / "profiles" / "emulebb" / "config" / "preferences.ini").read_text(encoding="utf-16")
    assert "[eMule]" in preferences
    assert "BindInterface=hide.me" in preferences
    assert "BindAddr=\n" in preferences
    assert "BlockNetworkWhenBindUnavailableAtStartup=0" in preferences
    assert "NetworkGuardMode=Off" in preferences
    assert "NetworkGuardAllowedCIDRs=" in preferences
    assert "[WebServer]" in preferences
    assert f"BindAddr={control_bind}" in preferences
    assert "Port=14711" in preferences

    suite_config = json.loads((install_root / "manifests" / "suite-config.json").read_text(encoding="utf-8-sig"))
    assert suite_config["schema"] == "emulebb.suite-config.v1"
    assert suite_config["installKind"] == "Production"
    assert suite_config["emulebbPackageFlavor"] == "standard"
    assert suite_config["emulebbExecutableName"] == "emulebb.exe"
    assert suite_config["services"]["emulebb"]["bindAddress"] == control_bind
    assert suite_config["services"]["emulebb"]["port"] == 14711
    assert suite_config["services"]["amutorrent"]["bindAddress"] == control_bind
    assert suite_config["p2p"] == {
        "bindInterface": "hide.me",
        "blockNetworkWhenBindUnavailableAtStartup": False,
        "networkGuardMode": "Off",
        "networkGuardAllowedCIDRs": "",
    }

    install_manifest = json.loads((install_root / "manifests" / "suite-install.json").read_text(encoding="utf-8-sig"))
    assert install_manifest["profileImport"] == {
        "action": "fresh",
        "configured": False,
        "source": None,
        "sourcePreferencesSha256": None,
    }
    assert install_manifest["installKind"] == "Production"
    assert install_manifest["emulebbPackageFlavor"] == "standard"
    assert install_manifest["emulebbExecutableName"] == "emulebb.exe"
    assert install_manifest["services"]["emulebb"]["apiKeyPresent"] is True
    assert "apiKey" not in install_manifest["services"]["emulebb"]
    assert suite_config["services"]["emulebb"]["apiKey"] not in json.dumps(install_manifest)

    start_emulebb = (install_root / "scripts" / "Start-eMuleBB.ps1").read_text(encoding="utf-8-sig")
    assert "apps\\eMuleBB" in start_emulebb
    assert "emulebbExecutableName" in start_emulebb
    assert "'emulebb.exe'" in start_emulebb
    assert "profiles\\emulebb" in start_emulebb

    start_suite = (install_root / "scripts" / "Start-Suite.ps1").read_text(encoding="utf-8-sig")
    assert "suite-config.json" in start_suite
    assert "Start-eMuleBB.ps1" in start_suite
    assert "$env:BIND_ADDRESS = [string]$Config.services.amutorrent.bindAddress" in start_suite
    assert "Register-aMuTorrent.ps1" in start_suite

    for generated_script in (
        "Start-eMuleBB.ps1",
        "Start-Suite.ps1",
        "Stop-Suite.ps1",
        "Get-SuiteStatus.ps1",
        "Test-Suite.ps1",
        "Update-Suite.ps1",
    ):
        _assert_powershell_parse(install_root / "scripts" / generated_script, cwd=repo_root)


def test_suite_installer_copies_packaged_installer_into_suite_scripts(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    installer_payload = b"#Requires -Version 5.1\nWrite-Host 'fresh packaged installer'\n"
    suite_install_fixtures.write_core_release(release_root, installer_payload=installer_payload)

    repo_root = Path.cwd()
    _run_powershell(
        [
            "-File",
            str((repo_root / INSTALLER).resolve()),
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Core",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
        ],
        cwd=repo_root,
    )

    assert (install_root / "scripts" / "Install-eMuleBBSuite.ps1").read_bytes() == installer_payload


def test_suite_installer_core_install_uses_diagnostics_executable_name(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    suite_install_fixtures.write_core_release(
        release_root,
        package_flavor="diagnostics",
        executable_name="emulebb-diagnostics.exe",
    )

    repo_root = Path.cwd()
    suite_install_fixtures.run_installer(
        (repo_root / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Core",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
            "-EmulebbPackageFlavor",
            "diagnostics",
        ],
        cwd=repo_root,
    )

    assert (install_root / "apps" / "eMuleBB" / "emulebb-diagnostics.exe").is_file()
    assert not (install_root / "apps" / "eMuleBB" / "emulebb.exe").exists()
    suite_config = suite_install_fixtures.read_suite_config(install_root)
    assert suite_config["emulebbPackageFlavor"] == "diagnostics"
    assert suite_config["emulebbExecutableName"] == "emulebb-diagnostics.exe"
    install_manifest = suite_install_fixtures.read_suite_install_manifest(install_root)
    assert install_manifest["emulebbPackageFlavor"] == "diagnostics"
    assert install_manifest["emulebbExecutableName"] == "emulebb-diagnostics.exe"
    start_emulebb = (install_root / "scripts" / "Start-eMuleBB.ps1").read_text(encoding="utf-8-sig")
    assert "emulebbExecutableName" in start_emulebb
    assert "emulebb-diagnostics.exe" not in start_emulebb


def test_suite_installer_recomputes_executable_name_from_package_flavor(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    suite_install_fixtures.write_core_release(
        release_root,
        package_flavor="diagnostics",
        executable_name="emulebb-diagnostics.exe",
    )
    config_path = tmp_path / "stale-suite-config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": "emulebb.suite-config.v1",
                "emulebbPackageFlavor": "standard",
                "emulebbExecutableName": "emulebb.exe",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    repo_root = Path.cwd()
    suite_install_fixtures.run_installer(
        (repo_root / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Core",
            "-InstallRoot",
            str(install_root),
            "-ConfigFile",
            str(config_path),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
            "-EmulebbPackageFlavor",
            "diagnostics",
        ],
        cwd=repo_root,
    )

    suite_config = suite_install_fixtures.read_suite_config(install_root)
    assert suite_config["emulebbPackageFlavor"] == "diagnostics"
    assert suite_config["emulebbExecutableName"] == "emulebb-diagnostics.exe"
    assert (install_root / "apps" / "eMuleBB" / "emulebb-diagnostics.exe").is_file()


def test_suite_installer_rejects_release_manifest_without_sha256(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    package_zip = release_root / "emulebb-0.7.3-rc.1-x64.zip"
    manifest = release_root / "emulebb-0.7.3-rc.1-x64.manifest.json"
    suite_install_fixtures.write_zip(
        package_zip,
        {
            "eMuleBB/emulebb.exe": b"exe\n",
            "eMuleBB/scripts/Install-eMuleBBSuite.ps1": b"#Requires -Version 5.1\n",
        },
    )
    manifest.write_text("{}\n", encoding="utf-8")

    repo_root = Path.cwd()
    completed = subprocess.run(
        [
            shutil.which("powershell") or "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str((repo_root / INSTALLER).resolve()),
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Core",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
        ],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode != 0
    assert "eMuleBB release manifest must include a SHA256 hash." in completed.stdout


def test_suite_installer_full_install_uses_hashed_local_dependency_manifest_and_preserves_keys(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    dependency_root = tmp_path / "dependencies"
    install_root = tmp_path / "suite"
    package_zip = release_root / "emulebb-0.7.3-rc.1-x64.zip"
    package_manifest = release_root / "emulebb-0.7.3-rc.1-x64.manifest.json"
    amutorrent_zip = release_root / "emulebb-0.7.3-rc.1-amutorrent-x64.zip"
    amutorrent_manifest = release_root / "emulebb-0.7.3-rc.1-amutorrent-x64.manifest.json"
    dependency_manifest = tmp_path / "dependency-manifest.json"
    repo_root = Path.cwd()
    suite_install_fixtures.write_zip(
        package_zip,
        {
            "eMuleBB/emulebb.exe": b"exe\n",
            "eMuleBB/scripts/Install-eMuleBBSuite.ps1": (repo_root / INSTALLER).read_bytes(),
        },
    )
    _write_manifest(package_manifest, package_zip)
    suite_install_fixtures.write_zip(amutorrent_zip, {"aMuTorrent/server/server.js": b"server\n"})
    _write_manifest(amutorrent_manifest, amutorrent_zip)
    suite_install_fixtures.write_dependency_manifest(dependency_manifest, dependency_root)

    install_args = [
        "-File",
        str((repo_root / INSTALLER).resolve()),
        "-NonInteractive",
        "-NoStart",
        "-Force",
        "-Bundle",
        "Full",
        "-InstallRoot",
        str(install_root),
        "-ReleaseBaseUrl",
        release_root.as_uri(),
        "-DependencyManifest",
        str(dependency_manifest),
        "-P2PBindInterface",
        "hide.me",
    ]
    _run_powershell(install_args, cwd=repo_root)

    suite_config_path = install_root / "manifests" / "suite-config.json"
    suite_config = json.loads(suite_config_path.read_text(encoding="utf-8-sig"))
    first_keys = {
        name: suite_config["services"][name]["apiKey"]
        for name in ("emulebb", "prowlarr", "radarr", "sonarr")
    }
    assert (install_root / "apps" / "eMuleBB" / "emulebb.exe").is_file()
    assert (install_root / "apps" / "aMuTorrent" / "server" / "server.js").is_file()
    assert list((install_root / "runtime" / "node").rglob("node.exe"))
    assert list((install_root / "apps" / "prowlarr").rglob("Prowlarr.exe"))
    assert list((install_root / "apps" / "radarr").rglob("Radarr.exe"))
    assert list((install_root / "apps" / "sonarr").rglob("Sonarr.exe"))
    preferences = (install_root / "profiles" / "emulebb" / "config" / "preferences.ini").read_text(encoding="utf-16")
    assert "ApiKey=" + first_keys["emulebb"] in preferences
    assert "BindInterface=hide.me" in preferences
    assert "BindAddr=\n" in preferences
    assert f"BindAddr={suite_config['services']['emulebb']['bindAddress']}" in preferences
    for service_name in ("prowlarr", "radarr", "sonarr"):
        arr_config = (install_root / "data" / service_name / "config.xml").read_text(encoding="utf-8-sig")
        assert f"<BindAddress>{suite_config['services'][service_name]['bindAddress']}</BindAddress>" in arr_config
        assert f"<ApiKey>{first_keys[service_name]}</ApiKey>" in arr_config

    _run_powershell(
        [
            "-File",
            str((repo_root / INSTALLER).resolve()),
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-ConfigFile",
            str(suite_config_path),
            "-DependencyManifest",
            str(dependency_manifest),
        ],
        cwd=repo_root,
    )

    refreshed_config = json.loads(suite_config_path.read_text(encoding="utf-8-sig"))
    refreshed_keys = {
        name: refreshed_config["services"][name]["apiKey"]
        for name in ("emulebb", "prowlarr", "radarr", "sonarr")
    }
    assert refreshed_keys == first_keys


def test_suite_installer_imports_profile_config_only_once_and_preserves_refresh_profile(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    source_profile = tmp_path / "source-profile"
    suite_install_fixtures.write_core_release(release_root)
    source_config = source_profile / "config"
    source_config.mkdir(parents=True)
    source_preferences = source_config / "preferences.ini"
    source_preferences.write_text(
        "\n".join(
            [
                "[eMule]",
                "Nick=imported-user",
                r"IncomingDir=F:\old\incoming",
                "[WebServer]",
                "ApiKey=source-api-key",
                "Enabled=0",
                "CustomWebSetting=keep",
                "",
            ]
        ),
        encoding="utf-16",
    )
    source_preferences_hash = suite_install_fixtures.sha256_bytes(source_preferences.read_bytes())
    (source_config / "known.met").write_text("identity\n", encoding="utf-8")
    (source_profile / "runtime.log").write_text("do not import\n", encoding="utf-8")

    repo_root = Path.cwd()
    suite_install_fixtures.run_installer(
        (repo_root / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Core",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
            "-ImportProfileDir",
            str(source_profile),
            "-P2PBindInterface",
            "hide.me",
            "-EmulebbPort",
            "14711",
        ],
        cwd=repo_root,
    )

    profile_config = install_root / "profiles" / "emulebb" / "config"
    preferences_path = profile_config / "preferences.ini"
    preferences = preferences_path.read_text(encoding="utf-16")
    suite_config_path = install_root / "manifests" / "suite-config.json"
    suite_config = suite_install_fixtures.read_suite_config(install_root)
    assert "Nick=imported-user" in preferences
    assert "CustomWebSetting=keep" in preferences
    assert "IncomingDir=" + str(install_root / "downloads" / "incoming") in preferences
    assert "TempDir=" + str(install_root / "downloads" / "temp") in preferences
    assert "BindInterface=hide.me" in preferences
    assert "Enabled=1" in preferences
    assert "Port=14711" in preferences
    assert "ApiKey=" + suite_config["services"]["emulebb"]["apiKey"] in preferences
    assert "source-api-key" not in preferences
    assert (profile_config / "known.met").read_text(encoding="utf-8") == "identity\n"
    assert not (install_root / "profiles" / "emulebb" / "runtime.log").exists()
    assert source_preferences.read_text(encoding="utf-16").count(r"IncomingDir=F:\old\incoming") == 1
    assert suite_config["importProfileDir"] == str(source_profile)
    install_manifest = suite_install_fixtures.read_suite_install_manifest(install_root)
    assert install_manifest["profileImport"] == {
        "action": "imported",
        "configured": True,
        "source": str(source_profile),
        "sourcePreferencesSha256": source_preferences_hash,
    }

    preferences_path.write_text(
        preferences.replace("Nick=imported-user", "Nick=edited-after-bootstrap") + "RefreshOnly=keep\n",
        encoding="utf-16",
    )
    shutil.rmtree(source_profile)

    suite_install_fixtures.run_installer(
        (repo_root / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-ConfigFile",
            str(suite_config_path),
        ],
        cwd=repo_root,
    )

    refreshed_preferences = preferences_path.read_text(encoding="utf-16")
    refreshed_install_manifest = suite_install_fixtures.read_suite_install_manifest(install_root)
    assert "Nick=edited-after-bootstrap" in refreshed_preferences
    assert "RefreshOnly=keep" in refreshed_preferences
    assert "IncomingDir=" + str(install_root / "downloads" / "incoming") in refreshed_preferences
    assert refreshed_install_manifest["profileImport"] == {
        "action": "skipped-existing",
        "configured": True,
        "source": str(source_profile),
        "sourcePreferencesSha256": None,
    }


def test_suite_installer_profile_import_appends_missing_ini_sections(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    source_profile = tmp_path / "source-profile"
    suite_install_fixtures.write_core_release(release_root)
    source_config = source_profile / "config"
    source_config.mkdir(parents=True)
    (source_config / "preferences.ini").write_text("[eMule]\nNick=missing-webserver\n", encoding="utf-16")

    repo_root = Path.cwd()
    suite_install_fixtures.run_installer(
        (repo_root / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Core",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
            "-ImportProfileDir",
            str(source_profile),
            "-EmulebbPort",
            "14712",
        ],
        cwd=repo_root,
    )

    preferences = suite_install_fixtures.read_suite_preferences(install_root)
    suite_config = suite_install_fixtures.read_suite_config(install_root)
    assert "Nick=missing-webserver" in preferences
    assert "[WebServer]" in preferences
    assert "Enabled=1" in preferences
    assert "Port=14712" in preferences
    assert "ApiKey=" + suite_config["services"]["emulebb"]["apiKey"] in preferences


def test_suite_installer_import_profile_requires_source_before_bootstrap(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    missing_source = tmp_path / "missing-profile"
    package_zip = release_root / "emulebb-0.7.3-rc.1-x64.zip"
    manifest = release_root / "emulebb-0.7.3-rc.1-x64.manifest.json"
    suite_install_fixtures.write_zip(package_zip, {"eMuleBB/emulebb.exe": b"exe\n"})
    _write_manifest(manifest, package_zip)

    repo_root = Path.cwd()
    completed = subprocess.run(
        [
            shutil.which("powershell") or "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str((repo_root / INSTALLER).resolve()),
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Core",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
            "-ImportProfileDir",
            str(missing_source),
        ],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode != 0
    assert "ImportProfileDir must contain" in completed.stdout
    assert "preferences.ini" in completed.stdout


def test_suite_installer_copies_configured_emulebb_symbols(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    pdb_path = tmp_path / "build" / "emulebb.pdb"
    suite_install_fixtures.write_core_release(release_root)
    pdb_path.parent.mkdir()
    pdb_path.write_bytes(b"private-symbols\n")
    expected_hash = suite_install_fixtures.sha256_bytes(pdb_path.read_bytes())

    repo_root = Path.cwd()
    suite_install_fixtures.run_installer(
        (repo_root / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Core",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
            "-EmulebbPdbPath",
            str(pdb_path),
        ],
        cwd=repo_root,
    )

    adjacent_pdb = install_root / "apps" / "eMuleBB" / "emulebb.pdb"
    versioned_pdb = install_root / "symbols" / "emulebb-v0.7.3-rc.1" / "x64" / "emulebb.pdb"
    assert adjacent_pdb.read_bytes() == b"private-symbols\n"
    assert versioned_pdb.read_bytes() == b"private-symbols\n"
    install_manifest = suite_install_fixtures.read_suite_install_manifest(install_root)
    assert install_manifest["symbols"]["action"] == "copied"
    assert install_manifest["symbols"]["source"] == str(pdb_path)
    assert install_manifest["symbols"]["sourceSha256"] == expected_hash
    assert install_manifest["symbols"]["adjacentPdb"] == str(adjacent_pdb)
    assert install_manifest["symbols"]["versionedPdb"] == str(versioned_pdb)


def test_suite_installer_keeps_full_suite_service_binds_config_driven() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    assert '"  <BindAddress>$BindAddress</BindAddress>"' in installer
    assert "`$env:BIND_ADDRESS = [string]`$Config.services.amutorrent.bindAddress" in installer
    assert "Get-ClientHost `$Config.services.prowlarr.bindAddress" in installer
    assert "Get-ClientHost `$Config.services.radarr.bindAddress" in installer
    assert "Get-ClientHost `$Config.services.sonarr.bindAddress" in installer
    assert "BlockNetworkWhenBindUnavailableAtStartup=0" in installer
    assert "NetworkGuardMode=Off" in installer
    assert "NetworkGuardAllowedCIDRs=" in installer
    assert "Get-DefaultControlBindAddress" in installer
    assert "Get-AutoLanBindAddress" in installer
    assert "Test-AutoLanIPv4Address" in installer
    assert "'hide.me'" in installer
    assert "X_LOCAL_IP" in installer


def test_suite_installer_preserves_app_roots_when_extracting_multiple_packages() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "$extractRoot = Join-Path $downloadRoot (\"extract-$Name\")" in installer
    assert "$extractedPackageRoot = Join-Path $extractRoot $Name" in installer
    assert "$targetPackageRoot = Join-Path $Destination $Name" in installer
    assert "Move-Item -LiteralPath $extractedPackageRoot -Destination $targetPackageRoot" in installer


def test_suite_installer_requires_hashed_pinned_dependencies() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "9d388c476edfe579439830dc87f05fc50c86fa0dce80802726832c72088e731b" in installer
    assert "cc4fdffc4a82a3805e53aa9c016749fd17247eb21dd6764b1b53ced471695bb7" in installer
    assert "19a81e69dedd8d317b5fa8a1a9c48d63bc3b3f3ba87b84c94ff6d75b1803e419" in installer
    assert "Latest dependency resolution requires -DependencyManifest entries with exact URLs and SHA256 hashes." in installer
    assert "$Name dependency download requires a SHA256 hash." in installer


def test_suite_installer_global_bind_is_default_not_override() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    control_index = installer.index("@('ControlBindAddress'")
    emulebb_index = installer.index("@('EmulebbBindAddress'")
    amutorrent_index = installer.index("@('AmutorrentBindAddress'")
    assert control_index < emulebb_index < amutorrent_index
    assert "if ($PSBoundParameters.ContainsKey('ControlBindAddress'))" not in installer


def test_suite_generated_update_and_start_scripts_are_refresh_safe() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "& (Join-Path '$rootLiteral' 'scripts\\Stop-Suite.ps1')" in installer
    assert "apps\\eMuleBB\\scripts\\Install-eMuleBBSuite.ps1" in installer
    assert "Copy-Item -Force -LiteralPath $PSCommandPath -Destination (Join-Path $scriptsDir 'Install-eMuleBBSuite.ps1')" not in installer
    assert "function Test-ProcessRunning" in installer
    assert "function Start-ProcessIfMissing" in installer
    assert "eMuleBB is already running" in installer
    assert "Start-ProcessIfMissing -FilePath `$node" in installer


def test_suite_bootstrapper_requires_emulebb_package_root() -> None:
    _assert_powershell_parse(Path.cwd() / BOOTSTRAPPER, cwd=Path.cwd())
    bootstrapper = BOOTSTRAPPER.read_text(encoding="utf-8")

    assert "eMuleBB/scripts/Install-eMuleBBSuite.ps1" in bootstrapper
    assert "eMule/scripts/Install-eMuleBBSuite.ps1" not in bootstrapper
    assert "Release ZIP does not contain eMuleBB/scripts/Install-eMuleBBSuite.ps1." in bootstrapper
    assert "Assert-FileHash" in bootstrapper
    assert "IncludePrerelease" in bootstrapper
    assert "-EmulebbBindAddress" in bootstrapper
    assert "-AmutorrentPort" in bootstrapper
    assert "-AllowRemoteServiceBind" in bootstrapper
