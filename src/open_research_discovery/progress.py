from __future__ import annotations

from typing import Any


def progress_assessment(decision: dict[str, Any]) -> dict[str, Any]:
    explicit = decision.get("progress_assessment")
    if explicit:
        if explicit.get("importance_reassessed") and not decision.get("importance"):
            raise ValueError(
                "importance_reassessed=true requires a post-progress importance block"
            )
        if explicit.get("review_reassessed") and not decision.get(
            "reviewer_contract"
        ):
            raise ValueError(
                "review_reassessed=true requires a post-progress reviewer_contract"
            )
        return explicit
    audit_status = decision["audit_status"]
    major = audit_status in {"partially_resolved", "resolved", "refuted"}
    effect = {
        "still_open": "none",
        "partially_resolved": "narrows",
        "resolved": "resolves",
        "refuted": "refutes",
        "uncertain": "uncertain",
    }[audit_status]
    return {
        "major_progress_found": major,
        "effect": effect,
        "surviving_core_reassessed": False,
        "importance_reassessed": False,
        "review_reassessed": False,
        "decision": "continue" if audit_status == "still_open" else "unassessed",
        "derived_problem_ids": [],
    }
