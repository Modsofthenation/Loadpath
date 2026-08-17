from __future__ import annotations

import time
from pathlib import Path

from loadpath.architecture.snapshot import architecture_report
from loadpath.config import LoadpathConfig
from loadpath.index import index_repo, iter_source_files
from loadpath.scan import is_minified_name, skip_dir_name


def test_skip_dir_names_cover_install_trees():
    assert skip_dir_name("node_modules")
    assert skip_dir_name(".git")
    assert skip_dir_name(".next")
    assert not skip_dir_name("frontend")
    assert not skip_dir_name("cypress")


def test_minified_and_dts_are_not_source():
    assert is_minified_name("vendor.min.js")
    assert is_minified_name("app.bundle.js")
    assert is_minified_name("types.d.ts")
    assert not is_minified_name("App.tsx")
    assert not is_minified_name("models.py")


def test_iter_source_files_prunes_node_modules_and_minified(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "views.py").write_text("def hello():\n    return 1\n")
    junk = tmp_path / "node_modules" / "pkg" / "dist"
    junk.mkdir(parents=True)
    (junk / "index.js").write_text("export const x = 1;\n")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "vendor.min.js").write_text("const a=1;\n" * 1000)
    (tmp_path / "frontend" / "src" / "App.tsx").write_text("export function App() { return <div/>; }\n")

    cfg = LoadpathConfig(repo_root=tmp_path)
    files = iter_source_files(tmp_path, cfg)
    rels = {p.relative_to(tmp_path).as_posix() for p in files}
    assert "backend/views.py" in rels
    assert "frontend/src/App.tsx" in rels
    assert not any("node_modules" in rel for rel in rels)
    assert not any(rel.endswith(".min.js") for rel in rels)


def test_pruned_walk_does_not_stat_skipped_trees(tmp_path: Path):
    (tmp_path / "app.py").write_text("x = 1\n")
    nested = tmp_path / "node_modules" / "pkg"
    nested.mkdir(parents=True)
    (nested / "index.js").write_text("export default 1;\n")

    seen: list[str] = []
    original_stat = Path.stat

    def wrapped(self, *args, **kwargs):
        seen.append(str(self))
        return original_stat(self, *args, **kwargs)

    Path.stat = wrapped  # type: ignore[method-assign]
    try:
        from loadpath.config import LoadpathConfig
        from loadpath.index import iter_source_files

        iter_source_files(tmp_path, LoadpathConfig(repo_root=tmp_path))
    finally:
        Path.stat = original_stat  # type: ignore[method-assign]

    assert not any("node_modules" in path for path in seen)


def test_architecture_report_uses_cached_findings(tmp_path: Path, monkeypatch):
    from loadpath.architecture import snapshot as snap
    from tests.conftest import prepare_review_repo

    repo = prepare_review_repo(tmp_path)
    store = index_repo(repo, incremental=False, workers=1)
    assert store.get_meta("findings_json")
    store.close()

    calls = {"n": 0}
    real = snap.evaluate

    def wrapped(store, config, changed_ids=None):
        calls["n"] += 1
        return real(store, config, changed_ids=changed_ids)

    monkeypatch.setattr(snap, "evaluate", wrapped)
    monkeypatch.setattr("loadpath.architecture.rules.evaluate", wrapped)
    report = architecture_report(repo, include_graph=False)
    assert report["indexed"] is True
    assert calls["n"] == 0
    assert isinstance(report["findings"], list)


def test_large_junk_tree_scan_stays_cheap(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "models.py").write_text("class M:\n    pass\n")
    for i in range(80):
        pkg = tmp_path / "node_modules" / f"pkg{i}" / "dist"
        pkg.mkdir(parents=True)
        for j in range(40):
            (pkg / f"f{j}.js").write_text("export const x = 1;\n")
    cfg = LoadpathConfig(repo_root=tmp_path)
    t0 = time.monotonic()
    files = iter_source_files(tmp_path, cfg)
    elapsed = time.monotonic() - t0
    assert len(files) == 1
    assert elapsed < 0.4
