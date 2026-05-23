"""Python test command orchestration for emulebb-build-tests."""

from __future__ import annotations

from .config import PythonTestOptions
from .layout import WorkspaceLayout
from .process import get_python_invocation, run_native


def invoke_python_tests(layout: WorkspaceLayout, options: PythonTestOptions) -> None:
    """Runs the fast pytest harness suite from the shared test repository."""

    pytest_args: list[str] = []
    if options.quiet:
        pytest_args.append("-q")
    pytest_args.extend(options.paths)
    if options.expression:
        pytest_args.extend(["-k", options.expression])
    pytest_args.extend(options.extra_args)

    python = get_python_invocation()
    run_native(
        python.command(["-m", "pytest", *pytest_args]),
        label="python tests",
        cwd=layout.tests_repo_root,
    )
