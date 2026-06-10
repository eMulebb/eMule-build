from __future__ import annotations

from pathlib import Path

from emule_workspace.process import _ensure_cargo_target_dir


OUTPUT_ROOT = r"C:/var/build/emulebb_out"


def _expected_target_dir() -> str:
    return str(Path(OUTPUT_ROOT) / "builds" / "rust" / "target")


def test_cargo_target_dir_is_derived_from_output_root_for_cargo() -> None:
    env = {"EMULEBB_WORKSPACE_OUTPUT_ROOT": OUTPUT_ROOT}
    _ensure_cargo_target_dir(["cargo", "test", "-p", "emulebb-rest"], env)
    assert env["CARGO_TARGET_DIR"] == _expected_target_dir()


def test_cargo_target_dir_handles_absolute_cargo_executable() -> None:
    env = {"EMULEBB_WORKSPACE_OUTPUT_ROOT": OUTPUT_ROOT}
    _ensure_cargo_target_dir([r"C:/Users/dev/.cargo/bin/cargo.exe", "build"], env)
    assert env["CARGO_TARGET_DIR"] == _expected_target_dir()


def test_explicit_cargo_target_dir_is_respected() -> None:
    env = {
        "EMULEBB_WORKSPACE_OUTPUT_ROOT": OUTPUT_ROOT,
        "CARGO_TARGET_DIR": r"X:/explicit/target",
    }
    _ensure_cargo_target_dir(["cargo", "build"], env)
    assert env["CARGO_TARGET_DIR"] == r"X:/explicit/target"


def test_non_cargo_commands_are_not_modified() -> None:
    env = {"EMULEBB_WORKSPACE_OUTPUT_ROOT": OUTPUT_ROOT}
    _ensure_cargo_target_dir(["git", "status"], env)
    assert "CARGO_TARGET_DIR" not in env


def test_missing_output_root_leaves_cargo_target_unset() -> None:
    env: dict[str, str] = {}
    _ensure_cargo_target_dir(["cargo", "build"], env)
    assert "CARGO_TARGET_DIR" not in env


def test_empty_command_is_safe() -> None:
    env = {"EMULEBB_WORKSPACE_OUTPUT_ROOT": OUTPUT_ROOT}
    _ensure_cargo_target_dir([], env)
    assert "CARGO_TARGET_DIR" not in env
