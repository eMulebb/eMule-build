"""Dependency and app build orchestration."""

from __future__ import annotations

import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from .build_state import BuildSession
from .cmake import invoke_cmake_dependency_build, remove_tree_if_present, static_msvc_runtime_cmake_arguments
from .config import BuildClientsOptions, WorkspaceOptions
from .git import repo_branch, test_app_branch_allowed
from .layout import WorkspaceLayout
from .msbuild import env_override, invoke_msbuild_project
from .process import find_tool
from .toolchain import get_cmake_path, get_dumpbin_path, get_perl_path


def build_libs(layout: WorkspaceLayout, options: WorkspaceOptions, *, clean: bool) -> None:
    """Builds the workspace-owned third-party dependency set."""

    session = BuildSession(layout=layout, options=options, command_name="build libs", clean=clean)
    try:
        third_party = layout.resolve_workspace_path("repos/third_party")
        target = "Rebuild" if clean else "Build"
        if options.platform == "ARM64":
            ensure_arm64_override_targets(layout)

        invoke_msbuild_project(
            session,
            project_path=third_party / "eMule-cryptopp" / "cryptlib.vcxproj",
            extra_properties=crypto_pp_properties(layout, options.platform),
            environment_overrides=crypto_pp_environment(options.platform),
            target=target,
            step_name="DEP cryptopp",
        )
        invoke_msbuild_project(
            session,
            project_path=third_party / "eMule-id3lib" / "libprj" / "id3lib.vcxproj",
            extra_properties=id3lib_properties(options.configuration, options.platform),
            target=target,
            step_name="DEP id3lib",
        )
        invoke_msbuild_project(
            session,
            project_path=third_party / "eMule-miniupnp" / "miniupnpc" / "msvc" / "miniupnpc.vcxproj",
            target=target,
            step_name="DEP miniupnp",
        )
        if clean:
            remove_tree_if_present(libpcpnatpmp_build_root(layout, options.platform))
        invoke_cmake_dependency_build(
            session,
            source_directory=third_party / "eMule-libpcpnatpmp",
            build_directory=libpcpnatpmp_build_root(layout, options.platform),
            target_name="pcpnatpmp",
            step_name="DEP libpcpnatpmp",
            configure_arguments=static_msvc_runtime_cmake_arguments(),
        )
        invoke_msbuild_project(
            session,
            project_path=third_party / "eMule-ResizableLib" / "ResizableLib" / "ResizableLib.vcxproj",
            target=target,
            step_name="DEP ResizableLib",
        )
        if clean and options.configuration == "Debug" and options.platform == "x64":
            remove_stale_generated_artifacts(third_party / "eMule-zlib", "zlib")
            remove_stale_generated_artifacts(third_party / "eMule-mbedtls", "mbedtls")
        invoke_msbuild_project(
            session,
            project_path=third_party / "eMule-zlib" / "contrib" / "vstudio" / "vc" / "zlib.vcxproj",
            extra_properties=(f"/p:WorkspaceCMakeExe={get_cmake_path()}",),
            target=target,
            step_name="DEP zlib",
        )
        invoke_msbuild_project(
            session,
            project_path=mbedtls_project_path(layout),
            extra_properties=(f"/p:WorkspaceCMakeExe={get_cmake_path()}", f"/p:WorkspacePerlExe={get_perl_path()}"),
            target=target,
            step_name="DEP mbedtls",
        )
    finally:
        session.write_recap()


def build_apps(
    layout: WorkspaceLayout,
    options: WorkspaceOptions,
    *,
    clean: bool,
    app_variant_names: tuple[str, ...],
) -> None:
    """Builds selected managed app variants."""

    session = BuildSession(layout=layout, options=options, command_name="build app", clean=clean)
    try:
        assert_app_layout(layout)
        ensure_app_dependency_artifacts(layout, options, clean=clean)
        target = "Rebuild" if clean else "Build"
        variants = selected_app_variants(layout, app_variant_names)
        for variant in variants:
            extra_properties = [*app_property_overrides(layout, options.platform)]
            override = env_override(layout.toolset_override_variable)
            if override:
                extra_properties.append(f"/p:PlatformToolset={override}")
            invoke_msbuild_project(
                session,
                project_path=variant.path / "srchybrid" / "emule.vcxproj",
                extra_properties=extra_properties,
                target=target,
                step_name=f"APP {variant.name}",
            )
            if variant.name == "main":
                verify_app_control_flow_guard(
                    session,
                    binary_path=app_binary_path(variant.path, options.configuration, options.platform),
                    step_name=f"APP {variant.name} CFG",
                )
    finally:
        session.write_recap()


def build_clients(layout: WorkspaceLayout, options: WorkspaceOptions, build_options: BuildClientsOptions) -> None:
    """Builds opt-in third-party P2P clients used by live multi-client tests."""

    session = BuildSession(layout=layout, options=options, command_name="build clients", clean=build_options.clean)
    try:
        selected_clients = tuple(dict.fromkeys(build_options.clients or ("emuleai", "amule")))
        for client in selected_clients:
            if client == "emuleai":
                build_emuleai_client(session, clean=build_options.clean)
            elif client == "amule":
                build_amule_client(session, clean=build_options.clean)
            else:
                raise RuntimeError(f"Unsupported client build target: {client}")
    finally:
        session.write_recap()


def build_emuleai_client(session: BuildSession, *, clean: bool) -> None:
    """Builds the eMuleAI fork using the workspace MSBuild entrypoint."""

    target = "Rebuild" if clean else "Build"
    extra_properties = []
    override = env_override(session.layout.toolset_override_variable)
    if override:
        extra_properties.append(f"/p:PlatformToolset={override}")
    invoke_msbuild_project(
        session,
        project_path=session.layout.emuleai_repo_root / "eMuleAI.sln",
        extra_properties=extra_properties,
        target=target,
        step_name="CLIENT eMuleAI",
    )


def build_amule_client(session: BuildSession, *, clean: bool) -> None:
    """Builds the aMule Windows portable client and stages daemon tools under workspace state."""

    bash = find_tool(("bash.exe", "bash"))
    if bash is None:
        raise RuntimeError(
            "build clients --client amule requires an MSYS2 bash on PATH. "
            "Open an MSYS2 MINGW64 shell or add its bash.exe to PATH."
        )
    script_path = session.layout.amule_repo_root / "packaging" / "windows" / "build.sh"
    if not script_path.is_file():
        raise RuntimeError(f"aMule Windows build script was not found: {script_path}")
    if clean:
        for path in (
            session.layout.amule_repo_root / "build-windows-x86_64",
            session.layout.amule_repo_root / "amule-portable-x86_64",
            session.layout.amule_repo_root / "dist",
            staged_amule_root(session.layout),
        ):
            remove_tree_if_present(path)

    log_path = session.log_directory / "client-amule-build-release-x64.log"
    started_at = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(f"{bash} {script_path}\n\n")
            completed = subprocess.run(
                [str(bash), str(script_path)],
                cwd=session.layout.amule_repo_root,
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                env={**subprocess_os_environ(), "WINDOWS_MSYSTEM": "MINGW64"},
            )
        if completed.returncode != 0:
            raise RuntimeError(f"aMule Windows build failed with exit code {completed.returncode}. See {log_path}")
        stage_amule_runtime(session.layout)
        session.add_step(
            name="CLIENT aMule",
            succeeded=True,
            log_path=log_path,
            duration_seconds=time.monotonic() - started_at,
            warning_count=0,
        )
    except Exception:
        session.add_step(
            name="CLIENT aMule",
            succeeded=False,
            log_path=log_path,
            duration_seconds=time.monotonic() - started_at,
            warning_count=0,
        )
        raise


def subprocess_os_environ() -> dict[str, str]:
    """Returns a mutable environment dictionary without importing `os` at call sites."""

    import os

    return os.environ.copy()


def staged_amule_root(layout: WorkspaceLayout) -> Path:
    """Returns the workspace-state aMule runtime staging root."""

    return layout.workspace_root / "state" / "tools" / "amule"


def stage_amule_runtime(layout: WorkspaceLayout) -> None:
    """Stages the latest aMule portable runtime below the workspace state tree."""

    source_root = find_amule_portable_root(layout.amule_repo_root)
    target_root = staged_amule_root(layout)
    remove_tree_if_present(target_root)
    shutil.copytree(source_root, target_root)
    for required in ("bin/amuled.exe", "bin/amulecmd.exe"):
        if not (target_root / required).is_file():
            raise RuntimeError(f"Staged aMule runtime is missing required file: {target_root / required}")


def find_amule_portable_root(repo_root: Path) -> Path:
    """Finds or extracts the portable aMule runtime built by the Windows recipe."""

    candidates = sorted(
        (
            path.parent.parent
            for path in repo_root.glob("**/bin/amuled.exe")
            if "amule-portable" in str(path.parent.parent).lower() or "dist" in str(path.parent.parent).lower()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        if (candidate / "bin" / "amulecmd.exe").is_file():
            return candidate

    zip_candidates = sorted((repo_root / "dist").glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not zip_candidates:
        raise RuntimeError(f"aMule build did not produce a portable runtime or zip under {repo_root}")
    extract_root = repo_root / "dist" / "_workspace-extracted"
    remove_tree_if_present(extract_root)
    with zipfile.ZipFile(zip_candidates[0]) as archive:
        archive.extractall(extract_root)
    extracted = sorted((path.parent.parent for path in extract_root.glob("**/bin/amuled.exe")), key=lambda path: str(path))
    for candidate in extracted:
        if (candidate / "bin" / "amulecmd.exe").is_file():
            return candidate
    raise RuntimeError(f"aMule zip does not contain bin/amuled.exe and bin/amulecmd.exe: {zip_candidates[0]}")


def selected_app_variants(layout: WorkspaceLayout, names: tuple[str, ...]):
    """Returns selected app variants, defaulting to all materialized variants."""

    if not names:
        return layout.app_variants
    selected = []
    for name in dict.fromkeys(name.strip() for name in names if name.strip()):
        selected.append(layout.get_app_variant(name))
    return tuple(selected)


def assert_app_layout(layout: WorkspaceLayout) -> None:
    """Checks that app worktrees exist and match branch policy."""

    missing = [variant.path for variant in layout.app_variants if not variant.path.exists()]
    if missing:
        raise RuntimeError("Missing app worktrees:\n" + "\n".join(str(path) for path in missing))
    for variant in layout.app_variants:
        current_branch = repo_branch(variant.path)
        if not test_app_branch_allowed(variant.branch, current_branch):
            raise RuntimeError(
                f"App checkout '{variant.path}' is on branch '{current_branch}', expected '{variant.branch}'."
            )


def ensure_app_dependency_artifacts(layout: WorkspaceLayout, options: WorkspaceOptions, *, clean: bool) -> None:
    """Builds dependencies when required app dependency outputs are missing."""

    missing = missing_app_dependency_artifacts(layout, options.configuration, options.platform)
    if not missing:
        return
    print(f"Missing dependency outputs for {options.configuration}|{options.platform}; running build libs.")
    build_libs(layout, options, clean=clean)
    missing = missing_app_dependency_artifacts(layout, options.configuration, options.platform)
    if missing:
        details = "\n".join(f"{name}: {path}" for name, path in missing)
        raise RuntimeError(f"Required dependency outputs are still missing for {options.configuration}|{options.platform}:\n{details}")


def missing_app_dependency_artifacts(layout: WorkspaceLayout, configuration: str, platform: str) -> list[tuple[str, Path]]:
    """Returns missing dependency artifacts required by app builds."""

    return [(name, path) for name, path in app_dependency_artifacts(layout, configuration, platform) if not path.exists()]


def app_dependency_artifacts(layout: WorkspaceLayout, configuration: str, platform: str) -> tuple[tuple[str, Path], ...]:
    """Returns required dependency library outputs for app builds."""

    third_party = layout.resolve_workspace_path("repos/third_party")
    mbedtls_root = mbedtls_library_root(layout, platform)
    return (
        ("cryptopp", third_party / "eMule-cryptopp" / platform / "Output" / configuration / "cryptlib.lib"),
        ("id3lib", third_party / "eMule-id3lib" / "libprj" / platform / configuration / "id3lib.lib"),
        ("miniupnp", third_party / "eMule-miniupnp" / "miniupnpc" / "msvc" / platform / configuration / "miniupnpc.lib"),
        ("libpcpnatpmp", libpcpnatpmp_library_path(layout, configuration, platform)),
        ("ResizableLib", third_party / "eMule-ResizableLib" / "ResizableLib" / platform / configuration / "ResizableLib.lib"),
        ("zlib", third_party / "eMule-zlib" / "contrib" / "vstudio" / "vc" / platform / configuration / "zlib.lib"),
        ("mbedtls", mbedtls_root / configuration / "mbedtls.lib"),
        ("mbedx509", mbedtls_root / configuration / "mbedx509.lib"),
        ("tfpsacrypto", mbedtls_root.parent / "tf-psa-crypto" / "core" / configuration / "tfpsacrypto.lib"),
    )


def app_property_overrides(layout: WorkspaceLayout, platform: str) -> tuple[str, ...]:
    """Returns app MSBuild dependency root properties."""

    third_party = layout.resolve_workspace_path("repos/third_party")
    return (
        f"/p:WorkspaceRoot={with_trailing_separator(layout.emule_workspace_root)}",
        f"/p:CryptoPpRoot={with_trailing_separator(third_party / 'eMule-cryptopp')}",
        f"/p:Id3libRoot={with_trailing_separator(third_party / 'eMule-id3lib')}",
        f"/p:MbedTlsRoot={with_trailing_separator(third_party / 'eMule-mbedtls')}",
        f"/p:MbedTlsLibRoot={with_trailing_separator(mbedtls_library_root(layout, platform))}",
        f"/p:MiniUpnpRoot={with_trailing_separator(third_party / 'eMule-miniupnp')}",
        f"/p:NlohmannJsonRoot={with_trailing_separator(third_party / 'eMule-nlohmann-json' / 'single_include')}",
        f"/p:PcpNatPmpRoot={with_trailing_separator(third_party / 'eMule-libpcpnatpmp')}",
        f"/p:PcpNatPmpLibRoot={with_trailing_separator(libpcpnatpmp_build_root(layout, platform) / 'lib')}",
        f"/p:ResizableLibRoot={with_trailing_separator(third_party / 'eMule-ResizableLib')}",
        f"/p:ZlibRoot={with_trailing_separator(third_party / 'eMule-zlib')}",
    )


def crypto_pp_properties(layout: WorkspaceLayout, platform: str) -> tuple[str, ...]:
    """Returns Crypto++ MSBuild policy overrides."""

    properties = [f"/p:PlatformToolset={env_override(layout.toolset_override_variable) or 'v143'}"]
    if platform == "ARM64":
        properties.extend(
            [
                f"/p:ForceImportAfterCppProps={arm64_overrides_props_path(layout)}",
                f"/p:ForceImportAfterCppTargets={arm64_overrides_targets_path(layout)}",
            ]
        )
    return tuple(properties)


def id3lib_properties(configuration: str, platform: str) -> tuple[str, ...]:
    """Returns id3lib MSBuild policy overrides."""

    if configuration == "Release" and platform == "ARM64":
        return ("/p:PlatformToolset=v143", "/p:ConfigurationType=StaticLibrary")
    return ()


def crypto_pp_environment(platform: str) -> dict[str, str]:
    """Returns Crypto++ compiler environment overrides."""

    if platform != "ARM64":
        return {}
    return {"CL": "/DCRYPTOPP_DISABLE_ASM /DCRYPTOPP_NO_CPU_FEATURE_PROBES"}


def ensure_arm64_override_targets(layout: WorkspaceLayout) -> None:
    """Writes ARM64 Crypto++ override files under workspace state."""

    props_path = arm64_overrides_props_path(layout)
    targets_path = arm64_overrides_targets_path(layout)
    props_path.parent.mkdir(parents=True, exist_ok=True)
    props_path.write_text(
        """<Project ToolsVersion="Current" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemDefinitionGroup Condition="'$(Platform)'=='ARM64'">
    <ClCompile>
      <AdditionalOptions>/DCRYPTOPP_DISABLE_ASM /DCRYPTOPP_NO_CPU_FEATURE_PROBES %(AdditionalOptions)</AdditionalOptions>
    </ClCompile>
  </ItemDefinitionGroup>
</Project>
""",
        encoding="utf-8",
        newline="\n",
    )
    targets_path.write_text(
        """<Project ToolsVersion="Current" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup Condition="'$(Platform)'=='ARM64'">
    <ClCompile Remove="blake2s_simd.cpp;blake2b_simd.cpp;chacha_simd.cpp;crc_simd.cpp;gcm_simd.cpp;gf2n_simd.cpp;lea_simd.cpp;rijndael_simd.cpp;sha_simd.cpp;simon128_simd.cpp;speck128_simd.cpp" />
  </ItemGroup>
</Project>
""",
        encoding="utf-8",
        newline="\n",
    )


def verify_app_control_flow_guard(session: BuildSession, *, binary_path: Path, step_name: str) -> None:
    """Verifies Control Flow Guard metadata in a built app executable."""

    relative_binary = binary_path.resolve().relative_to(session.layout.emule_workspace_root)
    log_path = session.log_directory / f"{str(relative_binary.with_suffix('')).replace('\\', '-')}-cfg.log"
    started_at = time.monotonic()
    try:
        if not binary_path.is_file():
            raise RuntimeError(f"Built app binary not found: {binary_path}")
        completed = subprocess.run(
            [str(get_dumpbin_path()), "/headers", "/loadconfig", str(binary_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        log_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
        if completed.returncode != 0:
            raise RuntimeError(f"dumpbin failed with exit code {completed.returncode} for {binary_path}")
        dumpbin_output = completed.stdout.lower()
        for pattern in ("cf instrumented", "fid table present"):
            if pattern not in dumpbin_output:
                raise RuntimeError(f"CFG verification failed for {binary_path}: missing '{pattern}' in dumpbin output.")
        session.add_step(
            name=step_name,
            succeeded=True,
            log_path=log_path,
            duration_seconds=time.monotonic() - started_at,
            warning_count=0,
        )
    except Exception:
        session.add_step(
            name=step_name,
            succeeded=False,
            log_path=log_path,
            duration_seconds=time.monotonic() - started_at,
            warning_count=0,
        )
        raise


def app_binary_path(app_root: Path, configuration: str, platform: str) -> Path:
    """Returns the built eMule executable path."""

    return app_root / "srchybrid" / platform / configuration / "emule.exe"


def mbedtls_project_path(layout: WorkspaceLayout) -> Path:
    """Returns the mbedTLS Visual Studio project path."""

    return layout.resolve_workspace_path("repos/third_party/eMule-mbedtls") / "visualc" / "VS2017" / "mbedTLS.vcxproj"


def mbedtls_library_root(layout: WorkspaceLayout, platform: str) -> Path:
    """Returns the mbedTLS library output root for a target platform."""

    return layout.resolve_workspace_path("repos/third_party/eMule-mbedtls") / "visualc" / f"VS2017-{platform}" / "library"


def libpcpnatpmp_build_root(layout: WorkspaceLayout, platform: str) -> Path:
    """Returns the libpcpnatpmp CMake build root."""

    return layout.resolve_workspace_path("repos/third_party/eMule-libpcpnatpmp") / f"cmake-build-{platform.lower()}"


def libpcpnatpmp_library_path(layout: WorkspaceLayout, configuration: str, platform: str) -> Path:
    """Returns the libpcpnatpmp static library path."""

    return libpcpnatpmp_build_root(layout, platform) / "lib" / configuration / "pcpnatpmp.lib"


def with_trailing_separator(path: Path) -> str:
    """Formats an absolute path with a trailing separator for MSBuild properties."""

    text = str(path.resolve())
    return text if text.endswith("\\") else text + "\\"


def arm64_overrides_props_path(layout: WorkspaceLayout) -> Path:
    """Returns the generated ARM64 Crypto++ props path."""

    return layout.workspace_root / "state" / "arm64-build-overrides.props"


def arm64_overrides_targets_path(layout: WorkspaceLayout) -> Path:
    """Returns the generated ARM64 Crypto++ targets path."""

    return layout.workspace_root / "state" / "arm64-build-overrides.targets"


def remove_stale_generated_artifacts(repo_path: Path, kind: str) -> None:
    """Removes stale generated dependency artifacts for clean Debug x64 rebuilds."""

    paths = {
        "zlib": (repo_path / "cmake-build-x64",),
        "mbedtls": (repo_path / "visualc" / "VS2017-x64", repo_path / "visualc" / "VS2017" / "x64"),
    }[kind]
    for path in paths:
        if path.exists():
            shutil.rmtree(path)
