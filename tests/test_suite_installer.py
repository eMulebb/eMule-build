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


def _read_ini_sections(path: Path, *, encoding: str = "utf-16") -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in path.read_text(encoding=encoding).splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = {}
            sections[stripped[1:-1]] = current
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        current[key.strip()] = value
    return sections


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
    assert suite_config["services"]["emulebb"]["clientHost"] == control_bind
    assert suite_config["services"]["emulebb"]["port"] == 14711
    assert suite_config["services"]["amutorrent"]["bindAddress"] == control_bind
    assert suite_config["services"]["amutorrent"]["clientHost"] == control_bind
    assert suite_config["credentials"]["username"] == "admin"
    assert re.fullmatch(r"[A-Za-z0-9]{24}", suite_config["credentials"]["password"])
    assert re.fullmatch(r"[A-Za-z0-9]{24}", suite_config["services"]["emulebb"]["apiKey"])
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
    assert install_manifest["services"]["emulebb"]["clientHost"] == control_bind
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
    assert 'target="_blank"' in credentials_html
    assert 'rel="noopener noreferrer"' in credentials_html
    assert 'data-copy="' in credentials_html
    assert suite_config["credentials"]["password"] in credentials_html
    assert suite_config["services"]["emulebb"]["apiKey"] in credentials_html

    start_emulebb = (install_root / "scripts" / "Start-eMuleBB.ps1").read_text(encoding="utf-8-sig")
    assert "apps\\eMuleBB" in start_emulebb
    assert "emulebbExecutableName" in start_emulebb
    assert "'emulebb.exe'" in start_emulebb
    assert "profiles\\emulebb" in start_emulebb
    assert "function Test-EmuleRunning" in start_emulebb
    assert "function Invoke-EmuleBootstrapFileDownload" in start_emulebb
    assert "function Ensure-EmuleBootstrapFiles" in start_emulebb
    assert "https://upd.emule-security.org/server.met" in start_emulebb
    assert "https://upd.emule-security.org/nodes.dat" in start_emulebb
    assert "$Name bootstrap file ready: $Destination" in start_emulebb
    assert "eMuleBB can still start, but first public connection may require manual server/node updates" in start_emulebb
    assert "function Show-EmuleLaunchReturnNotice" in start_emulebb
    assert "return to this PowerShell window so setup can complete the app registrations" in start_emulebb
    assert "Continuing in 6 seconds..." in start_emulebb
    assert "Start-Sleep -Seconds 6" in start_emulebb
    assert start_emulebb.index("Ensure-EmuleBootstrapFiles") < start_emulebb.index("Start-Process -FilePath $Emule")
    assert start_emulebb.index("Ensure-EmuleBootstrapFiles") < start_emulebb.index("Show-EmuleLaunchReturnNotice")
    assert start_emulebb.index("Show-EmuleLaunchReturnNotice") < start_emulebb.index("Start-Process -FilePath $Emule")
    assert "eMuleBB executable is missing" in start_emulebb
    assert "eMuleBB could not be started from" in start_emulebb
    assert "eMuleBB did not stay running after launch" in start_emulebb

    start_suite = (install_root / "scripts" / "Start-Suite.ps1").read_text(encoding="utf-8-sig")
    assert "suite-config.json" in start_suite
    assert "Start-eMuleBB.ps1" in start_suite
    suite_launch = start_suite.index("& (Join-Path $Root 'scripts\\Start-eMuleBB.ps1')", start_suite.index("$EmuleKey ="))
    assert "Show-EmuleLaunchReturnNotice" not in start_suite
    assert "function Initialize-AmutorrentConfig" in start_suite
    assert "$env:AMUTORRENT_DATA_DIR = Join-Path $Root 'data\\amutorrent'" in start_suite
    assert "Initialize-AmutorrentConfig -DataDir $env:AMUTORRENT_DATA_DIR" in start_suite
    assert "Set-ObjectProperty -Target $server -Name 'host' -Value $BindAddress" in start_suite
    assert "Set-ObjectProperty -Target $server -Name 'port' -Value $Port" in start_suite
    assert "Set-ObjectProperty -Target $auth -Name 'enabled' -Value $true" in start_suite
    assert "Set-ObjectProperty -Target $auth -Name 'adminUsername' -Value $Username" in start_suite
    assert "Set-ObjectProperty -Target $auth -Name 'password' -Value $Password" in start_suite
    assert "Get-ObjectPropertyValue -Target $auth -Name 'password'" not in start_suite
    assert "aMuTorrent config was not valid JSON" in start_suite
    assert "A fresh suite-managed config will be written." in start_suite
    assert "$env:EMULEBB_" not in start_suite
    assert "$env:BIND_ADDRESS" not in start_suite
    assert "$env:WEB_AUTH_" not in start_suite
    assert "$env:PORT" not in start_suite
    assert "$env:SKIP_SETUP_WIZARD" not in start_suite
    assert "/api/auth/status" in start_suite
    assert "Register-aMuTorrent.ps1" in start_suite
    assert "-EmulebbApiKey $EmuleKey" in start_suite
    assert "-AmutorrentUsername ([string]$Config.credentials.username)" in start_suite
    assert "-AmutorrentPassword ([string]$Config.credentials.password)" in start_suite
    assert "-AppProfileName 'eMuleBB Suite'" in start_suite
    assert "function Set-ArrHostCredentials" in start_suite
    assert "Set-ObjectProperty -Target $hostConfig -Name 'authenticationMethod' -Value 'forms'" in start_suite
    assert "Set-ObjectProperty -Target $hostConfig -Name 'authenticationRequired' -Value 'enabled'" in start_suite
    assert "Set-ObjectProperty -Target $hostConfig -Name 'username' -Value ([string]$Config.credentials.username)" in start_suite
    assert "Set-ObjectProperty -Target $hostConfig -Name 'password' -Value ([string]$Config.credentials.password)" in start_suite
    assert "$hostConfig.authenticationMethod = 'forms'" not in start_suite
    assert "Set-ArrHostCredentials -Name 'Prowlarr'" in start_suite
    assert "Set-ArrHostCredentials -Name 'Radarr'" in start_suite
    assert "Set-ArrHostCredentials -Name 'Sonarr'" in start_suite
    assert "function Get-HttpErrorDetail" in start_suite
    assert "function Get-ExceptionMessage" in start_suite
    assert "function Invoke-SuiteJsonApi" in start_suite
    assert "function Get-ServiceTroubleshootingHint" in start_suite
    assert "function Get-ServiceClientHost" in start_suite
    assert "Suite config is missing clientHost" in start_suite
    assert "clientHost for $ServiceName cannot be a wildcard address" in start_suite
    assert "Last error:" in start_suite
    assert "Timed out waiting for $Name at $Uri" in start_suite
    assert "Check $Root\\data\\radarr\\logs" in start_suite
    assert "Invoke-SuiteJsonApi -Name \"$Name web login update\"" in start_suite
    assert "Invoke-StepWithRetry -Name 'Arr web login setup'" in start_suite
    assert "function Ensure-ArrRootFolder" in start_suite
    assert "function Test-ArrRootFolderPath" in start_suite
    assert "function Test-ArrRootFolderCollection" in start_suite
    assert "$rootFolderUrl = \"$Url/$ApiPath/rootfolder\"" in start_suite
    assert "New-Item -ItemType Directory -Force -Path $Path" in start_suite
    assert "$createdRootFolder = Invoke-SuiteJsonApi -Name \"$Name root folder create\"" in start_suite
    assert "already configured as a root folder" in start_suite
    assert "Invoke-SuiteJsonApi -Name \"$Name root folder verify\"" in start_suite
    assert "did not persist root folder" in start_suite
    assert "Settings > Media Management > Root Folders" in start_suite
    assert "$RootFolder.PSObject.Properties['path']" in start_suite
    assert "Ensure-ArrRootFolder -Name 'Radarr'" in start_suite
    assert "Join-Path $Root 'media\\movies'" in start_suite
    assert "Ensure-ArrRootFolder -Name 'Sonarr'" in start_suite
    assert "Join-Path $Root 'media\\series'" in start_suite
    assert "Invoke-StepWithRetry -Name 'Radarr root folder setup'" in start_suite
    assert "Invoke-StepWithRetry -Name 'Sonarr root folder setup'" in start_suite
    assert "-EmulebbCategoryPath (Join-Path $Root 'downloads\\radarr')" in start_suite
    assert "-EmulebbCategoryPath (Join-Path $Root 'downloads\\sonarr')" in start_suite
    assert "function Start-ArrHost" in start_suite
    assert "$trayName = $Name + '.exe'" in start_suite
    assert "Missing Windows tray host" in start_suite
    assert "Start-ProcessIfMissing -Name $Name -FilePath $exe.FullName" in start_suite
    assert "Start-ProcessIfMissing -Name $Name -FilePath $exe.FullName -ArgumentList @('/data='" in start_suite
    assert "working directory is missing" in start_suite
    assert "could not be started from $FilePath" in start_suite
    assert "did not stay running after launch" in start_suite
    assert "function Ensure-EmuleBBAvailable" in start_suite
    assert "function Ensure-SuiteServicesAvailable" in start_suite
    assert "Wait-Json -Name 'aMuTorrent' -Uri \"$AmutorrentUrl/api/auth/status\"" in start_suite
    assert "Wait-Json -Name 'Prowlarr' -Uri \"$ProwlarrUrl/api/v1/system/status\" -Headers @{ 'X-Api-Key' = $ProwlarrKey }" in start_suite
    assert "Wait-Json -Name 'Radarr' -Uri \"$RadarrUrl/api/v3/system/status\" -Headers @{ 'X-Api-Key' = $RadarrKey }" in start_suite
    assert "Wait-Json -Name 'Sonarr' -Uri \"$SonarrUrl/api/v3/system/status\" -Headers @{ 'X-Api-Key' = $SonarrKey }" in start_suite
    assert "function Invoke-StepWithRetry" in start_suite
    assert "Ensure-SuiteServicesAvailable" in start_suite
    assert "Invoke-StepWithRetry -Name 'Sonarr registration'" in start_suite
    assert "-ProwlarrApiKey $ProwlarrKey" in start_suite
    assert "-RadarrApiKey $RadarrKey" in start_suite
    assert "-SonarrApiKey $SonarrKey" in start_suite
    assert "-SkipProwlarrSync" in start_suite
    assert "Invoke-StepWithRetry -Name 'Prowlarr application sync'" in start_suite
    assert "-SyncProwlarrOnly" in start_suite
    assert "Invoke-StepWithRetry -Name 'Radarr indexer verification'" in start_suite
    assert "Invoke-StepWithRetry -Name 'Sonarr indexer verification'" in start_suite
    assert "-VerifyIndexerOnly -Target Radarr" in start_suite
    assert "-VerifyIndexerOnly -Target Sonarr" in start_suite
    assert start_suite.index("Invoke-StepWithRetry -Name 'Arr web login setup'") < start_suite.index("Invoke-StepWithRetry -Name 'Radarr root folder setup'")
    assert start_suite.index("Invoke-StepWithRetry -Name 'Radarr root folder setup'") < start_suite.index("Invoke-StepWithRetry -Name 'Sonarr root folder setup'")
    assert start_suite.index("Invoke-StepWithRetry -Name 'Sonarr root folder setup'") < start_suite.index("Invoke-StepWithRetry -Name 'Prowlarr registration'")
    assert start_suite.index("Invoke-StepWithRetry -Name 'Radarr registration'") < start_suite.index("Invoke-StepWithRetry -Name 'Sonarr registration'")
    assert start_suite.index("Invoke-StepWithRetry -Name 'Sonarr registration'") < start_suite.index("Invoke-StepWithRetry -Name 'Prowlarr application sync'")
    assert start_suite.index("Invoke-StepWithRetry -Name 'Prowlarr application sync'") < start_suite.index("Invoke-StepWithRetry -Name 'Radarr indexer verification'")
    assert start_suite.index("Invoke-StepWithRetry -Name 'Radarr indexer verification'") < start_suite.index("Invoke-StepWithRetry -Name 'Sonarr indexer verification'")
    assert start_suite.index("foreach ($item in @(@('Prowlarr'") < start_suite.index("Initialize-AmutorrentConfig -DataDir $env:AMUTORRENT_DATA_DIR")
    assert start_suite.index("Initialize-AmutorrentConfig -DataDir $env:AMUTORRENT_DATA_DIR") < start_suite.index("Start-ProcessIfMissing -Name 'aMuTorrent' -FilePath $node")
    assert start_suite.index("Start-ProcessIfMissing -Name 'aMuTorrent' -FilePath $node") < start_suite.index("Invoke-StepWithRetry -Name 'aMuTorrent registration'")

    stop_suite = (install_root / "scripts" / "Stop-Suite.ps1").read_text(encoding="utf-8-sig")
    assert "Get-CimInstance Win32_Process" in stop_suite
    assert "apps\\aMuTorrent\\server\\server.js" in stop_suite
    assert "$Process.Name -eq 'node.exe'" in stop_suite
    assert "function Get-FirstSuiteExecutable" in stop_suite
    assert "Get-ChildItem -Path $appRoot -Filter $FileName -Recurse -File" in stop_suite
    assert "Get-FirstSuiteExecutable -RelativeRoot 'apps\\Prowlarr' -FileName 'Prowlarr.exe'" in stop_suite
    assert "StartsWith($Root" not in stop_suite
    assert "No eMuleBB Suite processes are running." in stop_suite
    assert "return" in stop_suite
    assert "exit 0" not in stop_suite
    assert "Stopping {0} (PID {1})" in stop_suite
    assert "eMuleBB Suite stop request completed." in stop_suite

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
    assert suite_config["services"]["emulebb"]["clientHost"] == "127.0.0.1"
    first_keys = {
        name: suite_config["services"][name]["apiKey"]
        for name in ("emulebb", "prowlarr", "radarr", "sonarr")
    }
    suite_password = suite_config["credentials"]["password"]
    assert re.fullmatch(r"[A-Za-z0-9]{24}", suite_password)
    for key in first_keys.values():
        assert re.fullmatch(r"[A-Za-z0-9]{24}", key)
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
    assert "SaveLogToDisk=1" in preferences
    assert "SaveDebugToDisk=" not in preferences
    assert "VerboseOptions=" not in preferences
    assert "Verbose=" not in preferences
    assert "FullVerbose=" not in preferences
    assert "MaxLogFileSize=" not in preferences
    assert "MaxLogBuff=" not in preferences
    assert "LogFileFormat=" not in preferences
    category_sections = _read_ini_sections(install_root / "profiles" / "emulebb" / "config" / "Category.ini")
    assert category_sections["General"]["Count"] == "3"
    categories_by_title = {
        section["Title"]: section
        for section in category_sections.values()
        if section.get("Title")
    }
    assert categories_by_title["emulebb-prowlarr"]["Incoming"] == f"{install_root}\\downloads\\prowlarr"
    assert categories_by_title["emulebb-radarr"]["Incoming"] == f"{install_root}\\downloads\\radarr"
    assert categories_by_title["emulebb-sonarr"]["Incoming"] == f"{install_root}\\downloads\\sonarr"
    assert (install_root / "downloads" / "prowlarr").is_dir()
    assert (install_root / "downloads" / "radarr").is_dir()
    assert (install_root / "downloads" / "sonarr").is_dir()
    for service_name in ("prowlarr", "radarr", "sonarr"):
        arr_config = (install_root / "data" / service_name / "config.xml").read_text(encoding="utf-8-sig")
        assert "<LogLevel>info</LogLevel>" in arr_config
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
    assert "Radarr/Sonarr download client" in credentials
    assert f"Password: {first_keys['emulebb']}" in credentials
    assert "First-run setup" in credentials
    assert "Run scripts\\Start-Suite.ps1 once before adding movies or series" in credentials
    assert "press Enter to use the default Register option" in credentials
    credentials_html = (install_root / "credentials.html").read_text(encoding="utf-8-sig")
    assert "eMuleBB Suite Credentials" in credentials_html
    assert "Radarr/Sonarr Download Client" in credentials_html
    assert "data-copy=" in credentials_html
    assert f"http://{suite_config['services']['emulebb']['clientHost']}:" in credentials_html
    assert 'target="_blank"' in credentials_html
    assert 'rel="noopener noreferrer"' in credentials_html
    assert "run scripts\\Start-Suite.ps1 once before adding movies or series" in credentials_html
    assert "press Enter to use the default Register option" in credentials_html
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
    assert "Initialize-AmutorrentConfig -DataDir `$env:AMUTORRENT_DATA_DIR -BindAddress ([string]`$Config.services.amutorrent.bindAddress)" in installer
    assert "Get-ServiceClientHost -ServiceName 'prowlarr' -Service `$Config.services.prowlarr" in installer
    assert "Get-ServiceClientHost -ServiceName 'radarr' -Service `$Config.services.radarr" in installer
    assert "Get-ServiceClientHost -ServiceName 'sonarr' -Service `$Config.services.sonarr" in installer
    assert "clientHost = ''" in installer
    assert "Resolve-ServiceClientHost" in installer
    assert "Set-SuiteClientHosts -Config $config" in installer
    assert "return '127.0.0.1'" not in installer
    assert "BlockNetworkWhenBindUnavailableAtStartup=0" in installer
    assert "NetworkGuardMode=Off" in installer
    assert "NetworkGuardAllowedCIDRs=" in installer
    assert "Get-DefaultControlBindAddress" in installer
    assert "Get-AutoLanBindAddress" in installer
    assert "Test-AutoLanIPv4Address" in installer
    assert "$bytes[0] -eq 10" in installer
    assert "$bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31" in installer
    assert "$bytes[0] -eq 192 -and $bytes[1] -eq 168" in installer
    assert "function ConvertTo-IPv4SubnetMask" in installer
    assert "function Test-VirtualLikeInterfaceName" in installer
    assert "function Get-AutoLanCandidateRank" in installer
    assert "Get-NetAdapter -ErrorAction Stop" in installer
    assert "IsVirtualLike = [bool](Test-VirtualLikeInterfaceName -Name $interfaceText)" in installer
    assert "Get-AutoLanCandidateRank -Candidate $_" in installer
    assert "'vethernet'" in installer
    assert "'default switch'" in installer
    assert "'hyper-v'" in installer
    assert "'vmware'" in installer
    assert "'virtualbox'" in installer
    assert "'bluetooth'" in installer
    assert "function Get-BindableInterfaceOptions" in installer
    assert "Any interface (no P2P bind)" in installer
    assert "P2P bind interface: Any interface (no bind; OS-selected route)" in installer
    assert "No P2P bind" not in installer
    assert "P2P bind interface: none" not in installer
    assert "' [VPN-like]'" in installer
    assert "InterfaceAlias = [string]$info.InterfaceAlias" in installer
    assert "Label = ('{0} - {1}{2}{3}{4}'" in installer
    assert "'hide.me'" in installer
    assert "X_LOCAL_IP" not in installer
    assert "Default local bind" not in installer
    assert "Detected LAN/VPN bind" in installer
    assert "Non-loopback control-service bind detected" not in installer
    assert "Allow remote control-service bind" not in installer
    assert "Back to service binds" not in installer
    assert "bind address $Address is not loopback" not in installer
    assert "will bind to non-loopback address $Address" not in installer
    assert "bind address $Address exposes the service" not in installer
    assert "will bind to all interfaces" not in installer


def test_suite_installer_recomputes_client_host_when_bind_changes(tmp_path: Path) -> None:
    config_path = tmp_path / "suite-config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": "emulebb.suite-config.v1",
                "bundle": "Core",
                "installRoot": r"C:\SuiteProbe",
                "services": {
                    name: {
                        "bindAddress": "192.168.1.10",
                        "clientHost": "192.168.1.10",
                        "port": port,
                        **({"apiKey": ""} if name in {"emulebb", "prowlarr", "radarr", "sonarr"} else {}),
                    }
                    for name, port in {
                        "emulebb": 54002,
                        "amutorrent": 54003,
                        "prowlarr": 54004,
                        "radarr": 54005,
                        "sonarr": 54006,
                    }.items()
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = suite_install_fixtures.run_installer(
        (Path.cwd() / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-DryRun",
            "-ConfigFile",
            str(config_path),
            "-ControlBindAddress",
            "127.0.0.1",
            "-EmulebbPort",
            "54002",
        ],
        cwd=Path.cwd(),
    )

    assert "emulebb: 127.0.0.1:54002" in completed.stdout
    assert "client URL host: 192.168.1.10" not in completed.stdout


def test_suite_installer_rejects_stale_wildcard_client_host(tmp_path: Path) -> None:
    config_path = tmp_path / "suite-config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": "emulebb.suite-config.v1",
                "bundle": "Core",
                "installRoot": r"C:\SuiteProbe",
                "services": {
                    name: {
                        "bindAddress": "0.0.0.0",
                        "clientHost": "203.0.113.55",
                        "port": port,
                        **({"apiKey": ""} if name in {"emulebb", "prowlarr", "radarr", "sonarr"} else {}),
                    }
                    for name, port in {
                        "emulebb": 54002,
                        "amutorrent": 54003,
                        "prowlarr": 54004,
                        "radarr": 54005,
                        "sonarr": 54006,
                    }.items()
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = suite_install_fixtures.run_installer(
        (Path.cwd() / INSTALLER).resolve(),
        [
            "-NonInteractive",
            "-DryRun",
            "-ConfigFile",
            str(config_path),
        ],
        cwd=Path.cwd(),
        check=False,
    )

    assert completed.returncode != 0
    assert "clientHost 203.0.113.55 is not a local IPv4 address" in completed.stdout
    assert "set services.emulebb.clientHost to a current LAN/VPN IP" in completed.stdout


def test_suite_installer_preserves_app_roots_when_extracting_multiple_packages() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "$extractRoot = Join-Path $downloadRoot (\"extract-$Name\")" in installer
    assert "$extractedPackageRoot = Join-Path $extractRoot $Name" in installer
    assert "$targetPackageRoot = Join-Path $Destination $Name" in installer
    assert "Move-Item -LiteralPath $extractedPackageRoot -Destination $targetPackageRoot" in installer


def test_suite_installer_requires_hashed_pinned_dependencies() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "function Read-JsonFile" in installer
    assert "$Description is not valid JSON: $Path" in installer
    assert "Fix or regenerate this file, then rerun scripts\\Install-eMuleBBSuite.ps1." in installer
    assert "Read-JsonFile -Path $ConfigFile -Description 'ConfigFile'" in installer
    assert "Read-JsonFile -Path $ManifestPath -Description 'DependencyManifest'" in installer
    assert "9d388c476edfe579439830dc87f05fc50c86fa0dce80802726832c72088e731b" in installer
    assert "cc4fdffc4a82a3805e53aa9c016749fd17247eb21dd6764b1b53ced471695bb7" in installer
    assert "19a81e69dedd8d317b5fa8a1a9c48d63bc3b3f3ba87b84c94ff6d75b1803e419" in installer
    assert "Latest dependency resolution requires -DependencyManifest entries with exact URLs and SHA256 hashes." in installer
    assert "DependencyChannel Latest requires -DependencyManifest with exact URLs and SHA256 hashes." in installer
    assert "Latest dependency releases are unavailable unless you pass -DependencyManifest." in installer
    assert "$Name dependency download requires a SHA256 hash." in installer
    assert "function Get-DependencyDownloadRecoveryMessage" in installer
    assert "pass -DependencyManifest with reachable file paths or URLs and SHA256 hashes" in installer
    assert "Failed to download $Url -> $Destination. $($_.Exception.Message) $(Get-DependencyDownloadRecoveryMessage)" in installer
    assert "Downloading $Name dependency $assetName" in installer
    assert "Verifying $Name dependency" in installer
    assert "Extracting $Name dependency" in installer
    assert "Downloading Node runtime $($nodeSpec.FileName)" in installer
    assert "Verifying Node runtime" in installer
    assert "Extracting Node runtime" in installer


def test_suite_arr_registration_defers_prowlarr_sync_until_all_apps_are_saved() -> None:
    script_path = Path("emule_workspace/release_assets/emulebb/scripts/Register-ArrStack.ps1")
    _assert_powershell_parse(Path.cwd() / script_path, cwd=Path.cwd())
    register_arr_stack = script_path.read_text(encoding="utf-8")

    assert "example http://127.0.0.1" not in register_arr_stack
    assert "example http://LAN-IP:4711" in register_arr_stack
    assert "example http://LAN-IP:9696" in register_arr_stack
    assert "example http://LAN-IP:7878" in register_arr_stack
    assert "example http://LAN-IP:8989" in register_arr_stack
    assert "[switch]$SkipProwlarrSync" in register_arr_stack
    assert "[switch]$SyncProwlarrOnly" in register_arr_stack
    assert "function Get-ArrUrlPrompt" in register_arr_stack
    assert "function Get-HttpErrorDetail" in register_arr_stack
    assert "function Get-ExceptionMessage" in register_arr_stack
    assert "Get-ExceptionMessage -Exception $_.Exception" in register_arr_stack
    assert "Arr API key was rejected by $uri." in register_arr_stack
    assert "Copy the API key from Settings > General in the matching Radarr/Sonarr web UI" in register_arr_stack
    assert "function Test-ApiKeyRejectedError" in register_arr_stack
    assert "if (Test-ApiKeyRejectedError -Exception $_.Exception)" in register_arr_stack
    assert "function Read-RequiredSecretValue" in register_arr_stack
    assert "-AsSecureString" not in register_arr_stack
    assert "return Normalize-ArgumentValue -Value (Read-Host $Prompt)" in register_arr_stack
    assert "[scriptblock]$OnRetry = $null" in register_arr_stack
    assert "\nexit " not in register_arr_stack
    assert 'throw "$Name cancelled by user."' in register_arr_stack
    assert "$script:EmulebbBaseUrl = ''" in register_arr_stack
    assert "$script:ProwlarrUrl = ''" in register_arr_stack
    assert "$script:targetUrl = ''" in register_arr_stack
    assert "function Get-ProwlarrCommandFailureDetail" in register_arr_stack
    assert "Prowlarr application sync failed: {0}. {1}" in register_arr_stack
    assert "function Save-ArrProwlarrIndexer" in register_arr_stack
    assert "function Save-ProwlarrQbitClient" in register_arr_stack
    assert "Run-TargetWithRetry -Name 'Prowlarr download client registration'" in register_arr_stack
    assert "/api/v1/downloadclient?forceSave=true" in register_arr_stack
    assert "[switch]$VerifyIndexerOnly" in register_arr_stack
    assert "function Get-ArrProwlarrIndexerName" in register_arr_stack
    assert "function Get-ExistingArrIndexers" in register_arr_stack
    assert "function Remove-DuplicateArrIndexers" in register_arr_stack
    assert "function Get-ArrIndexerCategories" in register_arr_stack
    assert "Prowlarr indexer '$Name' is not registered. Run Register-Prowlarr.ps1 first" in register_arr_stack
    assert "Prowlarr URL for indexer verification (example http://LAN-IP:9696)" in register_arr_stack
    assert "First-time setup or repair: press Enter to register. Choose U only to remove this Arr integration." in register_arr_stack
    assert "Run-TargetWithRetry -Name \"$Target indexer verification\"" in register_arr_stack
    assert "/api/v3/indexer?forceSave=true" in register_arr_stack
    assert "/api/v3/indexer/{0}?forceSave=true" in register_arr_stack
    assert "Set-ProviderField -Provider $payload -Name 'apiKey' -Value $ProwlarrKey" in register_arr_stack
    assert "Set-ProviderField -Provider $payload -Name 'categories' -Value (Get-ArrIndexerCategories -Kind $Kind)" in register_arr_stack
    assert "Set-ProviderField -Provider $payload -Name 'syncCategories' -Value (Get-ArrIndexerCategories -Kind $Kind) -Optional" in register_arr_stack
    assert "Read-RequiredSecretValue -Prompt 'Prowlarr API key' -Value $script:ProwlarrApiKey -Name 'ProwlarrApiKey'" in register_arr_stack
    assert "Read-RequiredSecretValue -Prompt 'eMuleBB API key' -Value $script:EmulebbApiKey -Name 'EmulebbApiKey'" in register_arr_stack
    assert "Read-RequiredSecretValue -Prompt \"$Target API key\" -Value $script:targetApiKey -Name (\"${Target}ApiKey\")" in register_arr_stack
    assert "$script:EmulebbBaseUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue" in register_arr_stack
    assert "$script:targetUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue" in register_arr_stack
    assert "$script:targetUrl = Normalize-ArgumentValue -Value $RadarrUrl" in register_arr_stack
    assert "$script:targetUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue" in register_arr_stack
    assert register_arr_stack.index("Run-TargetWithRetry -Name 'eMuleBB category registration'") < register_arr_stack.index("$script:EmulebbBaseUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue")
    assert register_arr_stack.index("Run-TargetWithRetry -Name \"Prowlarr $Target application registration\"") < register_arr_stack.index("Run-TargetWithRetry -Name 'Prowlarr download client registration'")
    assert register_arr_stack.index("Run-TargetWithRetry -Name (\"$Target download client {0}\"") < register_arr_stack.index("$script:targetUrl = Normalize-HttpBaseUrl -Value (Read-RequiredValue", register_arr_stack.index("Run-TargetWithRetry -Name (\"$Target download client {0}\""))
    assert "Set-ProviderField -Provider $payload -Name 'password' -Value $EmuleApiKey" in register_arr_stack
    assert "Set-ProviderField -Provider $payload -Name 'apiKey' -Value $ArrKey" in register_arr_stack
    assert "if ($SyncProwlarrOnly)" in register_arr_stack
    assert "if ($VerifyIndexerOnly)" in register_arr_stack
    assert "Read-RequiredValue -Prompt 'Prowlarr URL for application sync (example http://LAN-IP:9696)'" in register_arr_stack
    assert "throw 'ProwlarrUrl is required for -SyncProwlarrOnly.'" not in register_arr_stack
    assert register_arr_stack.index("if ($SyncProwlarrOnly)") < register_arr_stack.index("$ProwlarrUrl = Read-OptionalValue")
    assert register_arr_stack.index("if ($VerifyIndexerOnly)") < register_arr_stack.index("$ProwlarrUrl = Read-OptionalValue")
    assert "if ($ProwlarrUrl -and -not $SkipProwlarrSync)" in register_arr_stack
    assert "$ProwlarrUrl = Normalize-HttpBaseUrl -Value $ProwlarrUrl" not in register_arr_stack
    assert register_arr_stack.index("if ($ProwlarrUrl -and -not $SkipProwlarrSync)") < register_arr_stack.rindex("Run-TargetWithRetry -Name \"$Target indexer verification\"")


def test_suite_prowlarr_registration_requires_and_passes_api_keys() -> None:
    script_path = Path("emule_workspace/release_assets/emulebb/scripts/Register-Prowlarr.ps1")
    _assert_powershell_parse(Path.cwd() / script_path, cwd=Path.cwd())
    register_prowlarr = script_path.read_text(encoding="utf-8")

    assert "example http://127.0.0.1" not in register_prowlarr
    assert "example http://LAN-IP:9696" in register_prowlarr
    assert "example http://LAN-IP:4711" in register_prowlarr
    assert "function Get-HttpErrorDetail" in register_prowlarr
    assert "function Get-ExceptionMessage" in register_prowlarr
    assert "Get-ExceptionMessage -Exception $_.Exception" in register_prowlarr
    assert "Prowlarr API key was rejected by $uri." in register_prowlarr
    assert "Copy the API key from Settings > General in the Prowlarr web UI" in register_prowlarr
    assert "function Read-RequiredSecretValue" in register_prowlarr
    assert "-AsSecureString" not in register_prowlarr
    assert "return Normalize-ArgumentValue -Value (Read-Host $Prompt)" in register_prowlarr
    assert "\nexit " not in register_prowlarr
    assert "if ($NoRetry) {" in register_prowlarr
    assert 'throw "$Action cancelled by user."' in register_prowlarr
    assert "Read-RequiredSecretValue -Prompt 'Prowlarr API key' -Value $ProwlarrApiKey -Name 'ProwlarrApiKey'" in register_prowlarr
    assert "Read-RequiredSecretValue -Prompt 'eMuleBB API key' -Value $EmulebbApiKey -Name 'EmulebbApiKey'" in register_prowlarr
    assert "$EmulebbBaseUrl = ''" in register_prowlarr
    assert "$EmulebbApiKey = ''" in register_prowlarr
    assert "Set-ProviderField -Provider $payload -Name 'apiKey' -Value $TorznabApiKey" in register_prowlarr
    assert "First-time setup or repair: press Enter to register. Choose U only to remove this Prowlarr indexer." in register_prowlarr


def test_suite_amutorrent_registration_repairs_stale_env_owned_clients() -> None:
    script_path = Path("emule_workspace/release_assets/emulebb/scripts/Register-aMuTorrent.ps1")
    _assert_powershell_parse(Path.cwd() / script_path, cwd=Path.cwd())
    register_amutorrent = script_path.read_text(encoding="utf-8")

    assert "example http://127.0.0.1" not in register_amutorrent
    assert "example http://LAN-IP:4000" in register_amutorrent
    assert "example http://LAN-IP:4711" in register_amutorrent
    assert "function Read-RequiredSecretValue" in register_amutorrent
    assert "function Get-HttpErrorDetail" in register_amutorrent
    assert "function Get-ExceptionMessage" in register_amutorrent
    assert "aMuTorrent request failed at $uri" in register_amutorrent
    assert "Get-ExceptionMessage -Exception $_.Exception" in register_amutorrent
    assert "-AsSecureString" not in register_amutorrent
    assert "return Normalize-ArgumentValue -Value (Read-Host $Prompt)" in register_amutorrent
    assert "First-time setup or repair: press Enter to register/repair. Choose U only to remove this aMuTorrent client." in register_amutorrent
    assert "[switch]$PromptWhenBlank" in register_amutorrent
    assert "\nexit " not in register_amutorrent
    assert 'throw "$Name cancelled by user."' in register_amutorrent
    assert "$script:AmutorrentApiKeyWasProvided = $PSBoundParameters.ContainsKey('AmutorrentApiKey')" in register_amutorrent
    assert "-PromptWhenBlank:(-not $script:AmutorrentApiKeyWasProvided)" in register_amutorrent
    assert "[scriptblock]$OnRetry = $null" in register_amutorrent
    assert "$script:AmutorrentUrl = ''" in register_amutorrent
    assert "$script:AmutorrentWebSession = $null" in register_amutorrent
    assert "Read-RequiredSecretValue -Prompt 'eMuleBB API key' -Value $script:EmulebbApiKey -Name 'EmulebbApiKey'" in register_amutorrent
    assert "function Test-ClientHasActiveEnvField" in register_amutorrent
    assert "function Remove-StaleEnvOwnedEmulebbClients" in register_amutorrent
    assert "$clients = Remove-StaleEnvOwnedEmulebbClients -Clients $clients" in register_amutorrent
    assert "Remove-PropertyIfPresent -Target $Client -Name 'source'" in register_amutorrent
    assert "Test-ClientHasActiveEnvField -Client $clients[$index]" in register_amutorrent


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
    assert "function Get-ServiceClientHost" in installer
    assert "function Read-WizardPortValue" in installer
    assert "Enter a number from 0 to 65535. Use 0 to auto-select a free suite port." in installer
    assert "eMuleBB is already running" in installer
    assert "function Test-EmuleRunning" in installer
    assert "eMuleBB executable is missing" in installer
    assert "eMuleBB could not be started from" in installer
    assert "eMuleBB did not stay running after launch" in installer
    assert "Start-ProcessIfMissing -Name 'aMuTorrent' -FilePath `$node" in installer
    assert "working directory is missing" in installer
    assert "could not be started from `$FilePath" in installer
    assert "function Get-FirstSuiteExecutable" in installer
    assert installer.index("`$nodeMatch = Get-ChildItem -Path (Join-Path `$Root 'runtime\\node')") < installer.index("`$node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source")
    assert "Start skipped because -NoStart was used" in installer
    assert "credentials.html" in installer
    assert "if (-not $DryRun -and -not $NonInteractive)" in installer
    assert "Start-Process -FilePath (Join-Path $script:Root 'credentials.html')" in installer
    assert "must be exactly 24 alphanumeric characters, or blank to generate a new key." in installer
    assert "function Assert-InstallRootValue" in installer
    assert "InstallRoot is required. Pass -InstallRoot C:\\eMuleBBSuite" in installer
    assert "InstallRoot contains characters Windows cannot use in folder names" in installer
    assert "InstallRoot must be an absolute drive path" in installer
    assert "[IO.Path]::IsPathRooted($Path)" in installer
    assert "InstallRoot is not a valid Windows path" in installer
    assert "function Enable-Tls12" in installer
    assert "[Net.SecurityProtocolType]::Tls12" in installer
    assert "Choose a short folder such as C:\\eMuleBBSuite or C:\\eMuleBB" in installer
    assert "InstallRoot already exists:" in installer
    assert "Choose a different -InstallRoot" in installer
    assert "function Invoke-HttpDownload" in installer
    assert "Write-Progress -Activity $activity -Status $status -PercentComplete $percent" in installer
    assert "Downloaded {0}" in installer
    assert "$ProgressPreference = 'SilentlyContinue'" not in installer


def test_suite_windows_system_helpers_explain_admin_requirement() -> None:
    for script_name, expected in {
        "Enable-LongPaths.ps1": "Windows long-path enable requires an elevated PowerShell window.",
        "Repair-Firewall.ps1": "Windows Firewall repair requires an elevated PowerShell window.",
        "Set-DefenderExclusions.ps1": "Microsoft Defender exclusion updates require an elevated PowerShell window.",
    }.items():
        script_path = Path("emule_workspace/release_assets/emulebb/scripts") / script_name
        _assert_powershell_parse(Path.cwd() / script_path, cwd=Path.cwd())
        script = script_path.read_text(encoding="utf-8")
        assert "function Assert-Administrator" in script
        assert "WindowsBuiltInRole]::Administrator" in script
        assert "Run as administrator" in script
        assert expected in script


def test_suite_bootstrapper_requires_emulebb_package_root() -> None:
    _assert_powershell_parse(Path.cwd() / BOOTSTRAPPER, cwd=Path.cwd())
    bootstrapper = BOOTSTRAPPER.read_text(encoding="utf-8")

    assert "eMuleBB/scripts/Install-eMuleBBSuite.ps1" in bootstrapper
    assert "eMule/scripts/Install-eMuleBBSuite.ps1" not in bootstrapper
    assert "Release ZIP does not contain eMuleBB/scripts/Install-eMuleBBSuite.ps1." in bootstrapper
    assert "Assert-FileHash" in bootstrapper
    assert "function Assert-RequiredSha256" in bootstrapper
    assert "$Description must include a SHA256 hash." in bootstrapper
    assert "Assert-RequiredSha256 -Value ([string]$manifest.sha256) -Description 'Downloaded eMuleBB release manifest'" in bootstrapper
    assert "IncludePrerelease" in bootstrapper
    assert "EmulebbBindAddress" in bootstrapper
    assert "AmutorrentPort" in bootstrapper
    assert "AllowRemoteServiceBind" in bootstrapper
    assert "ReleaseBaseUrl" in bootstrapper
    assert "AmutorrentReleaseBaseUrl" in bootstrapper
    assert "EmulebbPackageZip" in bootstrapper
    assert "AmutorrentPackageZip" in bootstrapper
    assert "DependencyManifest" in bootstrapper
    assert "function Enable-Tls12" in bootstrapper
    assert "[Net.SecurityProtocolType]::Tls12" in bootstrapper
    assert "[ValidateRange(0, 65535)]" in bootstrapper
    assert "[ValidateRange(1, 65535)]" not in bootstrapper
    assert "function Invoke-GitHubApi" in bootstrapper
    assert "function Read-JsonFile" in bootstrapper
    assert "Download or regenerate this file, then rerun the bootstrapper." in bootstrapper
    assert 'Read-JsonFile -Path $resolvedManifest -Description "$Name local package manifest"' in bootstrapper
    assert "Read-JsonFile -Path $manifestPath -Description 'Downloaded eMuleBB release manifest'" in bootstrapper
    assert "download the package assets in a browser from GitHub Releases" in bootstrapper
    assert "https://github.com/emulebb/emulebb/releases" in bootstrapper
    assert "https://github.com/emulebb/amutorrent/releases" in bootstrapper
    assert "-EmulebbPackageZip" in bootstrapper
    assert "-AmutorrentPackageZip" in bootstrapper
    assert "emulebb/amutorrent" in bootstrapper
    assert "emulebb-nightly-" in bootstrapper
    assert "Test-SupportedReleaseTag" in bootstrapper
    assert "Test-SupportedAmutorrentReleaseTag" in bootstrapper
    assert "& $installer @installerParams" in bootstrapper
    assert "& $installer @args" not in bootstrapper
    assert "function Invoke-HttpDownload" in bootstrapper
    assert "Write-Progress -Activity $activity -Status $status -PercentComplete $percent" in bootstrapper
    assert "Downloaded {0}" in bootstrapper
    assert "$ProgressPreference = 'SilentlyContinue'" not in bootstrapper


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


@pytest.mark.parametrize("pass_install_root", [False, True])
def test_suite_bootstrapper_hands_resolved_install_root_to_installer(tmp_path: Path, pass_install_root: bool) -> None:
    repo_root = Path.cwd()
    release_root = tmp_path / "release"
    captured = tmp_path / "captured-install-root.json"
    installer_payload = f"""#Requires -Version 5.1
param(
    [string]$Bundle,
    [string]$InstallRoot,
    [string]$Version,
    [string]$Platform,
    [string]$EmulebbPackageZip,
    [string]$EmulebbPackageManifest,
    [switch]$NoStart
)
@{{
    hasInstallRoot = $PSBoundParameters.ContainsKey('InstallRoot')
    installRoot = $InstallRoot
}} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath '{captured.as_posix()}'
""".encode("utf-8")
    package_zip = release_root / "emulebb-0.7.3-local.20260604-x64.zip"
    package_manifest = release_root / "emulebb-0.7.3-local.20260604-x64.manifest.json"
    suite_install_fixtures.write_zip(
        package_zip,
        {
            "eMuleBB/emulebb.exe": b"exe\n",
            "eMuleBB/scripts/Install-eMuleBBSuite.ps1": installer_payload,
        },
    )
    suite_install_fixtures.write_manifest(package_manifest, package_zip)

    bootstrapper_path = (repo_root / BOOTSTRAPPER).resolve()
    command = [
        "-File",
        str(bootstrapper_path),
        "-Bundle",
        "Core",
        "-NoStart",
        "-EmulebbPackageZip",
        str(package_zip),
        "-EmulebbPackageManifest",
        str(package_manifest),
    ]
    if pass_install_root:
        command.extend(["-InstallRoot", r"C:\SuiteSample"])

    _run_powershell(command, cwd=repo_root)
    captured_payload = json.loads(captured.read_text(encoding="utf-8-sig"))

    assert captured_payload["hasInstallRoot"] is True
    if pass_install_root:
        assert captured_payload["installRoot"] == r"C:\SuiteSample"
    else:
        assert captured_payload["installRoot"] == r"C:\eMuleBBSuite"


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
