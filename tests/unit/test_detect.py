from __future__ import annotations

from pathlib import Path

from loadpath.detect import detect_layout, write_draft_config
from tests.conftest import FIXTURE_ROOT as FIXTURE


def test_detects_demo_layout():
    layout = detect_layout(FIXTURE)
    assert layout["django_root"] == "backend"
    assert layout["react_root"] == "frontend/src"
    assert "billing" in layout["django_apps"]
    assert "accounts" in layout["django_apps"]
    assert "billing" in layout["react_features"]
    assert "auth" in layout["react_features"]
    assert "billing" in layout["contexts"]
    assert "identity" in layout["contexts"]
    assert layout["contexts"]["identity"]["django_apps"] == ["accounts"]
    assert any("features/auth" in p for p in layout["contexts"]["identity"]["react"])
    assert layout["has_config"] is True


def test_write_draft_does_not_overwrite_existing(tmp_path: Path):
    (tmp_path / "loadpath.yml").write_text("contexts: {}\n", encoding="utf-8")
    layout = write_draft_config(tmp_path)
    assert layout["wrote"] is False
    assert (tmp_path / "loadpath.yml").read_text(encoding="utf-8") == "contexts: {}\n"


def test_write_draft_creates_manifest(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "manage.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "backend" / "billing").mkdir()
    (tmp_path / "backend" / "billing" / "apps.py").write_text("class BillingConfig:\n    pass\n")
    (tmp_path / "frontend" / "src" / "features" / "billing").mkdir(parents=True)
    (tmp_path / "frontend" / "package.json").write_text("{}\n", encoding="utf-8")
    layout = write_draft_config(tmp_path)
    assert layout["wrote"] is True
    text = (tmp_path / "loadpath.yml").read_text(encoding="utf-8")
    assert "django_root: backend" in text
    assert "billing" in text
    assert "queryset_nplusone" in text
