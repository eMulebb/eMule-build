from __future__ import annotations

from pathlib import Path

import pytest

from emule_workspace.process import _validate_cargo_target_dir


def _env(tmp_path: Path) -> dict[str, str]:
    output_root = tmp_path / "output"
    target_dir = output_root / "builds" / "rust" / "target"
    target_dir.mkdir(parents=True)
    return {
        "EMULEBB_WORKSPACE_OUTPUT_ROOT": str(output_root),
        "CARGO_TARGET_DIR": str(target_dir),
    }


def test_cargo_target_dir_is_required_for_cargo(tmp_path: Path) -> None:
    env = _env(tmp_path)

    _validate_cargo_target_dir(["cargo", "test", "-p", "emulebb-rest"], env)


def test_cargo_target_dir_handles_absolute_cargo_executable(tmp_path: Path) -> None:
    env = _env(tmp_path)

    _validate_cargo_target_dir([r"C:/toolchains/rust/bin/cargo.exe", "build"], env)


def test_cargo_target_dir_is_not_derived_from_output_root(tmp_path: Path) -> None:
    env = _env(tmp_path)
    del env["CARGO_TARGET_DIR"]

    with pytest.raises(RuntimeError, match="CARGO_TARGET_DIR is required"):
        _validate_cargo_target_dir(["cargo", "build"], env)


def test_wrong_cargo_target_dir_is_rejected(tmp_path: Path) -> None:
    env = _env(tmp_path)
    wrong = tmp_path / "wrong-target"
    wrong.mkdir()
    env["CARGO_TARGET_DIR"] = str(wrong)

    with pytest.raises(RuntimeError, match="CARGO_TARGET_DIR must be"):
        _validate_cargo_target_dir(["cargo", "build"], env)


def test_nonexistent_cargo_target_dir_is_rejected(tmp_path: Path) -> None:
    env = _env(tmp_path)
    env["CARGO_TARGET_DIR"] = str(tmp_path / "output" / "builds" / "rust" / "missing")

    with pytest.raises(RuntimeError, match="existing directory"):
        _validate_cargo_target_dir(["cargo", "build"], env)


def test_non_cargo_commands_are_not_modified(tmp_path: Path) -> None:
    env = _env(tmp_path)
    del env["CARGO_TARGET_DIR"]

    _validate_cargo_target_dir(["git", "status"], env)

    assert "CARGO_TARGET_DIR" not in env


def test_empty_command_is_safe(tmp_path: Path) -> None:
    env = _env(tmp_path)
    del env["CARGO_TARGET_DIR"]

    _validate_cargo_target_dir([], env)

    assert "CARGO_TARGET_DIR" not in env
