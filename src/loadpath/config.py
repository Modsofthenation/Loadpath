from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RULES = [
    "views_cannot_import_other_context_models",
    "react_feature_may_only_call_own_or_shared_api",
    "serializers_are_the_only_published_contract",
    "no_queryset_in_serializer",
    "celery_tasks_must_be_idempotent_on_model_pk",
    "queryset_nplusone",
    "queryset_missing_index",
    "cascade_crosses_context",
    "migration_blast_radius",
    "leaked_seam",
    "tests_bypass_interface",
]


@dataclass
class ContextDef:
    name: str
    django_apps: list[str] = field(default_factory=list)
    react: list[str] = field(default_factory=list)
    public_api: list[str] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)


@dataclass
class Waiver:
    rule: str
    node: str | None = None
    reason: str = ""


@dataclass
class LoadpathConfig:
    repo_root: Path
    contexts: dict[str, ContextDef] = field(default_factory=dict)
    django_layers: list[str] = field(default_factory=lambda: ["route", "view", "service", "model"])
    react_layers: list[str] = field(
        default_factory=lambda: ["route", "page", "feature", "shared"]
    )
    rules: list[str] = field(default_factory=lambda: list(DEFAULT_RULES))
    waivers: list[Waiver] = field(default_factory=list)
    django_root: str = "backend"
    react_root: str = "frontend/src"
    openapi_paths: list[str] = field(default_factory=list)
    generated_client_globs: list[str] = field(
        default_factory=lambda: [
            "**/generated/**/*.{ts,tsx,js}",
            "**/*openapi*.{ts,js}",
            "**/orval/**/*.{ts,js}",
        ]
    )
    extra: dict[str, Any] = field(default_factory=dict)
    boot_django: bool = False

    def context_for_django_app(self, app: str) -> str | None:
        for name, ctx in self.contexts.items():
            if app in ctx.django_apps:
                return name
        return None

    def context_for_react_path(self, rel_path: str) -> str | None:
        normalized = rel_path.replace("\\", "/")
        for name, ctx in self.contexts.items():
            for prefix in ctx.react:
                if normalized.startswith(prefix.rstrip("/") + "/") or normalized.startswith(
                    prefix.rstrip("/")
                ):
                    return name
                # also match when react_root is prepended in stored paths
                if prefix.rstrip("/") in normalized:
                    # feature folder name match
                    feature = prefix.rstrip("/").split("/")[-1]
                    if f"/features/{feature}/" in f"/{normalized}/":
                        return name
        return None

    def is_shared_react(self, rel_path: str) -> bool:
        n = rel_path.replace("\\", "/")
        return "/shared/" in f"/{n}/" or n.startswith("shared/")

    def owners_for_context(self, context: str | None) -> list[str]:
        if not context:
            return []
        ctx = self.contexts.get(context)
        return list(ctx.owners) if ctx else []


def find_config(start: Path) -> Path | None:
    cur = start.resolve()
    for candidate in [cur, *cur.parents]:
        path = candidate / "loadpath.yml"
        if path.is_file():
            return path
    return None


def load_config(repo_root: Path, config_path: Path | None = None) -> LoadpathConfig:
    path = config_path or find_config(repo_root) or (repo_root / "loadpath.yml")
    if not path.is_file():
        return LoadpathConfig(repo_root=repo_root.resolve())

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    contexts: dict[str, ContextDef] = {}
    for name, data in (raw.get("contexts") or {}).items():
        data = data or {}
        contexts[name] = ContextDef(
            name=name,
            django_apps=list(data.get("django_apps") or []),
            react=list(data.get("react") or []),
            public_api=list(data.get("public_api") or []),
            owners=list(data.get("owners") or []),
        )

    layers = raw.get("layers") or {}
    waivers = [
        Waiver(rule=w.get("rule", ""), node=w.get("node"), reason=w.get("reason", ""))
        for w in (raw.get("waivers") or [])
    ]
    return LoadpathConfig(
        repo_root=repo_root.resolve(),
        contexts=contexts,
        django_layers=list(layers.get("django") or ["route", "view", "service", "model"]),
        react_layers=list(layers.get("react") or ["route", "page", "feature", "shared"]),
        rules=list(raw.get("rules") or DEFAULT_RULES),
        waivers=waivers,
        django_root=raw.get("django_root", "backend"),
        react_root=raw.get("react_root", "frontend/src"),
        openapi_paths=list(raw.get("openapi_paths") or []),
        generated_client_globs=list(
            raw.get("generated_client_globs")
            or [
                "**/generated/**/*.{ts,tsx,js}",
                "**/*openapi*.{ts,js}",
                "**/orval/**/*.{ts,js}",
            ]
        ),
        extra=raw,
        boot_django=bool(raw.get("boot_django", False)),
    )


def config_document(cfg: LoadpathConfig) -> dict[str, Any]:
    path = find_config(cfg.repo_root)
    return {
        "repo_root": str(cfg.repo_root),
        "path": str(path or (cfg.repo_root / "loadpath.yml")),
        "exists": path is not None,
        "contexts": {
            name: {
                "name": name,
                "django_apps": list(ctx.django_apps),
                "react": list(ctx.react),
                "public_api": list(ctx.public_api),
                "owners": list(ctx.owners),
            }
            for name, ctx in cfg.contexts.items()
        },
        "rules": list(cfg.rules),
        "available_rules": list(DEFAULT_RULES),
        "waivers": [
            {"rule": w.rule, "node": w.node, "reason": w.reason} for w in cfg.waivers
        ],
        "django_root": cfg.django_root,
        "react_root": cfg.react_root,
        "openapi_paths": list(cfg.openapi_paths),
        "boot_django": cfg.boot_django,
        "layers": {"django": list(cfg.django_layers), "react": list(cfg.react_layers)},
    }


def _dump_config_payload(raw: dict[str, Any]) -> str:
    header = (
        "# Loadpath architecture manifest. Contexts, public_api, owners, and waivers "
        "are the rules Loadpath will enforce.\n"
    )
    return header + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


def write_config(repo_root: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Write loadpath.yml from an editor document. Preserves unknown keys."""
    repo_root = repo_root.resolve()
    path = find_config(repo_root) or (repo_root / "loadpath.yml")
    raw: dict[str, Any] = {}
    if path.is_file():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raw = {}

    if "contexts" in document:
        contexts: dict[str, Any] = {}
        for name, data in (document.get("contexts") or {}).items():
            data = data or {}
            name = str(name).strip()
            if not name:
                continue
            contexts[name] = {
                "django_apps": list(data.get("django_apps") or []),
                "react": list(data.get("react") or []),
                "public_api": list(data.get("public_api") or []),
                "owners": list(data.get("owners") or []),
            }
        raw["contexts"] = contexts
    if "rules" in document and document["rules"] is not None:
        raw["rules"] = [str(r) for r in document["rules"] if str(r).strip()]
    if "waivers" in document:
        waivers = []
        for w in document.get("waivers") or []:
            rule = str((w or {}).get("rule") or "").strip()
            if not rule:
                continue
            item: dict[str, Any] = {"rule": rule}
            if (w or {}).get("node"):
                item["node"] = w["node"]
            if (w or {}).get("reason"):
                item["reason"] = w["reason"]
            waivers.append(item)
        raw["waivers"] = waivers
    if document.get("django_root") is not None:
        raw["django_root"] = document["django_root"]
    if document.get("react_root") is not None:
        raw["react_root"] = document["react_root"]
    if "openapi_paths" in document and document["openapi_paths"] is not None:
        raw["openapi_paths"] = list(document["openapi_paths"])
    if document.get("boot_django") is not None:
        raw["boot_django"] = bool(document["boot_django"])
    layers = document.get("layers")
    if isinstance(layers, dict):
        raw["layers"] = {
            "django": list(layers.get("django") or raw.get("layers", {}).get("django") or ["route", "view", "service", "model"]),
            "react": list(layers.get("react") or raw.get("layers", {}).get("react") or ["route", "page", "feature", "shared"]),
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_config_payload(raw), encoding="utf-8")
    return config_document(load_config(repo_root, path))


def add_waiver(repo_root: Path, rule: str, node: str | None = None, reason: str = "") -> dict[str, Any]:
    cfg = load_config(repo_root)
    doc = config_document(cfg)
    waivers = list(doc.get("waivers") or [])
    entry = {"rule": rule, "node": node, "reason": reason}
    if not any(w.get("rule") == rule and w.get("node") == node for w in waivers):
        waivers.append(entry)
    doc["waivers"] = waivers
    return write_config(repo_root, doc)
