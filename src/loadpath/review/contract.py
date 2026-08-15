"""Classify serializer/OpenAPI/Zod/GraphQL diffs as additive, breaking, or drift."""

from __future__ import annotations

import re

from loadpath.review.diff import DiffSet
from loadpath.types import CONTRACT_TYPES, ContractBreakKind, NodeType

REQUIRED_RE = re.compile(
    r"""extra_kwargs\s*=\s*\{[^}]*['"](\w+)['"]\s*:\s*\{[^}]*required['"]?\s*:\s*True""",
    re.S,
)
FIELD_ASSIGN_RE = re.compile(r"""^\s*(\w+)\s*=\s*\w*(Field|Serializer)\b""", re.M)
REMOVED_FIELD_RE = re.compile(r"""^\-\s*['"](\w+)['"]\s*,?\s*$""", re.M)
ADDED_FIELD_RE = re.compile(r"""^\+\s*['"](\w+)['"]\s*,?\s*$""", re.M)
ZOD_REQUIRED_RE = re.compile(r"""^\+\s*(\w+)\s*:\s*z\.""", re.M)
ZOD_OPTIONAL_RE = re.compile(r"""\.optional\(\)|\.nullish\(\)|nullish\(""")


def _touched(node: dict, changed_files: set[str]) -> bool:
    if not changed_files:
        return True
    return (node.get("file_path") or "") in changed_files


def classify_contract_break(impact_nodes: list[dict], diff: DiffSet | None) -> dict:
    kinds: set[str] = set()
    reasons: list[str] = []
    fields: list[str] = []
    contract_nodes = [n for n in impact_nodes if n.get("type") in {t.value for t in CONTRACT_TYPES}]
    if not contract_nodes:
        return {
            "kind": ContractBreakKind.NONE.value,
            "reasons": [],
            "fields": [],
        }

    patch = "\n".join(f.patch or "" for f in (diff.files if diff else []))
    changed_files = {f.path for f in (diff.files if diff else []) if not f.skip}
    required = {
        m.group(1)
        for m in REQUIRED_RE.finditer(patch)
        if "+" in patch[max(0, m.start() - 80) : m.start() + 1]
    }
    # extra_kwargs required=True in added lines
    added_required: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+") and "required" in line and "True" in line:
            names = re.findall(r"""['"](\w+)['"]""", line)
            added_required.extend(names)
        if line.startswith("+") and "required=True" in line.replace(" ", ""):
            added_required.extend(re.findall(r"""['"](\w+)['"]""", line))

    removed = REMOVED_FIELD_RE.findall(patch)
    added = ADDED_FIELD_RE.findall(patch)
    zod_added = ZOD_REQUIRED_RE.findall(patch)

    serializer_changed = any(
        n["type"] in {NodeType.SERIALIZER.value, NodeType.SERIALIZER_FIELD.value, NodeType.PYDANTIC_MODEL.value}
        and _touched(n, changed_files)
        for n in contract_nodes
    )
    graphql_changed = any(
        n["type"].startswith("graphql.") and _touched(n, changed_files) for n in contract_nodes
    )
    openapi_changed = any(
        n["type"] == NodeType.OPENAPI_PATH.value and _touched(n, changed_files) for n in contract_nodes
    )
    zod_changed = any(
        n["type"] == NodeType.FORM_SCHEMA.value and _touched(n, changed_files) for n in contract_nodes
    )

    if added_required or required:
        names = sorted({n for n in added_required if n not in {"extra_kwargs", "required"}} or required)
        if names:
            kinds.add(ContractBreakKind.BREAKING.value)
            fields.extend(names)
            reasons.append("Required contract field(s): " + ", ".join(f"`{n}`" for n in names[:6]))

    if removed and serializer_changed:
        kinds.add(ContractBreakKind.BREAKING.value)
        fields.extend(removed)
        reasons.append("Removed published field(s): " + ", ".join(f"`{n}`" for n in removed[:6]))

    if added and serializer_changed and ContractBreakKind.BREAKING.value not in kinds:
        kinds.add(ContractBreakKind.ADDITIVE.value)
        fields.extend(added)
        reasons.append("Added published field(s): " + ", ".join(f"`{n}`" for n in added[:6]))

    if graphql_changed:
        kinds.add(ContractBreakKind.BREAKING.value if serializer_changed else ContractBreakKind.ADDITIVE.value)
        reasons.append("GraphQL operation or type is on the impact path")

    if openapi_changed and serializer_changed:
        kinds.add(ContractBreakKind.DRIFT.value)
        reasons.append("OpenAPI path moved with the serializer — confirm generated clients")

    if zod_changed and serializer_changed:
        ser_names = {
            n["name"]
            for n in impact_nodes
            if n["type"] in {NodeType.SERIALIZER_FIELD.value, NodeType.FIELD.value}
        }
        schema_fields: set[str] = set()
        for n in impact_nodes:
            extra = n.get("extra") or {}
            if n["type"] == NodeType.FORM_SCHEMA.value:
                schema_fields.update(extra.get("fields") or [])
        missing = sorted(ser_names - schema_fields - {"id", "pk"})
        if missing:
            kinds.add(ContractBreakKind.DRIFT.value)
            fields.extend(missing)
            reasons.append("Zod/form schema does not include " + ", ".join(f"`{f}`" for f in missing[:6]))
        elif zod_added:
            kinds.add(ContractBreakKind.ADDITIVE.value)

    if not kinds and contract_nodes:
        kinds.add(ContractBreakKind.ADDITIVE.value)
        reasons.append("Public contract nodes changed without a detected field removal or required=True")

    order = [
        ContractBreakKind.BREAKING.value,
        ContractBreakKind.DRIFT.value,
        ContractBreakKind.ADDITIVE.value,
        ContractBreakKind.NONE.value,
    ]
    kind = next((k for k in order if k in kinds), ContractBreakKind.NONE.value)
    seen: set[str] = set()
    uniq_fields = []
    for f in fields:
        if f not in seen and f not in {"extra_kwargs", "required", "True", "False"}:
            seen.add(f)
            uniq_fields.append(f)
    return {"kind": kind, "reasons": reasons[:4], "fields": uniq_fields[:12]}
