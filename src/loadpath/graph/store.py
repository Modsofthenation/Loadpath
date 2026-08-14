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


class GraphStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

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

    def file_hash(self, path: str) -> str | None:
        row = self.conn.execute("SELECT hash FROM files WHERE path=?", (path,)).fetchone()
        return row["hash"] if row else None

    def upsert_file(self, path: str, digest: str, language: str | None) -> None:
        self.conn.execute(
            "INSERT INTO files(path, hash, language) VALUES(?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET hash=excluded.hash, language=excluded.language",
            (path, digest, language),
        )

    def delete_file_nodes(self, path: str) -> None:
        ids = [
            r["id"]
            for r in self.conn.execute("SELECT id FROM nodes WHERE file_path=?", (path,)).fetchall()
        ]
        if not ids:
            self.conn.execute("DELETE FROM files WHERE path=?", (path,))
            return
        placeholders = ",".join("?" * len(ids))
        self.conn.execute(f"DELETE FROM edges WHERE src IN ({placeholders}) OR dst IN ({placeholders})", ids + ids)
        self.conn.execute("DELETE FROM nodes WHERE file_path=?", (path,))
        self.conn.execute("DELETE FROM files WHERE path=?", (path,))

    def upsert_graph(self, graph: ExtractedGraph) -> None:
        for node in graph.nodes:
            self.upsert_node(node)
        for edge in graph.edges:
            self.upsert_edge(edge)
        self.conn.commit()

    def upsert_node(self, node: Node) -> None:
        existing = self.get_node(node.id)
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
            (
                node.id,
                node.type.value,
                node.name,
                node.qualified_name,
                file_path,
                start_line,
                node.end_line,
                context,
                json.dumps(extra),
            ),
        )

    def upsert_edge(self, edge: Edge) -> None:
        row = edge.to_row()
        self.conn.execute(
            """
            INSERT INTO edges(id, src, dst, type, weight, confidence, extra)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                weight=excluded.weight,
                confidence=excluded.confidence,
                extra=excluded.extra
            """,
            (
                row["id"],
                row["src"],
                row["dst"],
                row["type"],
                row["weight"],
                row["confidence"],
                json.dumps(row["extra"]),
            ),
        )

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return self._node_from_row(row) if row else None

    def nodes(self, types: Iterable[NodeType] | None = None) -> list[dict[str, Any]]:
        if types:
            values = [t.value for t in types]
            placeholders = ",".join("?" * len(values))
            rows = self.conn.execute(
                f"SELECT * FROM nodes WHERE type IN ({placeholders})", values
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM nodes").fetchall()
        return [self._node_from_row(r) for r in rows]

    def edges(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM edges").fetchall()
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
        frontier = set(seed_ids)
        seen_nodes = set(frontier)
        seen_edges: dict[str, dict[str, Any]] = {}
        for _ in range(hops):
            if not frontier:
                break
            nxt: set[str] = set()
            for nid in frontier:
                for edge in self.neighbors(nid, "both"):
                    seen_edges[edge["id"]] = edge
                    other = edge["dst"] if edge["src"] == nid else edge["src"]
                    if other not in seen_nodes:
                        seen_nodes.add(other)
                        nxt.add(other)
            frontier = nxt
        nodes = [self.get_node(i) for i in seen_nodes]
        return [n for n in nodes if n], list(seen_edges.values())

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

    def list_reviews(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, created_at, repo_root, base_ref, head_ref FROM reviews ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        n = self.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
        e = self.conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
        return {"nodes": n, "edges": e}

    def type_counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT type, COUNT(*) AS c FROM nodes GROUP BY type").fetchall()
        return {r["type"]: r["c"] for r in rows}

    def file_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]

    @staticmethod
    def _node_from_row(row: sqlite3.Row) -> dict[str, Any]:
        extra = json.loads(row["extra"] or "{}")
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
        extra = json.loads(row["extra"] or "{}")
        return {
            "id": row["id"],
            "src": row["src"],
            "dst": row["dst"],
            "type": row["type"],
            "weight": row["weight"],
            "confidence": row["confidence"],
            "extra": extra,
        }
