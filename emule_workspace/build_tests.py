"""Native shared-test build command orchestration."""

from __future__ import annotations

from .artifact_names import utc_run_id
from .config import BuildTestsOptions, WorkspaceOptions
from .layout import WorkspaceLayout, file_token, get_test_build_tag
from .process import get_python_invocation, run_native


def invoke_build_tests(
    layout: WorkspaceLayout,
    workspace_options: WorkspaceOptions,
    build_options: BuildTestsOptions,
) -> None:
    """Invokes the maintained native-test build helper through the new CLI."""

    test_build_variant = build_options.test_run_variant or layout.test_targets.test_build_variant
    app_root = layout.get_app_variant(test_build_variant).path
    build_tag = get_test_build_tag(layout.workspace_root, app_root)
    build_log_session_stamp = utc_run_id()
    log_directory = layout.build_log_directory(build_log_session_stamp)
    suffix = f"{workspace_options.configuration.lower()}-{workspace_options.platform.lower()}"
    token = file_token(f"emule-tests-{build_tag}")
    print(f"Build logs: {log_directory}")
    print(f"Build tag: {build_tag}")

    python = get_python_invocation()
    script_path = layout.tests_repo_root / "scripts" / "build-emule-tests.py"
    args: list[str] = [
        script_path.as_posix(),
        "--test-repo-root",
        str(layout.tests_repo_root),
        "--app-root",
        str(app_root),
        "--configuration",
        workspace_options.configuration,
        "--platform",
        workspace_options.platform,
        "--build-output-mode",
        workspace_options.build_output_mode,
        "--build-log-session-stamp",
        build_log_session_stamp,
    ]
    if build_options.clean:
        args.append("--clean")
    run_native(
        python.command(args),
        label=f"build-emule-tests {workspace_options.configuration}/{workspace_options.platform}",
        cwd=layout.emule_workspace_root,
        env={"EMULEBB_WORKSPACE_ROOT": layout.emule_workspace_root},
    )
    print(f"Text log: {log_directory / f'{token}-{suffix}.log'}")
    print(f"Binary log: {log_directory / f'{token}-{suffix}.binlog'}")
