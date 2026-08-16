from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator

from loadpath.types import Edge, ExtractedGraph, Node, NodeType

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    language TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    file_path TEXT,
    start_line INTEGER,
    end_line INTEGER,
    context TEXT,
    extra TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    type TEXT NOT NULL,
    weight TEXT NOT NULL,
    confidence REAL NOT NULL,
    extra TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_context ON nodes(context);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    repo_root TEXT NOT NULL,
    base_ref TEXT,
    head_ref TEXT,
    payload TEXT NOT NULL
);
"""


def linked_edges(nodes: Iterable[dict[str, Any]], edges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only edges whose src and dst both exist in `nodes`."""
    ids = {n["id"] for n in nodes if n and n.get("id")}
    return [e for e in edges if e.get("src") in ids and e.get("dst") in ids]


class GraphStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        self.conn.execute("PRAGMA mmap_size = 268435456")
        self.conn.execute("PRAGMA cache_size = -32000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._nodes_cache: list[dict[str, Any]] | None = None
        self._edges_cache: list[dict[str, Any]] | None = None

    def close(self) -> None:
        self._nodes_cache = None
        self._edges_cache = None
        self.conn.close()

    def _invalidate(self) -> None:
        self._nodes_cache = None
        self._edges_cache = None

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def file_hashes(self) -> dict[str, str]:
        return {r["path"]: r["hash"] for r in self.conn.execute("SELECT path, hash FROM files")}

    def file_hash(self, path: str) -> str | None:
        row = self.conn.execute("SELECT hash FROM files WHERE path=?", (path,)).fetchone()
        return row["hash"] if row else None

    def upsert_file(self, path: str, digest: str, language: str | None) -> None:
        self.conn.execute(
            "INSERT INTO files(path, hash, language) VALUES(?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET hash=excluded.hash, language=excluded.language",
            (path, digest, language),
        )

    def delete_file_nodes(self, path: str, *, drop_incoming: bool = True) -> None:
        ids = [
            r["id"]
            for r in self.conn.execute("SELECT id FROM nodes WHERE file_path=?", (path,)).fetchall()
        ]
        if not ids:
            self.conn.execute("DELETE FROM files WHERE path=?", (path,))
            self._invalidate()
            return
        placeholders = ",".join("?" * len(ids))
        if drop_incoming:
            self.conn.execute(
                f"DELETE FROM edges WHERE src IN ({placeholders}) OR dst IN ({placeholders})",
                ids + ids,
            )
        else:
            # Reindex: keep edges from other files (e.g. view ENQUEUES → task).
            self.conn.execute(f"DELETE FROM edges WHERE src IN ({placeholders})", ids)
        self.conn.execute("DELETE FROM nodes WHERE file_path=?", (path,))
        self.conn.execute("DELETE FROM files WHERE path=?", (path,))
        self._invalidate()

    def prune_dangling_edges(self) -> None:
        self.conn.execute(
            "DELETE FROM edges WHERE src NOT IN (SELECT id FROM nodes) OR dst NOT IN (SELECT id FROM nodes)"
        )
        self._invalidate()

    def upsert_graph(self, graph: ExtractedGraph, *, commit: bool = True) -> None:
        if not graph.nodes and not graph.edges:
            if commit:
                self.conn.commit()
            return
        existing: dict[str, dict[str, Any]] = {}
        ids = [node.id for node in graph.nodes]
        for chunk in _chunks(ids, 400):
            placeholders = ",".join("?" * len(chunk))
            for row in self.conn.execute(
                f"SELECT * FROM nodes WHERE id IN ({placeholders})", chunk
            ):
                existing[row["id"]] = self._node_from_row(row)
        for node in graph.nodes:
            existing[node.id] = self._merged_node(node, existing.get(node.id))
        unique_ids = list(dict.fromkeys(ids))
        self.conn.executemany(
            """
            INSERT INTO nodes(id, type, name, qualified_name, file_path, start_line, end_line, context, extra)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                name=excluded.name,
                qualified_name=excluded.qualified_name,
                file_path=excluded.file_path,
                start_line=excluded.start_line,
                end_line=excluded.end_line,
                context=excluded.context,
                extra=excluded.extra
            """,
            [self._node_sql_row(existing[nid]) for nid in unique_ids],
        )
        self.conn.executemany(
            """
            INSERT INTO edges(id, src, dst, type, weight, confidence, extra)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                weight=excluded.weight,
                confidence=excluded.confidence,
                extra=excluded.extra
            """,
            [self._edge_row(edge) for edge in graph.edges],
        )
        if commit:
            self.conn.commit()
        self._invalidate()

    def upsert_node(self, node: Node) -> None:
        existing = self.get_node(node.id)
        self.conn.execute(
            """
            INSERT INTO nodes(id, type, name, qualified_name, file_path, start_line, end_line, context, extra)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                name=excluded.name,
                qualified_name=excluded.qualified_name,
                file_path=excluded.file_path,
                start_line=excluded.start_line,
                end_line=excluded.end_line,
                context=excluded.context,
                extra=excluded.extra
            """,
            self._node_sql_row(self._merged_node(node, existing)),
        )
        self._invalidate()

    def upsert_edge(self, edge: Edge) -> None:
        self.conn.execute(
            """
            INSERT INTO edges(id, src, dst, type, weight, confidence, extra)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                weight=excluded.weight,
                confidence=excluded.confidence,
                extra=excluded.extra
            """,
            self._edge_row(edge),
        )
        self._invalidate()

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return self._node_from_row(row) if row else None

    def nodes(self, types: Iterable[NodeType | str] | None = None) -> list[dict[str, Any]]:
        want = {t.value if isinstance(t, NodeType) else str(t) for t in types} if types else None
        if self._nodes_cache is not None:
            if want is None:
                return self._nodes_cache
            return [n for n in self._nodes_cache if n["type"] in want]
        if want:
            placeholders = ",".join("?" * len(want))
            rows = self.conn.execute(
                f"SELECT * FROM nodes WHERE type IN ({placeholders})", tuple(want)
            ).fetchall()
            return [self._node_from_row(r) for r in rows]
        self._nodes_cache = [self._node_from_row(r) for r in self.conn.execute("SELECT * FROM nodes")]
        return self._nodes_cache

    def edges(self) -> list[dict[str, Any]]:
        if self._edges_cache is None:
            self._edges_cache = [self._edge_from_row(r) for r in self.conn.execute("SELECT * FROM edges")]
        return self._edges_cache

    def edges_between_types(self, types: Iterable[str]) -> list[dict[str, Any]]:
        """Edges whose endpoints both have a type in `types`. Avoids loading the full graph."""
        want = sorted({str(t) for t in types})
        if not want:
            return []
        if self._edges_cache is not None and self._nodes_cache is not None:
            ids = {n["id"] for n in self._nodes_cache if n["type"] in set(want)}
            return [e for e in self._edges_cache if e["src"] in ids and e["dst"] in ids]
        placeholders = ",".join("?" * len(want))
        rows = self.conn.execute(
            f"""
            SELECT e.id, e.src, e.dst, e.type, e.weight, e.confidence, e.extra
            FROM edges e
            WHERE e.src IN (SELECT id FROM nodes WHERE type IN ({placeholders}))
              AND e.dst IN (SELECT id FROM nodes WHERE type IN ({placeholders}))
            """,
            (*want, *want),
        ).fetchall()
        return [self._edge_from_row(r) for r in rows]

    def edges_of_type(self, types: Iterable[str]) -> list[dict[str, Any]]:
        want = {str(t) for t in types}
        if not want:
            return []
        if self._edges_cache is not None:
            return [e for e in self._edges_cache if e["type"] in want]
        placeholders = ",".join("?" * len(want))
        rows = self.conn.execute(
            f"SELECT * FROM edges WHERE type IN ({placeholders})", tuple(want)
        ).fetchall()
        return [self._edge_from_row(r) for r in rows]

    def neighbors(self, node_id: str, direction: str = "both") -> list[dict[str, Any]]:
        clauses = []
        args: list[str] = []
        if direction in ("out", "both"):
            clauses.append("src=?")
            args.append(node_id)
        if direction in ("in", "both"):
            clauses.append("dst=?")
            args.append(node_id)
        rows = self.conn.execute(
            f"SELECT * FROM edges WHERE {' OR '.join(clauses)}", args
        ).fetchall()
        return [self._edge_from_row(r) for r in rows]

    def nodes_in_files(self, paths: Iterable[str]) -> list[dict[str, Any]]:
        path_list = list(paths)
        if not path_list:
            return []
        placeholders = ",".join("?" * len(path_list))
        rows = self.conn.execute(
            f"SELECT * FROM nodes WHERE file_path IN ({placeholders})", path_list
        ).fetchall()
        return [self._node_from_row(r) for r in rows]

    def subgraph(self, seed_ids: Iterable[str], hops: int = 6) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        known = {r["id"] for r in self.conn.execute("SELECT id FROM nodes")}
        frontier = set(seed_ids) & known
        seen_nodes = set(frontier)
        seen_edges: dict[str, dict[str, Any]] = {}
        for _ in range(hops):
            if not frontier:
                break
            nxt: set[str] = set()
            for nid in frontier:
                for edge in self.neighbors(nid, "both"):
                    other = edge["dst"] if edge["src"] == nid else edge["src"]
                    if other not in known:
                        continue
                    seen_edges[edge["id"]] = edge
                    if other not in seen_nodes:
                        seen_nodes.add(other)
                        nxt.add(other)
            frontier = nxt
        nodes = [n for n in (self.get_node(i) for i in seen_nodes) if n]
        return nodes, linked_edges(nodes, list(seen_edges.values()))

    def iter_nodes(self) -> Iterator[dict[str, Any]]:
        for row in self.conn.execute("SELECT * FROM nodes"):
            yield self._node_from_row(row)

    def save_review(self, review_id: str, created_at: str, repo_root: str, base_ref: str, head_ref: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO reviews(id, created_at, repo_root, base_ref, head_ref, payload) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (review_id, created_at, repo_root, base_ref, head_ref, json.dumps(payload)),
        )
        self.conn.commit()

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "repo_root": row["repo_root"],
            "base_ref": row["base_ref"],
            "head_ref": row["head_ref"],
            "payload": json.loads(row["payload"]),
        }

    def list_reviews(self, *, include_payload: bool = False, limit: int = 40) -> list[dict[str, Any]]:
        sql = "SELECT id, created_at, repo_root, base_ref, head_ref"
        if include_payload:
            sql += ", payload"
        sql += " FROM reviews ORDER BY created_at DESC LIMIT ?"
        rows = self.conn.execute(sql, (max(1, min(limit, 200)),)).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = {
                "id": row["id"],
                "created_at": row["created_at"],
                "repo_root": row["repo_root"],
                "base_ref": row["base_ref"],
                "head_ref": row["head_ref"],
            }
            if include_payload:
                item["payload"] = json.loads(row["payload"])
            out.append(item)
        return out

    def counts(self) -> dict[str, int]:
        n = self.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        e = self.conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
        return {"nodes": n, "edges": e}

    def type_counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT type, COUNT(*) AS c FROM nodes GROUP BY type").fetchall()
        return {r["type"]: r["c"] for r in rows}

    def file_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]

    def indexed_paths(self) -> list[str]:
        return [r["path"] for r in self.conn.execute("SELECT path FROM files").fetchall()]

    def _merged_node(self, node: Node, existing: dict[str, Any] | None) -> dict[str, Any]:
        extra = dict(node.extra or {})
        file_path = node.file_path
        start_line = node.start_line
        context = node.context
        if existing:
            merged = dict(existing.get("extra") or {})
            merged.update(extra)
            extra = merged
            new_is_ref = bool(node.extra.get("referenced"))
            old_is_ref = bool((existing.get("extra") or {}).get("referenced"))
            # A definition (tasks.py / @actor) wins over a call-site placeholder.
            if new_is_ref and not old_is_ref:
                extra["referenced"] = False
                for k, v in (existing.get("extra") or {}).items():
                    if k not in node.extra or node.extra.get(k) is None:
                        extra[k] = v
                file_path = existing.get("file_path") or file_path
                start_line = existing.get("start_line") if existing.get("start_line") is not None else start_line
                context = existing.get("context") or context
            elif not new_is_ref and old_is_ref:
                extra["referenced"] = False
        return {
            "id": node.id,
            "type": node.type.value,
            "name": node.name,
            "qualified_name": node.qualified_name,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": node.end_line,
            "context": context,
            "extra": extra,
        }

    @staticmethod
    def _node_sql_row(merged: dict[str, Any]) -> tuple[Any, ...]:
        extra = merged.get("extra") or {}
        return (
            merged["id"],
            merged["type"],
            merged["name"],
            merged["qualified_name"],
            merged["file_path"],
            merged["start_line"],
            merged["end_line"],
            merged["context"],
            "{}" if not extra else json.dumps(extra),
        )

    @staticmethod
    def _edge_row(edge: Edge) -> tuple[Any, ...]:
        row = edge.to_row()
        extra = row["extra"]
        return (
            row["id"],
            row["src"],
            row["dst"],
            row["type"],
            row["weight"],
            row["confidence"],
            "{}" if not extra else json.dumps(extra),
        )

    @staticmethod
    def _node_from_row(row: sqlite3.Row) -> dict[str, Any]:
        raw = row["extra"] or "{}"
        extra = {} if raw == "{}" else json.loads(raw)
        return {
            "id": row["id"],
            "type": row["type"],
            "name": row["name"],
            "qualified_name": row["qualified_name"],
            "file_path": row["file_path"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "context": row["context"],
            "extra": extra,
        }

    @staticmethod
    def _edge_from_row(row: sqlite3.Row) -> dict[str, Any]:
        raw = row["extra"] or "{}"
        extra = {} if raw == "{}" else json.loads(raw)
        return {
            "id": row["id"],
            "src": row["src"],
            "dst": row["dst"],
            "type": row["type"],
            "weight": row["weight"],
            "confidence": row["confidence"],
            "extra": extra,
        }


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]
