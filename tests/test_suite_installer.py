from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

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
    assert suite_config["credentials"]["username"] == "admin"
    assert re.fullmatch(r"[A-Za-z0-9]{16}", suite_config["credentials"]["password"])
    assert re.fullmatch(r"[A-Za-z0-9]{16}", suite_config["services"]["emulebb"]["apiKey"])
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
    assert suite_config["credentials"]["password"] not in json.dumps(install_manifest)

    credentials = (install_root / "credentials.txt").read_text(encoding="utf-8-sig")
    assert "eMuleBB Suite credentials" in credentials
    assert "Suite web login" in credentials
    assert "Username: admin" in credentials
    assert f"Password: {suite_config['credentials']['password']}" in credentials
    assert f"eMuleBB URL: http://{control_bind}:14711" in credentials
    assert f"eMuleBB API key: {suite_config['services']['emulebb']['apiKey']}" in credentials
    credentials_html = (install_root / "credentials.html").read_text(encoding="utf-8-sig")
    assert "eMuleBB Suite Credentials" in credentials_html
    assert f"http://{control_bind}:14711" in credentials_html
    assert 'data-copy="' in credentials_html
    assert suite_config["credentials"]["password"] in credentials_html
    assert suite_config["services"]["emulebb"]["apiKey"] in credentials_html

    start_emulebb = (install_root / "scripts" / "Start-eMuleBB.ps1").read_text(encoding="utf-8-sig")
    assert "apps\\eMuleBB" in start_emulebb
    assert "emulebbExecutableName" in start_emulebb
    assert "'emulebb.exe'" in start_emulebb
    assert "profiles\\emulebb" in start_emulebb

    start_suite = (install_root / "scripts" / "Start-Suite.ps1").read_text(encoding="utf-8-sig")
    assert "suite-config.json" in start_suite
    assert "Start-eMuleBB.ps1" in start_suite
    assert "$env:BIND_ADDRESS = [string]$Config.services.amutorrent.bindAddress" in start_suite
    assert "$env:WEB_AUTH_ENABLED = 'true'" in start_suite
    assert "$env:WEB_AUTH_ADMIN_USERNAME = [string]$Config.credentials.username" in start_suite
    assert "$env:WEB_AUTH_PASSWORD = [string]$Config.credentials.password" in start_suite
    assert "/api/auth/status" in start_suite
    assert "Register-aMuTorrent.ps1" in start_suite
    assert "-AmutorrentUsername ([string]$Config.credentials.username)" in start_suite
    assert "-AmutorrentPassword ([string]$Config.credentials.password)" in start_suite
    assert "function Set-ArrHostCredentials" in start_suite
    assert "$hostConfig.authenticationMethod = 'forms'" in start_suite
    assert "$hostConfig.authenticationRequired = 'enabled'" in start_suite
    assert "$hostConfig.username = [string]$Config.credentials.username" in start_suite
    assert "$hostConfig.password = [string]$Config.credentials.password" in start_suite
    assert "Set-ArrHostCredentials -Name 'Prowlarr'" in start_suite
    assert "Set-ArrHostCredentials -Name 'Radarr'" in start_suite
    assert "Set-ArrHostCredentials -Name 'Sonarr'" in start_suite
    assert "function Ensure-ArrRootFolder" in start_suite
    assert "$rootFolderUrl = \"$Url/$ApiPath/rootfolder\"" in start_suite
    assert "New-Item -ItemType Directory -Force -Path $Path" in start_suite
    assert "$rootFolder.PSObject.Properties['path']" in start_suite
    assert "Ensure-ArrRootFolder -Name 'Radarr'" in start_suite
    assert "Join-Path $Root 'media\\movies'" in start_suite
    assert "Ensure-ArrRootFolder -Name 'Sonarr'" in start_suite
    assert "Join-Path $Root 'media\\series'" in start_suite
    assert "function Start-ArrHost" in start_suite
    assert "$trayName = $Name + '.exe'" in start_suite
    assert "Missing Windows tray host" in start_suite
    assert "Start-ProcessIfMissing -FilePath $exe.FullName" in start_suite
    assert "Start-ProcessIfMissing -FilePath $exe.FullName -ArgumentList @('/data='" in start_suite
    assert "function Ensure-EmuleBBAvailable" in start_suite
    assert "function Invoke-StepWithRetry" in start_suite
    assert "Invoke-StepWithRetry -Name 'Sonarr registration'" in start_suite
    assert start_suite.index("foreach ($item in @(@('Prowlarr'") < start_suite.index("$env:PORT = [string]$Config.services.amutorrent.port")
    assert start_suite.index("$env:PORT = [string]$Config.services.amutorrent.port") < start_suite.index("Start-ProcessIfMissing -FilePath $node")

    stop_suite = (install_root / "scripts" / "Stop-Suite.ps1").read_text(encoding="utf-8-sig")
    assert "Get-CimInstance Win32_Process" in stop_suite
    assert "apps\\aMuTorrent\\server\\server.js" in stop_suite
    assert "$_.Name -eq 'node.exe'" in stop_suite

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


def test_suite_installer_accepts_local_emulebb_package_zip_override(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    package_version = "0.7.3-nightly.20260604.localabc"
    release = suite_install_fixtures.write_core_release(release_root, version=package_version)

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
            "-EmulebbPackageZip",
            str(release.package_zip),
            "-EmulebbPackageManifest",
            str(release.manifest),
        ],
        cwd=repo_root,
    )

    suite_config = json.loads((install_root / "manifests" / "suite-config.json").read_text(encoding="utf-8-sig"))
    assert suite_config["version"] == package_version
    assert Path(suite_config["packageSources"]["emulebb"]["zip"]) == release.package_zip
    assert Path(suite_config["packageSources"]["emulebb"]["manifest"]) == release.manifest
    assert (install_root / "apps" / "eMuleBB" / "emulebb.exe").is_file()


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


def test_suite_installer_full_release_asset_gap_fails_before_app_replace(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    install_root = tmp_path / "suite"
    suite_install_fixtures.write_core_release(release_root)

    repo_root = Path.cwd()
    completed = suite_install_fixtures.run_installer(
        (repo_root / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Full",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
        ],
        cwd=repo_root,
        check=False,
    )

    assert completed.returncode != 0
    assert "Failed to download" in completed.stdout
    assert "emulebb-0.7.3-rc.1-amutorrent-x64.manifest.json" in completed.stdout
    assert not (install_root / "apps" / "eMuleBB").exists()


def test_suite_installer_full_can_use_separate_amutorrent_release_base(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    amutorrent_release_root = tmp_path / "amutorrent-release"
    dependency_root = tmp_path / "dependencies"
    install_root = tmp_path / "suite"
    amutorrent_version = "0.7.3-nightly.20260604.9eff539e"
    amutorrent_zip = amutorrent_release_root / f"emulebb-{amutorrent_version}-amutorrent-x64.zip"
    amutorrent_manifest = amutorrent_release_root / f"emulebb-{amutorrent_version}-amutorrent-x64.manifest.json"
    dependency_manifest = tmp_path / "dependency-manifest.json"
    suite_install_fixtures.write_core_release(release_root)
    suite_install_fixtures.write_zip(amutorrent_zip, {"aMuTorrent/server/server.js": b"server\n"})
    _write_manifest(amutorrent_manifest, amutorrent_zip)
    suite_install_fixtures.write_dependency_manifest(dependency_manifest, dependency_root)

    repo_root = Path.cwd()
    suite_install_fixtures.run_installer(
        (repo_root / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-NoStart",
            "-Force",
            "-Bundle",
            "Full",
            "-InstallRoot",
            str(install_root),
            "-ReleaseBaseUrl",
            release_root.as_uri(),
            "-AmutorrentReleaseBaseUrl",
            amutorrent_release_root.as_uri(),
            "-AmutorrentVersion",
            amutorrent_version,
            "-DependencyManifest",
            str(dependency_manifest),
        ],
        cwd=repo_root,
    )

    assert (install_root / "apps" / "eMuleBB" / "emulebb.exe").is_file()
    assert (install_root / "apps" / "aMuTorrent" / "server" / "server.js").is_file()
    suite_config = suite_install_fixtures.read_suite_config(install_root)
    assert suite_config["amutorrentReleaseBaseUrl"] == amutorrent_release_root.as_uri()
    assert suite_config["amutorrentVersion"] == amutorrent_version


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
        "-EmulebbPackageZip",
        str(package_zip),
        "-EmulebbPackageManifest",
        str(package_manifest),
        "-AmutorrentPackageZip",
        str(amutorrent_zip),
        "-AmutorrentPackageManifest",
        str(amutorrent_manifest),
        "-ControlBindAddress",
        "127.0.0.1",
        "-DependencyManifest",
        str(dependency_manifest),
        "-P2PBindInterface",
        "hide.me",
    ]
    try:
        occupied_port = socket.create_server(("127.0.0.1", 54000))
    except OSError:
        occupied_port = None
    try:
        _run_powershell(install_args, cwd=repo_root)
    finally:
        if occupied_port is not None:
            occupied_port.close()

    suite_config_path = install_root / "manifests" / "suite-config.json"
    suite_config = json.loads(suite_config_path.read_text(encoding="utf-8-sig"))
    first_keys = {
        name: suite_config["services"][name]["apiKey"]
        for name in ("emulebb", "prowlarr", "radarr", "sonarr")
    }
    suite_password = suite_config["credentials"]["password"]
    assert re.fullmatch(r"[A-Za-z0-9]{16}", suite_password)
    for key in first_keys.values():
        assert re.fullmatch(r"[A-Za-z0-9]{16}", key)
    service_order = ("emulebb", "amutorrent", "prowlarr", "radarr", "sonarr")
    service_ports = [suite_config["services"][name]["port"] for name in service_order]
    assert service_ports == list(range(service_ports[0], service_ports[0] + len(service_ports)))
    assert 54001 <= service_ports[0] <= 59995
    assert not ({4711, 4000, 9696, 7878, 8989} & set(service_ports))
    assert (install_root / "apps" / "eMuleBB" / "emulebb.exe").is_file()
    assert (install_root / "apps" / "aMuTorrent" / "server" / "server.js").is_file()
    assert Path(suite_config["packageSources"]["emulebb"]["zip"]) == package_zip
    assert Path(suite_config["packageSources"]["amutorrent"]["zip"]) == amutorrent_zip
    assert list((install_root / "runtime" / "node").rglob("node.exe"))
    assert list((install_root / "apps" / "prowlarr").rglob("Prowlarr.exe"))
    assert list((install_root / "apps" / "radarr").rglob("Radarr.exe"))
    assert list((install_root / "apps" / "sonarr").rglob("Sonarr.exe"))
    assert list((install_root / "apps" / "prowlarr").rglob("Prowlarr.Console.exe"))
    assert list((install_root / "apps" / "radarr").rglob("Radarr.Console.exe"))
    assert list((install_root / "apps" / "sonarr").rglob("Sonarr.Console.exe"))
    preferences = (install_root / "profiles" / "emulebb" / "config" / "preferences.ini").read_text(encoding="utf-16")
    assert "ApiKey=" + first_keys["emulebb"] in preferences
    assert "BindInterface=hide.me" in preferences
    assert "BindAddr=\n" in preferences
    assert f"BindAddr={suite_config['services']['emulebb']['bindAddress']}" in preferences
    assert f"Port={suite_config['services']['emulebb']['port']}" in preferences
    category_ini = (install_root / "profiles" / "emulebb" / "config" / "Category.ini").read_text(encoding="utf-16")
    assert "Count=3" in category_ini
    assert "Title=emulebb-prowlarr" in category_ini
    assert f"Incoming={install_root}\\downloads\\prowlarr" in category_ini
    assert "Title=emulebb-radarr" in category_ini
    assert f"Incoming={install_root}\\downloads\\radarr" in category_ini
    assert "Title=emulebb-sonarr" in category_ini
    assert f"Incoming={install_root}\\downloads\\sonarr" in category_ini
    assert (install_root / "downloads" / "prowlarr").is_dir()
    assert (install_root / "downloads" / "radarr").is_dir()
    assert (install_root / "downloads" / "sonarr").is_dir()
    for service_name in ("prowlarr", "radarr", "sonarr"):
        arr_config = (install_root / "data" / service_name / "config.xml").read_text(encoding="utf-8-sig")
        assert f"<BindAddress>{suite_config['services'][service_name]['bindAddress']}</BindAddress>" in arr_config
        assert f"<Port>{suite_config['services'][service_name]['port']}</Port>" in arr_config
        assert f"<ApiKey>{first_keys[service_name]}</ApiKey>" in arr_config
        assert "<AuthenticationMethod>Forms</AuthenticationMethod>" in arr_config
        assert "<AuthenticationRequired>Enabled</AuthenticationRequired>" in arr_config
        assert "<Username>admin</Username>" in arr_config
        assert f"<Password>{suite_password}</Password>" in arr_config

    credentials = (install_root / "credentials.txt").read_text(encoding="utf-8-sig")
    assert f"Password: {suite_password}" in credentials
    assert f"aMuTorrent password: {suite_password}" in credentials
    for service_name in ("emulebb", "prowlarr", "radarr", "sonarr"):
        assert first_keys[service_name] in credentials
    assert "Arr download client" in credentials
    assert f"Password: {first_keys['emulebb']}" in credentials
    credentials_html = (install_root / "credentials.html").read_text(encoding="utf-8-sig")
    assert "eMuleBB Suite Credentials" in credentials_html
    assert "Arr Download Client" in credentials_html
    assert "data-copy=" in credentials_html
    assert "http://127.0.0.1:" in credentials_html
    assert suite_password in credentials_html
    for key in first_keys.values():
        assert key in credentials_html

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
    assert refreshed_config["credentials"]["password"] == suite_password


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
    assert "credentials.html" in installer
    assert "if (-not $DryRun -and -not $NonInteractive)" in installer
    assert "Start-Process -FilePath (Join-Path $script:Root 'credentials.html')" in installer


def test_suite_bootstrapper_requires_emulebb_package_root() -> None:
    _assert_powershell_parse(Path.cwd() / BOOTSTRAPPER, cwd=Path.cwd())
    bootstrapper = BOOTSTRAPPER.read_text(encoding="utf-8")

    assert "eMuleBB/scripts/Install-eMuleBBSuite.ps1" in bootstrapper
    assert "eMule/scripts/Install-eMuleBBSuite.ps1" not in bootstrapper
    assert "Release ZIP does not contain eMuleBB/scripts/Install-eMuleBBSuite.ps1." in bootstrapper
    assert "Assert-FileHash" in bootstrapper
    assert "IncludePrerelease" in bootstrapper
    assert "EmulebbBindAddress" in bootstrapper
    assert "AmutorrentPort" in bootstrapper
    assert "AllowRemoteServiceBind" in bootstrapper
    assert "ReleaseBaseUrl" in bootstrapper
    assert "AmutorrentReleaseBaseUrl" in bootstrapper
    assert "EmulebbPackageZip" in bootstrapper
    assert "AmutorrentPackageZip" in bootstrapper
    assert "DependencyManifest" in bootstrapper
    assert "emulebb/amutorrent" in bootstrapper
    assert "emulebb-nightly-" in bootstrapper
    assert "Test-SupportedReleaseTag" in bootstrapper
    assert "Test-SupportedAmutorrentReleaseTag" in bootstrapper
    assert "& $installer @installerParams" in bootstrapper
    assert "& $installer @args" not in bootstrapper


@pytest.mark.parametrize(
    "version_arg",
    [
        "0.7.3-nightly.20260524.ae562c1",
        "emulebb-nightly-20260524-ae562c1",
    ],
)
def test_suite_bootstrapper_resolves_nightly_release_assets(version_arg: str) -> None:
    repo_root = Path.cwd()
    bootstrapper_path = (repo_root / BOOTSTRAPPER).resolve()
    command = rf"""
function Invoke-RestMethod {{
    param([string]$Uri, [hashtable]$Headers)
    if ($Uri -ne 'https://api.github.com/repos/emulebb/emulebb/releases/tags/emulebb-nightly-20260524-ae562c1') {{
        throw "Unexpected release URI: $Uri"
    }}
    return [pscustomobject]@{{
        tag_name = 'emulebb-nightly-20260524-ae562c1'
        draft = $false
        prerelease = $true
        assets = @(
            [pscustomobject]@{{
                name = 'emulebb-0.7.3-nightly.20260524.ae562c1-x64.zip'
                browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260524.ae562c1-x64.zip'
            }},
            [pscustomobject]@{{
                name = 'emulebb-0.7.3-nightly.20260524.ae562c1-x64.manifest.json'
                browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260524.ae562c1-x64.manifest.json'
            }}
        )
    }}
}}
& '{bootstrapper_path}' -Version '{version_arg}' -Platform x64 -Bundle Core -DryRun -NoStart
"""

    completed = _run_powershell(["-Command", command], cwd=repo_root)

    assert "Resolved release emulebb-nightly-20260524-ae562c1 for x64" in completed.stdout
    assert "emulebb-0.7.3-nightly.20260524.ae562c1-x64.zip" in completed.stdout
    assert (
        "-ReleaseBaseUrl https://github.com/emulebb/emulebb/releases/download/"
        "emulebb-nightly-20260524-ae562c1"
    ) in completed.stdout


def test_suite_bootstrapper_falls_back_to_nightly_when_only_legacy_stable_exists() -> None:
    repo_root = Path.cwd()
    bootstrapper_path = (repo_root / BOOTSTRAPPER).resolve()
    command = rf"""
function Invoke-RestMethod {{
    param([string]$Uri, [hashtable]$Headers)
    if ($Uri -eq 'https://api.github.com/repos/emulebb/amutorrent/releases') {{
        return @(
            [pscustomobject]@{{
                tag_name = 'amutorrent-nightly-20260604-9eff539e'
                draft = $false
                prerelease = $true
                assets = @(
                    [pscustomobject]@{{
                        name = 'emulebb-0.7.3-nightly.20260604.9eff539e-amutorrent-x64.zip'
                        browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.9eff539e-amutorrent-x64.zip'
                    }}
                )
            }}
        )
    }}
    if ($Uri -ne 'https://api.github.com/repos/emulebb/emulebb/releases') {{
        throw "Unexpected release URI: $Uri"
    }}
    return @(
        [pscustomobject]@{{
            tag_name = 'emulebb-nightly-20260604-5169162'
            draft = $false
            prerelease = $true
            assets = @(
                [pscustomobject]@{{
                    name = 'emulebb-0.7.3-nightly.20260604.5169162-x64.zip'
                    browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.5169162-x64.zip'
                }},
                [pscustomobject]@{{
                    name = 'emulebb-0.7.3-nightly.20260604.5169162-x64.manifest.json'
                    browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.5169162-x64.manifest.json'
                }}
            )
        }},
        [pscustomobject]@{{
            tag_name = 'eMule_v0.60d-broadband'
            draft = $false
            prerelease = $false
            assets = @()
        }}
    )
}}
& '{bootstrapper_path}' -Platform x64 -Bundle Core -DryRun -NoStart
"""

    completed = _run_powershell(["-Command", command], cwd=repo_root)

    assert "Resolved release emulebb-nightly-20260604-5169162 for x64" in completed.stdout
    assert "eMule_v0.60d-broadband" not in completed.stdout
    assert "emulebb-0.7.3-nightly.20260604.5169162-x64.zip" in completed.stdout


def test_suite_bootstrapper_hands_named_bundle_to_installer(tmp_path: Path) -> None:
    repo_root = Path.cwd()
    release_root = tmp_path / "release"
    captured_bundle = tmp_path / "captured-bundle.txt"
    installer_payload = f"""#Requires -Version 5.1
param(
    [ValidateSet('Core', 'Controller', 'Full')]
    [string]$Bundle = 'Full',
    [string]$InstallRoot,
    [string]$Version,
    [string]$Platform,
    [string]$ReleaseBaseUrl,
    [string]$AmutorrentVersion,
    [string]$AmutorrentReleaseBaseUrl,
    [switch]$NoStart
)
Set-Content -Encoding UTF8 -LiteralPath '{captured_bundle.as_posix()}' -Value $Bundle
""".encode("utf-8")
    package_zip = release_root / "emulebb-0.7.3-nightly.20260604.5169162-x64.zip"
    manifest = release_root / "emulebb-0.7.3-nightly.20260604.5169162-x64.manifest.json"
    suite_install_fixtures.write_zip(
        package_zip,
        {
            "eMuleBB/emulebb.exe": b"exe\n",
            "eMuleBB/scripts/Install-eMuleBBSuite.ps1": installer_payload,
        },
    )
    _write_manifest(manifest, package_zip)
    bootstrapper_path = (repo_root / BOOTSTRAPPER).resolve()
    command = rf"""
function Invoke-RestMethod {{
    param([string]$Uri, [hashtable]$Headers)
    if ($Uri -eq 'https://api.github.com/repos/emulebb/amutorrent/releases') {{
        return @(
            [pscustomobject]@{{
                tag_name = 'amutorrent-nightly-20260604-9eff539e'
                draft = $false
                prerelease = $true
                assets = @(
                    [pscustomobject]@{{
                        name = 'emulebb-0.7.3-nightly.20260604.9eff539e-amutorrent-x64.zip'
                        browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.9eff539e-amutorrent-x64.zip'
                    }},
                    [pscustomobject]@{{
                        name = 'emulebb-0.7.3-nightly.20260604.9eff539e-amutorrent-x64.manifest.json'
                        browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.9eff539e-amutorrent-x64.manifest.json'
                    }}
                )
            }}
        )
    }}
    if ($Uri -ne 'https://api.github.com/repos/emulebb/emulebb/releases') {{
        throw "Unexpected release URI: $Uri"
    }}
    return @(
        [pscustomobject]@{{
            tag_name = 'emulebb-nightly-20260604-5169162'
            draft = $false
            prerelease = $true
            assets = @(
                [pscustomobject]@{{
                    name = 'emulebb-0.7.3-nightly.20260604.5169162-x64.zip'
                    browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.5169162-x64.zip'
                }},
                [pscustomobject]@{{
                    name = 'emulebb-0.7.3-nightly.20260604.5169162-x64.manifest.json'
                    browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.5169162-x64.manifest.json'
                }}
            )
        }}
    )
}}
function Invoke-WebRequest {{
    param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile, [hashtable]$Headers)
    if ($Uri.EndsWith('.manifest.json')) {{
        Copy-Item -Force -LiteralPath '{manifest.as_posix()}' -Destination $OutFile
        return
    }}
    if ($Uri.EndsWith('.zip')) {{
        Copy-Item -Force -LiteralPath '{package_zip.as_posix()}' -Destination $OutFile
        return
    }}
    throw "Unexpected download URI: $Uri"
}}
& '{bootstrapper_path}' -Platform x64 -Bundle Full -NoStart
"""

    completed = _run_powershell(["-Command", command], cwd=repo_root)

    assert "Resolved release emulebb-nightly-20260604-5169162 for x64" in completed.stdout
    assert "Resolved aMuTorrent release amutorrent-nightly-20260604-9eff539e for Full suite" in completed.stdout
    assert captured_bundle.read_text(encoding="utf-8-sig").strip() == "Full"


def test_suite_bootstrapper_accepts_local_package_zip_overrides(tmp_path: Path) -> None:
    repo_root = Path.cwd()
    release_root = tmp_path / "release"
    captured = tmp_path / "captured.json"
    installer_payload = f"""#Requires -Version 5.1
param(
    [string]$Bundle,
    [string]$InstallRoot,
    [string]$Version,
    [string]$Platform,
    [string]$EmulebbPackageZip,
    [string]$EmulebbPackageManifest,
    [string]$AmutorrentVersion,
    [string]$AmutorrentPackageZip,
    [string]$AmutorrentPackageManifest,
    [string]$DependencyManifest,
    [switch]$NoStart
)
@{{
    bundle = $Bundle
    version = $Version
    platform = $Platform
    emulebbPackageZip = $EmulebbPackageZip
    emulebbPackageManifest = $EmulebbPackageManifest
    amutorrentVersion = $AmutorrentVersion
    amutorrentPackageZip = $AmutorrentPackageZip
    amutorrentPackageManifest = $AmutorrentPackageManifest
    dependencyManifest = $DependencyManifest
}} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath '{captured.as_posix()}'
""".encode("utf-8")
    package_zip = release_root / "emulebb-0.7.3-local.20260604-x64.zip"
    package_manifest = release_root / "emulebb-0.7.3-local.20260604-x64.manifest.json"
    amutorrent_zip = release_root / "emulebb-0.7.3-local.20260604-amutorrent-x64.zip"
    amutorrent_manifest = release_root / "emulebb-0.7.3-local.20260604-amutorrent-x64.manifest.json"
    dependency_manifest = release_root / "dependency-manifest.json"
    suite_install_fixtures.write_zip(
        package_zip,
        {
            "eMuleBB/emulebb.exe": b"exe\n",
            "eMuleBB/scripts/Install-eMuleBBSuite.ps1": installer_payload,
        },
    )
    suite_install_fixtures.write_manifest(package_manifest, package_zip)
    suite_install_fixtures.write_zip(amutorrent_zip, {"aMuTorrent/server/server.js": b"server\n"})
    suite_install_fixtures.write_manifest(amutorrent_manifest, amutorrent_zip)
    dependency_manifest.write_text("{}\n", encoding="utf-8")
    bootstrapper_path = (repo_root / BOOTSTRAPPER).resolve()
    command = rf"""
function Invoke-RestMethod {{
    throw 'GitHub API should not be called for local package overrides.'
}}
function Invoke-WebRequest {{
    throw 'Downloads should not be used for local package overrides.'
}}
& '{bootstrapper_path}' -Bundle Full -NoStart -EmulebbPackageZip '{package_zip.as_posix()}' -EmulebbPackageManifest '{package_manifest.as_posix()}' -AmutorrentPackageZip '{amutorrent_zip.as_posix()}' -AmutorrentPackageManifest '{amutorrent_manifest.as_posix()}' -DependencyManifest '{dependency_manifest.as_posix()}'
"""

    completed = _run_powershell(["-Command", command], cwd=repo_root)
    captured_payload = json.loads(captured.read_text(encoding="utf-8-sig"))

    assert "Resolved local eMuleBB package" in completed.stdout
    assert "Resolved local aMuTorrent package" in completed.stdout
    assert captured_payload["bundle"] == "Full"
    assert captured_payload["version"] == "0.7.3-local.20260604"
    assert captured_payload["platform"] == "x64"
    assert Path(captured_payload["emulebbPackageZip"]) == package_zip
    assert Path(captured_payload["emulebbPackageManifest"]) == package_manifest
    assert captured_payload["amutorrentVersion"] == "0.7.3-local.20260604"
    assert Path(captured_payload["amutorrentPackageZip"]) == amutorrent_zip
    assert Path(captured_payload["amutorrentPackageManifest"]) == amutorrent_manifest
    assert Path(captured_payload["dependencyManifest"]) == dependency_manifest


def test_suite_bootstrapper_noninteractive_full_requires_amutorrent_assets() -> None:
    repo_root = Path.cwd()
    bootstrapper_path = (repo_root / BOOTSTRAPPER).resolve()
    command = rf"""
function Invoke-RestMethod {{
    param([string]$Uri, [hashtable]$Headers)
    if ($Uri -eq 'https://api.github.com/repos/emulebb/amutorrent/releases') {{
        return @(
            [pscustomobject]@{{
                tag_name = 'amutorrent-nightly-20260604-9eff539e'
                draft = $false
                prerelease = $true
                assets = @(
                    [pscustomobject]@{{
                        name = 'emulebb-0.7.3-nightly.20260604.9eff539e-amutorrent-x64.zip'
                        browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.9eff539e-amutorrent-x64.zip'
                    }}
                )
            }}
        )
    }}
    if ($Uri -ne 'https://api.github.com/repos/emulebb/emulebb/releases') {{
        throw "Unexpected release URI: $Uri"
    }}
    return @(
        [pscustomobject]@{{
            tag_name = 'emulebb-nightly-20260604-5169162'
            draft = $false
            prerelease = $true
            assets = @(
                [pscustomobject]@{{
                    name = 'emulebb-0.7.3-nightly.20260604.5169162-x64.zip'
                    browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.5169162-x64.zip'
                }},
                [pscustomobject]@{{
                    name = 'emulebb-0.7.3-nightly.20260604.5169162-x64.manifest.json'
                    browser_download_url = 'https://example.invalid/emulebb-0.7.3-nightly.20260604.5169162-x64.manifest.json'
                }}
            )
        }}
    )
}}
& '{bootstrapper_path}' -Platform x64 -Bundle Full -IncludePrerelease -NonInteractive -NoStart -DryRun
"""

    completed = subprocess.run(
        [shutil.which("powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    output = " ".join(completed.stdout.split())
    assert completed.returncode != 0
    assert "aMuTorrent release amutorrent-nightly-20260604-9eff539e does not contain required Full asset(s)" in output
    assert "emulebb-0.7.3-nightly.20260604.9eff539e-amutorrent-x64.manifest.json" in output
    assert "publish a complete aMuTorrent release" in output


def test_suite_installer_rejects_positional_parameter_string_splat() -> None:
    repo_root = Path.cwd()
    installer_path = (repo_root / INSTALLER).resolve()
    command = rf"""
$installer = '{installer_path}'
$argv = @('-Bundle')
& $installer @argv
"""

    completed = subprocess.run(
        [shutil.which("powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode != 0
    assert "Install-eMuleBBSuite.ps1 was invoked with positional parameter strings" in completed.stdout
