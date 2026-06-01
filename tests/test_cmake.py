from __future__ import annotations

from emule_workspace.cmake import cmake_generator_arguments


def test_cmake_generator_defaults_to_installed_visual_studio(monkeypatch) -> None:
    monkeypatch.delenv("EMULEBB_CMAKE_GENERATOR", raising=False)
    monkeypatch.delenv("EMULEBB_CMAKE_PLATFORM", raising=False)

    assert cmake_generator_arguments("x64") == ("-A", "x64")


def test_cmake_generator_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("EMULEBB_CMAKE_GENERATOR", "Visual Studio 18 2026")
    monkeypatch.delenv("EMULEBB_CMAKE_PLATFORM", raising=False)

    assert cmake_generator_arguments("ARM64") == ("-G", "Visual Studio 18 2026", "-A", "ARM64")


def test_cmake_generator_platform_can_be_suppressed(monkeypatch) -> None:
    monkeypatch.setenv("EMULEBB_CMAKE_GENERATOR", "Ninja")
    monkeypatch.setenv("EMULEBB_CMAKE_PLATFORM", "")

    assert cmake_generator_arguments("x64") == ("-G", "Ninja")
