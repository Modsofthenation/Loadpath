"""CI merge-gate: map a review to a process exit code."""

from __future__ import annotations

FAIL_ON_CHOICES = ("never", "blocker", "low", "medium")


def gate_result(review: dict, fail_on: str = "blocker") -> dict:
    fail_on = (fail_on or "blocker").lower()
    if fail_on not in FAIL_ON_CHOICES:
        fail_on = "blocker"
    findings = [f for f in (review.get("findings") or []) if not f.get("waived")]
    blockers = [f for f in findings if f.get("severity") == "blocker"]
    level = (review.get("confidence") or {}).get("level") or "medium"
    contract = (review.get("contract_break") or {}).get("kind")
    reasons: list[str] = []
    code = 0
    if fail_on != "never" and blockers:
        code = 2
        reasons.append(f"{len(blockers)} architecture blocker(s)")
    if fail_on in {"low", "medium"} and level == "low" and code == 0:
        code = 3
        reasons.append("confidence is low")
    if fail_on == "medium" and level == "medium" and code == 0:
        code = 3
        reasons.append("confidence is medium")
    if fail_on in {"low", "medium"} and contract == "breaking" and code == 0:
        code = 4
        reasons.append("breaking public contract")
    passed = code == 0
    summary = "pass" if passed else "fail"
    title = (review.get("title") or "change").strip()
    return {
        "passed": passed,
        "exit_code": code,
        "fail_on": fail_on,
        "summary": summary,
        "level": level,
        "contract_break": contract,
        "blockers": len(blockers),
        "reasons": reasons,
        "annotation": f"Loadpath {level.upper()} — {title}"
        + (f" ({'; '.join(reasons)})" if reasons else ""),
    }


def write_github_output(path: str, gate: dict, review: dict) -> None:
    conf = review.get("confidence") or {}
    lines = [
        f"level={gate.get('level') or ''}",
        f"passed={str(gate['passed']).lower()}",
        f"title={review.get('title') or ''}",
        f"contract_break={gate.get('contract_break') or 'none'}",
        f"sinks={conf.get('sinks') or 0}",
        f"annotation={gate.get('annotation') or ''}",
    ]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
