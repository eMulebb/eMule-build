from __future__ import annotations

from pathlib import Path

from emule_workspace import qbittorrentbb_runtime


def test_stage_qbittorrentbb_runtime_copies_transitive_dlls_plugins_and_qt_conf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target_root = tmp_path / "out"
    search_root = tmp_path / "deps"
    qt_prefix = tmp_path / "qt"
    qbt_root = tmp_path / "qbittorrentbb"
    executable = target_root / "qbittorrent.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    (search_root / "Qt6Core.dll").parent.mkdir(parents=True)
    (search_root / "Qt6Core.dll").write_bytes(b"qtcore")
    (search_root / "z.dll").write_bytes(b"zlib")
    (qt_prefix / "plugins" / "platforms").mkdir(parents=True)
    (qt_prefix / "plugins" / "platforms" / "qwindows.dll").write_bytes(b"plugin")
    (qbt_root / "dist" / "windows").mkdir(parents=True)
    (qbt_root / "dist" / "windows" / "qt.conf").write_text("test-qt-conf\n", encoding="utf-8")

    def fake_dependents(_dumpbin: str, binary: Path) -> list[str]:
        return {
            "qbittorrent.exe": ["Qt6Core.dll", "kernel32.dll", "missing.dll"],
            "Qt6Core.dll": ["z.dll"],
            "z.dll": [],
            "qwindows.dll": ["Qt6Core.dll"],
        }.get(binary.name, [])

    monkeypatch.setattr(qbittorrentbb_runtime, "_qbt_find_dumpbin", lambda: "dumpbin")
    monkeypatch.setattr(qbittorrentbb_runtime, "_qbt_dll_dependents", fake_dependents)

    result = qbittorrentbb_runtime.stage_qbittorrentbb_runtime(
        executable=executable,
        target_root=target_root,
        qt_prefix=qt_prefix,
        qbt_root=qbt_root,
        search_dirs=[search_root],
    )

    assert (target_root / "Qt6Core.dll").read_bytes() == b"qtcore"
    assert (target_root / "z.dll").read_bytes() == b"zlib"
    assert not (target_root / "kernel32.dll").exists()
    assert not (target_root / "missing.dll").exists()
    assert (target_root / "plugins" / "platforms" / "qwindows.dll").read_bytes() == b"plugin"
    assert (target_root / "qt.conf").read_text(encoding="utf-8") == "test-qt-conf\n"
    assert result.bundled_runtime == ["Qt6Core.dll", "z.dll"]


def test_stage_qbittorrentbb_runtime_writes_default_qt_conf_when_source_is_absent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target_root = tmp_path / "out"
    qt_prefix = tmp_path / "qt"
    executable = target_root / "qbittorrent.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    qt_prefix.mkdir()
    monkeypatch.setattr(qbittorrentbb_runtime, "_qbt_find_dumpbin", lambda: "dumpbin")
    monkeypatch.setattr(qbittorrentbb_runtime, "_qbt_dll_dependents", lambda _dumpbin, _binary: [])

    qbittorrentbb_runtime.stage_qbittorrentbb_runtime(
        executable=executable,
        target_root=target_root,
        qt_prefix=qt_prefix,
        qbt_root=tmp_path / "missing-qbt-root",
        search_dirs=[],
    )

    assert (target_root / "qt.conf").read_text(encoding="utf-8") == "[Paths]\nPlugins=plugins\n"
