from __future__ import annotations

from pathlib import Path

import pytest

from emule_workspace import build
from emule_workspace.config import WorkspaceOptions
from emule_workspace.layout import AppVariant, TestTargets as LayoutTestTargets, WorkspaceLayout


def test_build_libs_passes_default_toolset_to_msbuild_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = capture_build_libs_msbuild_calls(tmp_path, monkeypatch)

    assert captured
    for call in captured:
        assert "/p:PlatformToolset=v143" in call["extra_properties"]


def test_build_libs_honors_toolset_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMULEBB_VS_PLATFORM_TOOLSET", "v145")

    captured = capture_build_libs_msbuild_calls(tmp_path, monkeypatch)

    assert captured
    for call in captured:
        assert "/p:PlatformToolset=v145" in call["extra_properties"]
        assert "/p:PlatformToolset=v143" not in call["extra_properties"]


def test_build_libs_clean_release_x64_removes_generated_dependency_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[tuple[Path, str]] = []

    capture_build_libs_msbuild_calls(tmp_path, monkeypatch, clean=True, removed_generated=removed)

    assert [kind for _repo, kind in removed] == ["zlib", "mbedtls"]


def test_build_apps_forwards_startup_profiling_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = capture_build_apps_msbuild_call(
        tmp_path,
        monkeypatch,
        enable_startup_diagnostics=True,
    )

    assert "/p:EnableStartupDiagnostics=true" in captured["extra_properties"]


def test_build_apps_honors_startup_profiling_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMULEBB_ENABLE_STARTUP_DIAGNOSTICS", "off")

    captured = capture_build_apps_msbuild_call(tmp_path, monkeypatch)

    assert "/p:EnableStartupDiagnostics=false" in captured["extra_properties"]


def test_build_apps_honors_diagnostics_env_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMULEBB_ENABLE_STARTUP_DIAGNOSTICS", "1")
    monkeypatch.setenv("EMULEBB_ENABLE_UPLOAD_SLOT_DIAGNOSTICS", "1")
    monkeypatch.setenv("EMULEBB_ENABLE_DOWNLOAD_SLOT_DIAGNOSTICS", "true")
    monkeypatch.setenv("EMULEBB_ENABLE_BAD_PEER_DIAGNOSTICS", "yes")
    monkeypatch.setenv("EMULEBB_ENABLE_PACKET_DIAGNOSTICS", "on")

    captured = capture_build_apps_msbuild_call(tmp_path, monkeypatch)

    assert "/p:EnableStartupDiagnostics=true" in captured["extra_properties"]
    assert "/p:EnableUploadSlotDiagnostics=true" in captured["extra_properties"]
    assert "/p:EnableDownloadSlotDiagnostics=true" in captured["extra_properties"]
    assert "/p:EnableBadPeerDiagnostics=true" in captured["extra_properties"]
    assert "/p:EnablePacketDiagnostics=true" in captured["extra_properties"]
    assert "/p:TargetName=emulebb-diagnostics" in captured["extra_properties"]
    assert captured["cfg_binary_path"].name == "emulebb-diagnostics.exe"


def test_build_apps_diagnostics_option_enables_all_release_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMULEBB_ENABLE_PACKET_DIAGNOSTICS", "off")

    captured = capture_build_apps_msbuild_call(tmp_path, monkeypatch, enable_diagnostics=True)

    assert "/p:EnableStartupDiagnostics=true" in captured["extra_properties"]
    assert "/p:EnableUploadSlotDiagnostics=true" in captured["extra_properties"]
    assert "/p:EnableDownloadSlotDiagnostics=true" in captured["extra_properties"]
    assert "/p:EnableBadPeerDiagnostics=true" in captured["extra_properties"]
    assert "/p:EnablePacketDiagnostics=true" in captured["extra_properties"]
    assert "/p:EnablePacketDiagnostics=false" not in captured["extra_properties"]
    assert "/p:TargetName=emulebb-diagnostics" in captured["extra_properties"]
    assert captured["cfg_binary_path"].name == "emulebb-diagnostics.exe"
    assert captured["step_name"] == "APP main diagnostics"


def test_build_apps_diagnostics_option_requires_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match="--diagnostics requires --config Release"):
        capture_build_apps_msbuild_call(
            tmp_path,
            monkeypatch,
            configuration="Debug",
            enable_diagnostics=True,
        )


def test_build_apps_can_disable_packet_diagnostics_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMULEBB_ENABLE_PACKET_DIAGNOSTICS", "off")

    captured = capture_build_apps_msbuild_call(tmp_path, monkeypatch)

    assert "/p:EnablePacketDiagnostics=false" in captured["extra_properties"]
    assert "/p:TargetName=emulebb-diagnostics" not in captured["extra_properties"]


def test_build_apps_keeps_standard_name_without_full_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMULEBB_ENABLE_STARTUP_DIAGNOSTICS", "1")
    monkeypatch.setenv("EMULEBB_ENABLE_PACKET_DIAGNOSTICS", "on")

    captured = capture_build_apps_msbuild_call(tmp_path, monkeypatch)

    assert "/p:TargetName=emulebb-diagnostics" not in captured["extra_properties"]
    assert captured["cfg_binary_path"].name == "emulebb.exe"


def capture_build_libs_msbuild_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    clean: bool = False,
    removed_generated: list[tuple[Path, str]] | None = None,
) -> list[dict[str, object]]:
    layout = make_layout(tmp_path)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(build, "get_cmake_path", lambda: Path("cmake.exe"))
    monkeypatch.setattr(build, "get_perl_path", lambda: Path("perl.exe"))
    monkeypatch.setattr(build, "invoke_cmake_dependency_build", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build, "ensure_arm64_override_targets", lambda _layout: None)
    if removed_generated is not None:
        monkeypatch.setattr(
            build,
            "remove_stale_generated_artifacts",
            lambda repo_path, kind: removed_generated.append((repo_path, kind)),
        )

    def fake_invoke_msbuild_project(*_args, **kwargs):
        calls.append(
            {
                "project_path": kwargs["project_path"],
                "extra_properties": tuple(kwargs.get("extra_properties") or ()),
                "step_name": kwargs["step_name"],
            }
        )

    monkeypatch.setattr(build, "invoke_msbuild_project", fake_invoke_msbuild_project)

    build.build_libs(
        layout,
        WorkspaceOptions(workspace_root=layout.emule_workspace_root, configuration="Release", platform="x64"),
        clean=clean,
    )

    return calls


def capture_build_apps_msbuild_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enable_startup_diagnostics: bool | None = None,
    enable_diagnostics: bool = False,
    configuration: str = "Release",
) -> dict[str, object]:
    layout = make_layout(tmp_path, app_variants=True)
    captured: dict[str, object] = {}

    monkeypatch.setattr(build, "assert_app_layout", lambda _layout: None)
    monkeypatch.setattr(build, "ensure_app_dependency_artifacts", lambda *_args, **_kwargs: None)

    def fake_verify_app_control_flow_guard(*_args, **kwargs):
        captured["cfg_binary_path"] = kwargs["binary_path"]

    monkeypatch.setattr(build, "verify_app_control_flow_guard", fake_verify_app_control_flow_guard)

    def fake_invoke_msbuild_project(*_args, **kwargs):
        captured["project_path"] = kwargs["project_path"]
        captured["extra_properties"] = tuple(kwargs.get("extra_properties") or ())
        captured["step_name"] = kwargs["step_name"]

    monkeypatch.setattr(build, "invoke_msbuild_project", fake_invoke_msbuild_project)

    build.build_apps(
        layout,
        WorkspaceOptions(workspace_root=layout.emule_workspace_root, configuration=configuration, platform="x64"),
        clean=False,
        app_variant_names=("main",),
        enable_startup_diagnostics=enable_startup_diagnostics,
        enable_diagnostics=enable_diagnostics,
    )

    return captured


def make_layout(tmp_path: Path, *, app_variants: bool = False) -> WorkspaceLayout:
    emule_workspace_root = tmp_path / "workspace-root"
    workspace_root = emule_workspace_root / "workspaces" / "workspace"
    app_root = workspace_root / "app" / "emulebb-main"
    return WorkspaceLayout(
        emule_workspace_root=emule_workspace_root,
        workspace_name="workspace",
        workspace_root=workspace_root,
        build_repo_root=emule_workspace_root / "repos" / "emulebb-build",
        tests_repo_root=emule_workspace_root / "repos" / "emulebb-build-tests",
        tooling_repo_root=emule_workspace_root / "repos" / "emulebb-tooling",
        ed2k_server_repo_root=emule_workspace_root / "repos" / "goed2k-server",
        amule_repo_root=emule_workspace_root / "repos" / "amule",
        seed_repo_path=emule_workspace_root / "repos" / "emulebb",
        seed_repo_branch="main",
        dependencies=(),
        app_variants=(AppVariant(name="main", path=app_root, branch="main"),) if app_variants else (),
        test_targets=LayoutTestTargets(test_build_variant="main", test_run_variant="main", baseline_variant="community"),
        toolset_override_variable="EMULEBB_VS_PLATFORM_TOOLSET",
    )
