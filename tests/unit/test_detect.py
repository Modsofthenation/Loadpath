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


def test_detect_prefers_frontend_over_docs_site(tmp_path: Path):
    (tmp_path / "api" / "billing").mkdir(parents=True)
    (tmp_path / "api" / "billing" / "apps.py").write_text("class BillingConfig:\n    pass\n")
    (tmp_path / "docs" / "src").mkdir(parents=True)
    (tmp_path / "docs" / "package.json").write_text('{"dependencies":{"react":"19.0.0"}}\n')
    (tmp_path / "frontend" / "web").mkdir(parents=True)
    (tmp_path / "frontend" / "package.json").write_text('{"dependencies":{"react":"19.0.0"}}\n')
    layout = detect_layout(tmp_path)
    assert layout["react_root"] == "frontend"
    assert layout["django_root"] == "api"


def test_detect_does_not_treat_python_src_as_react_root(tmp_path: Path):
    (tmp_path / "src" / "oscar").mkdir(parents=True)
    (tmp_path / "src" / "oscar" / "apps.py").write_text("class OscarConfig:\n    pass\n")
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    layout = detect_layout(tmp_path)
    assert layout["django_root"] == "src"
    assert layout["react_root"] == "frontend/src"


def test_detect_skips_nested_test_project_manage_py(tmp_path: Path):
    """Library repos (Wagtail) keep manage.py under a test project — index the package."""
    pkg = tmp_path / "pack" / "contrib" / "redirects"
    pkg.mkdir(parents=True)
    (pkg / "apps.py").write_text("class RedirectsConfig:\n    pass\n")
    images = tmp_path / "pack" / "images"
    images.mkdir()
    (images / "apps.py").write_text("class ImagesConfig:\n    pass\n")
    test_proj = tmp_path / "pack" / "test" / "testapp"
    test_proj.mkdir(parents=True)
    (tmp_path / "pack" / "test" / "manage.py").write_text("print(1)\n")
    (test_proj / "apps.py").write_text("class TestAppConfig:\n    pass\n")
    layout = detect_layout(tmp_path)
    assert layout["django_root"] == "pack"
    assert "redirects" in layout["django_apps"]
    assert "images" in layout["django_apps"]
    assert "testapp" not in layout["django_apps"]
