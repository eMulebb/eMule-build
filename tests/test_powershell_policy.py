from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_tooling_module(workspace_root: Path, module_name: str, relative_path: str) -> ModuleType:
    module_path = workspace_root / "repos" / "emulebb-tooling" / relative_path
    ci_path = str(module_path.parent)
    if ci_path not in sys.path:
        sys.path.insert(0, ci_path)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_basic_hygiene_accepts_emulebb_runtime_script_header(workspace_root: Path, tmp_path: Path) -> None:
    policy_guards = _load_tooling_module(workspace_root, "policy_guards_under_test", "ci/policy_guards.py")
    repo_root = tmp_path / "emulebb-build"
    script_path = repo_root / "emule_workspace" / "release_assets" / "emule" / "scripts" / "register-prowlarr.ps1"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#Requires -Version 5.1\n", encoding="utf-8")

    issue = policy_guards.test_powershell_version_header(
        repo_root,
        "emulebb-build",
        "emule_workspace/release_assets/emule/scripts/register-prowlarr.ps1",
        script_path,
    )

    assert issue is None


def test_basic_hygiene_rejects_bad_emulebb_runtime_script_header(workspace_root: Path, tmp_path: Path) -> None:
    policy_guards = _load_tooling_module(workspace_root, "policy_guards_under_test_bad_header", "ci/policy_guards.py")
    repo_root = tmp_path / "emulebb-build"
    script_path = repo_root / "emule_workspace" / "release_assets" / "emule" / "scripts" / "register-prowlarr.ps1"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#Requires -Version 7.6\n", encoding="utf-8")

    issue = policy_guards.test_powershell_version_header(
        repo_root,
        "emulebb-build",
        "emule_workspace/release_assets/emule/scripts/register-prowlarr.ps1",
        script_path,
    )

    assert issue == "Expected PowerShell version header '#Requires -Version 5.1' but found '#Requires -Version 7.6'."


def test_basic_hygiene_keeps_emulebb_script_exception_to_direct_children(workspace_root: Path, tmp_path: Path) -> None:
    policy_guards = _load_tooling_module(workspace_root, "policy_guards_under_test_nested", "ci/policy_guards.py")
    repo_root = tmp_path / "emulebb-build"
    script_path = repo_root / "emule_workspace" / "release_assets" / "emule" / "scripts" / "nested" / "tool.ps1"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#Requires -Version 5.1\n", encoding="utf-8")

    issue = policy_guards.test_powershell_version_header(
        repo_root,
        "emulebb-build",
        "emule_workspace/release_assets/emule/scripts/nested/tool.ps1",
        script_path,
    )

    assert issue == "Expected PowerShell version header '#Requires -Version 7.6' but found '#Requires -Version 5.1'."


def test_workspace_policy_accepts_allowed_emulebb_runtime_script(
    workspace_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _load_tooling_module(workspace_root, "check_workspace_policy_under_test", "ci/check-workspace-policy.py")
    build_root = tmp_path / "repos" / "emulebb-build"
    script_path = build_root / "emule_workspace" / "release_assets" / "emule" / "scripts" / "register-prowlarr.ps1"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#Requires -Version 5.1\n", encoding="utf-8")

    def fake_tracked_powershell_paths(repo_root: Path) -> tuple[str, ...]:
        if repo_root == build_root.resolve():
            return ("emule_workspace/release_assets/emule/scripts/register-prowlarr.ps1",)
        return ()

    monkeypatch.setattr(policy, "tracked_powershell_paths", fake_tracked_powershell_paths)

    policy.audit_powershell_boundary(tmp_path)


def test_workspace_policy_rejects_emulebb_runtime_script_without_required_header(
    workspace_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _load_tooling_module(workspace_root, "check_workspace_policy_under_test_bad_header", "ci/check-workspace-policy.py")
    build_root = tmp_path / "repos" / "emulebb-build"
    script_path = build_root / "emule_workspace" / "release_assets" / "emule" / "scripts" / "register-prowlarr.ps1"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#Requires -Version 7.6\n", encoding="utf-8")

    def fake_tracked_powershell_paths(repo_root: Path) -> tuple[str, ...]:
        if repo_root == build_root.resolve():
            return ("emule_workspace/release_assets/emule/scripts/register-prowlarr.ps1",)
        return ()

    monkeypatch.setattr(policy, "tracked_powershell_paths", fake_tracked_powershell_paths)

    with pytest.raises(RuntimeError, match="eMuleBB runtime PowerShell must declare #Requires -Version 5.1"):
        policy.audit_powershell_boundary(tmp_path)


def test_workspace_policy_rejects_nested_emulebb_runtime_script(
    workspace_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _load_tooling_module(workspace_root, "check_workspace_policy_under_test_nested", "ci/check-workspace-policy.py")
    build_root = tmp_path / "repos" / "emulebb-build"
    script_path = build_root / "emule_workspace" / "release_assets" / "emule" / "scripts" / "nested" / "tool.ps1"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#Requires -Version 5.1\n", encoding="utf-8")

    def fake_tracked_powershell_paths(repo_root: Path) -> tuple[str, ...]:
        if repo_root == build_root.resolve():
            return ("emule_workspace/release_assets/emule/scripts/nested/tool.ps1",)
        return ()

    monkeypatch.setattr(policy, "tracked_powershell_paths", fake_tracked_powershell_paths)

    with pytest.raises(RuntimeError, match="tracked PowerShell is only allowed"):
        policy.audit_powershell_boundary(tmp_path)
