from __future__ import annotations

from pathlib import Path

from loadpath.paths import package_dir


def test_package_dir_contains_static_and_report():
    root = package_dir()
    assert (root / "static" / "index.html").is_file()
    assert (root / "report" / "graph.html").is_file()


def test_package_dir_uses_meipass_when_frozen(monkeypatch, tmp_path: Path):
    bundled = tmp_path / "loadpath"
    (bundled / "static").mkdir(parents=True)
    (bundled / "static" / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("loadpath.paths.sys.frozen", True, raising=False)
    monkeypatch.setattr("loadpath.paths.sys._MEIPASS", str(tmp_path), raising=False)
    assert package_dir() == bundled
    assert (package_dir() / "static" / "index.html").is_file()
