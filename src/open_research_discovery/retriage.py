from __future__ import annotations

from typing import Any


SOLUTION_REVIEW_SCOPES = {
    "result-only",
    "result-and-derivation",
    "expert-intensive",
    "unclassified",
}

CI_STATUSES = {
    "implemented",
    "partial",
    "pseudocode",
    "solution-reviewer-only",
    "blocked",
}


def progress_for(
    resolution_status: str, problem_review: dict[str, Any]
) -> dict[str, Any]:
    if resolution_status == "partially_resolved":
        return {
            "major_progress_found": True,
            "effect": "narrows",
            "surviving_core_reassessed": True,
            "importance_reassessed": True,
            "solution_review_reassessed": True,
            "decision": problem_review.get(
                "progress_decision", "rewrite-core"
            ),
            "derived_problem_ids": list(
                problem_review.get("derived_problem_ids") or []
            ),
        }
    if resolution_status in {"resolved", "refuted"}:
        return {
            "major_progress_found": True,
            "effect": "resolves" if resolution_status == "resolved" else "refutes",
            "surviving_core_reassessed": True,
            "importance_reassessed": True,
            "solution_review_reassessed": True,
            "decision": problem_review.get("progress_decision", "stop"),
            "derived_problem_ids": list(
                problem_review.get("derived_problem_ids") or []
            ),
        }
    return {
        "major_progress_found": False,
        "effect": "none" if resolution_status == "still_open" else "uncertain",
        "surviving_core_reassessed": False,
        "importance_reassessed": False,
        "solution_review_reassessed": False,
        "decision": "continue" if resolution_status == "still_open" else "unassessed",
        "derived_problem_ids": [],
    }


def apply_problem_review(
    problem: dict[str, Any],
    problem_review: dict[str, Any],
    reviewed_at: str,
) -> dict[str, Any]:
    scope = problem_review["solution_review_scope"]
    problem["research_triage"] = {
        "reviewed_at": reviewed_at,
        "importance_level": problem_review["importance_level"],
        "audit_priority": problem_review["audit_priority"],
        "post_audit_priority": problem_review["post_audit_priority"],
        "route": "candidate-result" if scope == "result-only" else "manual-review",
        "rationale": problem_review["importance_rationale"],
    }
    problem["solution_review_contract"].update(
        {
            "scope": scope,
            "rationale": problem_review["solution_review_rationale"],
            "estimated_review_time": problem_review[
                "estimated_solution_review_time"
            ],
            "acceptance_boundary": problem_review["acceptance_boundary"],
        }
    )
    problem["ci_contract"]["status"] = problem_review["ci_status"]
    resolution_status = problem["resolution_audit"]["status"]
    problem["resolution_audit"]["progress_assessment"] = progress_for(
        resolution_status, problem_review
    )
    if problem_review.get("post_progress_importance"):
        problem["importance"].update(
            problem_review["post_progress_importance"]
        )
    return problem


def validate_problem_review_set(
    problem_reviews: dict[str, dict[str, Any]], problem_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    missing = sorted(problem_ids - set(problem_reviews))
    extra = sorted(set(problem_reviews) - problem_ids)
    if missing:
        errors.append(f"missing problem-review IDs: {', '.join(missing)}")
    if extra:
        errors.append(f"unknown problem-review IDs: {', '.join(extra)}")
    required = {
        "importance_level",
        "importance_rationale",
        "audit_priority",
        "post_audit_priority",
        "solution_review_scope",
        "solution_review_rationale",
        "estimated_solution_review_time",
        "acceptance_boundary",
        "ci_status",
    }
    for problem_id, problem_review in problem_reviews.items():
        absent = sorted(required - set(problem_review))
        if absent:
            errors.append(f"{problem_id} missing fields: {', '.join(absent)}")
        if (
            problem_review.get("solution_review_scope")
            not in SOLUTION_REVIEW_SCOPES
        ):
            errors.append(f"{problem_id} has invalid solution_review_scope")
        if problem_review.get("ci_status") not in CI_STATUSES:
            errors.append(f"{problem_id} has invalid ci_status")
    return errors
