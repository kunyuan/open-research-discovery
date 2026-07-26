from __future__ import annotations

from typing import Any


REVIEW_SCOPES = {
    "result-only",
    "result-and-derivation",
    "expert-intensive",
    "unclassified",
}

CI_STATUSES = {
    "implemented",
    "partial",
    "pseudocode",
    "reviewer-only",
    "blocked",
}


def progress_for(
    resolution_status: str, review: dict[str, Any]
) -> dict[str, Any]:
    if resolution_status == "partially_resolved":
        return {
            "major_progress_found": True,
            "effect": "narrows",
            "surviving_core_reassessed": True,
            "importance_reassessed": True,
            "review_reassessed": True,
            "decision": review.get("progress_decision", "rewrite-core"),
            "derived_problem_ids": list(review.get("derived_problem_ids") or []),
        }
    if resolution_status in {"resolved", "refuted"}:
        return {
            "major_progress_found": True,
            "effect": "resolves" if resolution_status == "resolved" else "refutes",
            "surviving_core_reassessed": True,
            "importance_reassessed": True,
            "review_reassessed": True,
            "decision": review.get("progress_decision", "stop"),
            "derived_problem_ids": list(review.get("derived_problem_ids") or []),
        }
    return {
        "major_progress_found": False,
        "effect": "none" if resolution_status == "still_open" else "uncertain",
        "surviving_core_reassessed": False,
        "importance_reassessed": False,
        "review_reassessed": False,
        "decision": "continue" if resolution_status == "still_open" else "unassessed",
        "derived_problem_ids": [],
    }


def apply_review(
    problem: dict[str, Any], review: dict[str, Any], reviewed_at: str
) -> dict[str, Any]:
    scope = review["review_scope"]
    problem["research_triage"] = {
        "reviewed_at": reviewed_at,
        "importance_level": review["importance_level"],
        "audit_priority": review["audit_priority"],
        "post_audit_priority": review["post_audit_priority"],
        "route": "candidate-result" if scope == "result-only" else "manual-review",
        "rationale": review["importance_rationale"],
    }
    problem["reviewer_contract"].update(
        {
            "scope": scope,
            "estimated_review_time": review["estimated_review_time"],
            "acceptance_boundary": review["acceptance_boundary"],
        }
    )
    problem["ci_contract"]["status"] = review["ci_status"]
    resolution_status = problem["resolution_audit"]["status"]
    problem["resolution_audit"]["progress_assessment"] = progress_for(
        resolution_status, review
    )
    if review.get("post_progress_importance"):
        problem["importance"].update(review["post_progress_importance"])
    return problem


def validate_review_set(
    reviews: dict[str, dict[str, Any]], problem_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    missing = sorted(problem_ids - set(reviews))
    extra = sorted(set(reviews) - problem_ids)
    if missing:
        errors.append(f"missing review IDs: {', '.join(missing)}")
    if extra:
        errors.append(f"unknown review IDs: {', '.join(extra)}")
    required = {
        "importance_level",
        "importance_rationale",
        "audit_priority",
        "post_audit_priority",
        "review_scope",
        "estimated_review_time",
        "acceptance_boundary",
        "ci_status",
    }
    for problem_id, review in reviews.items():
        absent = sorted(required - set(review))
        if absent:
            errors.append(f"{problem_id} missing fields: {', '.join(absent)}")
        if review.get("review_scope") not in REVIEW_SCOPES:
            errors.append(f"{problem_id} has invalid review_scope")
        if review.get("ci_status") not in CI_STATUSES:
            errors.append(f"{problem_id} has invalid ci_status")
    return errors
