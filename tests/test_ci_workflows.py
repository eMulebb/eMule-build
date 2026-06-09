from __future__ import annotations

from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    return _repo_root().parents[1]


def _app_workflow(name: str) -> Path:
    return _workspace_root() / "workspaces" / "workspace" / "app" / "emulebb-main" / ".github" / "workflows" / name


def _amutorrent_workflow(name: str) -> Path:
    return _workspace_root() / "repos" / "amutorrent" / ".github" / "workflows" / name


def _read_app_workflow(name: str) -> str:
    workflow = _app_workflow(name)
    if not workflow.is_file():
        pytest.skip(f"app workflow is not available in this checkout: {workflow}")
    return workflow.read_text(encoding="utf-8")


def _read_amutorrent_workflow(name: str) -> str:
    workflow = _amutorrent_workflow(name)
    if not workflow.is_file():
        pytest.skip(f"aMuTorrent workflow is not available in this checkout: {workflow}")
    return workflow.read_text(encoding="utf-8")


def test_reusable_workspace_command_owns_materialized_ci_setup() -> None:
    workflow = _repo_root() / ".github" / "workflows" / "reusable-workspace-command.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "workflow_call:" in text
    assert "EMULEBB_WORKSPACE_ROOT: ${{ github.workspace }}" in text
    assert r"EMULEBB_WORKSPACE_OUTPUT_ROOT: ${{ runner.temp }}\emulebb-output" in text
    assert "python -m emule_workspace materialize" in text
    assert "python -m emule_workspace audit-artifacts" in text
    assert "materialize --workspace-root" not in text
    assert (
        "python -m pip install \"click>=8.1\" \"pydantic>=2.0\" \"jinja2>=3\" "
        "\"jsonschema>=4\" \"PyYAML>=6\" \"pywin32\" \"pywinauto\""
    ) in text
    assert "Reset-RepoRef" in text
    assert "[string]$Ref" in text
    assert "$PSNativeCommandUseErrorActionPreference = $true" in text
    assert "repos\\amutorrent" in text
    assert "workspaces\\workspace\\app\\emulebb-main" in text


def test_reusable_workspace_command_keeps_hyperv_local_only() -> None:
    workflow = _repo_root() / ".github" / "workflows" / "reusable-workspace-command.yml"
    text = workflow.read_text(encoding="utf-8").lower()

    assert "hyper-v" not in text
    assert "hyperv" not in text
    assert "windows-vm" not in text


def test_build_baseline_uses_supported_reusable_inputs() -> None:
    workflow = _repo_root() / ".github" / "workflows" / "baseline.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "uses: emulebb/emulebb-tooling/.github/workflows/reusable-baseline.yml@main" in text
    assert "repo_kind: emulebb-build" in text
    assert "extra_step_script:" not in text
    assert "extra_commands:" in text
    assert "python -m pip install -e .[dev]" in text
    assert "python -m pytest tests/test_ci_workflows.py" in text


def test_controlled_smoke_uses_reusable_core_offline_and_lan_suite() -> None:
    text = _read_app_workflow("controlled-smoke.yml")

    assert "workflow_dispatch:" in text
    assert 'cron: "47 5 * * *"' in text
    assert "uses: emulebb/emulebb-build/.github/workflows/reusable-workspace-command.yml@main" in text
    assert "runs_on: ${{ matrix.runner.label }}" in text
    assert "label: windows-2022" in text
    assert "runs_on: windows-11-arm" in text
    assert "label: windows-2025-vs2026" not in text
    assert "Hosted runner: windows-2022 with v143 ATL/MFC policy" in text
    assert "Hosted runner: windows-11-arm" in text
    assert 'node_version: "24"' in text
    assert "app_ref: ${{ github.sha }}" in text
    assert "timeout_minutes: 360" in text
    assert "python -m emule_workspace package-release" in text
    assert "python -m emule_workspace package-amutorrent" in text
    assert "python -m emule_workspace build app" in text
    assert "python -m emule_workspace package-release `\n          --workspace-root" not in text
    assert "python -m emule_workspace package-amutorrent `\n          --workspace-root" not in text
    assert "python -m emule_workspace build app `\n          --workspace-root" not in text
    assert "--variant tracing-harness" in text
    assert "tmp\\ci\\live-wire-inputs.ci.json" in text
    assert "local_package_install" in text
    assert "Get-NetAdapter" in text
    assert "--materialize-test-install" in text
    assert "--materialize-test-install-skip-build" in text
    assert "--live-wire-inputs-file $ciLiveWireInputs" in text
    assert "--suite command-line-smoke" in text
    assert "--test-network offline" in text
    assert "--suite deterministic-two-client-transfer" in text
    assert "--test-network lan" in text
    assert "--platform ARM64" in text
    assert "Expand-Archive -LiteralPath $packageZip" in text
    assert r"scripts\command-line-smoke.py" in text
    assert "Release ARM64 eMuleBB package" in text
    assert "ARM64 offline command-line smoke" in text
    assert r"${{ runner.temp }}\emulebb-output\reports\command-line-smoke\**" in text
    assert r"${{ runner.temp }}\emulebb-output\artifacts\command-line-smoke\**" in text
    assert r"${{ runner.temp }}\emulebb-output\reports\live-e2e-suite\**" in text
    assert r"${{ runner.temp }}\emulebb-output\artifacts\live-e2e-suite\**" in text
    assert r"${{ runner.temp }}\emulebb-output\logs\builds\**" in text


def test_controlled_smoke_keeps_first_lane_narrow() -> None:
    text = _read_app_workflow("controlled-smoke.yml").lower()

    assert "--fixture-size-bytes" not in text
    assert "package-helper-integration" not in text
    assert "amutorrent-local-ed2k-ui-live" not in text
    assert "--test-network vpn" not in text
    assert "--test-network all" not in text
    assert "hyper-v" not in text
    assert "hyperv" not in text
    assert "windows-vm" not in text


def test_vs2026_v145_probe_exercises_native_build_without_smoke_or_package() -> None:
    text = _read_app_workflow("vs2026-v145-probe.yml")

    assert "workflow_dispatch:" in text
    assert "runs_on: windows-2025-vs2026" in text
    assert '$env:EMULEBB_VS_PLATFORM_TOOLSET = "v145"' in text
    assert '$env:EMULEBB_CMAKE_GENERATOR = "Visual Studio 18 2026"' in text
    assert "python -m emule_workspace build libs" in text
    assert "python -m emule_workspace build app" in text
    assert "--config Release" in text
    assert "--platform x64" in text
    assert "--clean" in text
    assert "--variant main" in text
    assert r"${{ runner.temp }}\emulebb-output\reports\v145-probe\**" in text
    assert r"${{ runner.temp }}\emulebb-output\logs\builds\**" in text
    assert "package-release" not in text
    assert "package-amutorrent" not in text
    assert "test live-e2e" not in text
    assert "hyper-v" not in text.lower()
    assert "hyperv" not in text.lower()


def test_emulebb_publish_release_workflow_builds_and_publishes_github_generated_assets() -> None:
    text = _read_app_workflow("publish-release.yml")

    assert "workflow_dispatch:" in text
    assert "release_version:" in text
    assert "target_sha:" in text
    assert "build_ref:" in text
    assert "emulebb-v${RELEASE_VERSION}" in text
    assert "^[0-9]+\\.[0-9]+\\.[0-9]+(-(rc|beta)\\.[0-9]+)?$" in text
    assert "^[0-9a-fA-F]{40}$" in text
    assert "gh release view" in text
    assert 'tag_type="$(git cat-file -t ' in text
    assert "git tag -a \"${TAG_NAME}\" \"${TARGET_SHA}\"" in text
    assert "git push origin \"refs/tags/${TAG_NAME}\"" in text
    assert "--verify-tag" in text
    assert "--prerelease --latest=false" in text
    assert "--latest" in text
    assert "uses: emulebb/emulebb-build/.github/workflows/reusable-workspace-command.yml@main" in text
    assert "app_ref: ${{ needs.prepare.outputs.target_sha }}" in text
    assert "build_ref: ${{ inputs.build_ref }}" in text
    assert "runs_on: windows-2022" in text
    assert "python -m emule_workspace package-release" in text
    assert "--release-version $packageVersion" in text
    assert "emulebb-$packageVersion-$assetArch.zip" in text
    assert "emulebb-$packageVersion-$assetArch.manifest.json" in text
    assert "emulebb-$packageVersion-$assetArch.sbom.spdx.json" in text
    assert "emulebb-$packageVersion-diagnostics-$assetArch.zip" in text
    assert "emulebb-$packageVersion-diagnostics-$assetArch.manifest.json" in text
    assert "emulebb-$packageVersion-diagnostics-$assetArch.sbom.spdx.json" in text
    assert "Bootstrap-eMuleBBSuite.ps1" in text
    assert "Bootstrap-eMuleBBSuite.ps1.sha256" in text
    assert "actions/attest@v4" in text
    assert "gh attestation verify PATH_TO_ASSET -R ${GITHUB_REPOSITORY}" in text
    assert "package-amutorrent" not in text
    assert "emulebb-nightly-" not in text


def test_emulebb_nightly_workflow_publishes_standard_and_diagnostics_assets() -> None:
    text = _read_app_workflow("nightly.yml")

    assert "emulebb-nightly-${release_date}-${short_sha}" in text
    assert "python -m emule_workspace package-release" in text
    assert "--release-version $packageVersion" in text
    assert "emulebb-$packageVersion-${{ matrix.asset_arch }}.zip" in text
    assert "emulebb-$packageVersion-${{ matrix.asset_arch }}.manifest.json" in text
    assert "emulebb-$packageVersion-${{ matrix.asset_arch }}.sbom.spdx.json" in text
    assert "emulebb-$packageVersion-diagnostics-${{ matrix.asset_arch }}.zip" in text
    assert "emulebb-$packageVersion-diagnostics-${{ matrix.asset_arch }}.manifest.json" in text
    assert "emulebb-$packageVersion-diagnostics-${{ matrix.asset_arch }}.sbom.spdx.json" in text
    assert "Nightly standard and diagnostics ZIP" in text
    assert "Bootstrap-eMuleBBSuite.ps1" in text
    assert "Bootstrap-eMuleBBSuite.ps1.sha256" in text
    assert "actions/attest@v4" in text


def test_amutorrent_publish_release_workflow_uses_own_release_and_controller_assets() -> None:
    text = _read_amutorrent_workflow("publish-release.yml")

    assert "workflow_dispatch:" in text
    assert "release_version:" in text
    assert "target_sha:" in text
    assert "build_ref:" in text
    assert "amutorrent_version:" in text
    assert "package_version:" in text
    assert "amutorrent-v${amutorrent_version}-emulebb-v${PACKAGE_VERSION}" in text
    assert "^[0-9]+\\.[0-9]+\\.[0-9]+(-(rc|beta)\\.[0-9]+)?$" in text
    assert "^[0-9a-fA-F]{40}$" in text
    assert "read_version(\"package.json\")" in text
    assert "read_version(\"server/package.json\")" in text
    assert '["git", "show", f"{target}:{path}"]' in text
    assert "root_version != server_version" in text
    assert "gh release view" in text
    assert 'tag_type="$(git cat-file -t ' in text
    assert "git tag -a \"${TAG_NAME}\" \"${TARGET_SHA}\"" in text
    assert "aMuTorrent ${AMUTORRENT_VERSION} for eMuleBB ${PACKAGE_VERSION}" in text
    assert "git push origin \"refs/tags/${TAG_NAME}\"" in text
    assert "--verify-tag" in text
    assert "--prerelease --latest=false" in text
    assert "--latest" in text
    assert "uses: emulebb/emulebb-build/.github/workflows/reusable-workspace-command.yml@main" in text
    assert "amutorrent_repository: ${{ github.repository }}" in text
    assert "amutorrent_ref: ${{ needs.prepare.outputs.target_sha }}" in text
    assert "build_ref: ${{ inputs.build_ref }}" in text
    assert 'node_version: "24"' in text
    assert "python -m emule_workspace package-amutorrent" in text
    assert "--release-version $packageVersion" in text
    assert '$packageVersion = "${{ needs.prepare.outputs.package_version }}"' in text
    assert "emulebb-$packageVersion-amutorrent-x64.zip" in text
    assert "emulebb-$packageVersion-amutorrent-x64.manifest.json" in text
    assert "emulebb-$packageVersion-amutorrent-x64.sbom.spdx.json" in text
    assert "actions/attest@v4" in text
    assert "gh attestation verify PATH_TO_ASSET -R ${GITHUB_REPOSITORY}" in text
    assert "package-release" not in text
    assert "amutorrent-nightly-" not in text
