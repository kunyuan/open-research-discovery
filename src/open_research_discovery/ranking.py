from __future__ import annotations

from typing import Any, Iterable


RESULT_ONLY_DEFINITION = (
    "Review may use only the frozen problem specification, the declared final "
    "deliverable (including executable formal proof code or certificates), declared "
    "trusted verifiers, and frozen reference data; hiding the solver's search and "
    "reasoning process and every undeclared auxiliary explanation must not change "
    "the verdict."
)


IMPORTANCE_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "unassessed": 3,
}

REVIEW_SCOPE_ORDER = {
    "result-only": 0,
    "result-and-derivation": 1,
    "expert-intensive": 2,
    "unclassified": 3,
}

OPENNESS_ORDER = {
    "confirmed_open": 0,
    "likely_open": 1,
    "needs_reformulation": 2,
    "unclassified": 3,
    "resolved": 4,
    "refuted": 4,
}

LANE_ORDER = {
    "research-ready": 0,
    "verifier-blocked": 1,
    "derivation-or-expert": 2,
    "status-check": 3,
    "low-significance": 4,
    "closed": 5,
}


def timeout_class(timeout_minutes: int) -> tuple[str, int]:
    if timeout_minutes <= 0:
        return "unknown", 4
    if timeout_minutes <= 10:
        return "fast", 0
    if timeout_minutes <= 30:
        return "moderate", 1
    if timeout_minutes <= 120:
        return "slow", 2
    return "very-slow", 3


def ci_feasibility(record: dict[str, Any]) -> str:
    status = str(record.get("ci_status") or "blocked")
    mode = str(record.get("verification_mode") or "unclassified")
    scope = str(record.get("review_scope") or "unclassified")
    if status == "implemented":
        return "runnable"
    if status == "partial":
        return "partial"
    if status == "pseudocode":
        return "specified"
    if (
        status == "reviewer-only"
        and mode == "llm-reviewable"
        and scope == "result-only"
    ):
        return "bounded-llm"
    if status == "reviewer-only":
        return "manual-only"
    return "blocked"


def openness_state(record: dict[str, Any]) -> str:
    conclusion = str(record.get("resolution_conclusion") or "unclassified")
    resolution = str(record.get("resolution_status") or "")
    if conclusion in {"resolved", "refuted"} or resolution in {
        "resolved",
        "refuted",
    }:
        return "closed"
    if conclusion in {"confirmed_open", "likely_open"} and resolution in {
        "still_open",
        "partially_resolved",
    }:
        return "current-open"
    return "status-check"


def ranking_lane(record: dict[str, Any]) -> str:
    state = openness_state(record)
    if state == "closed":
        return "closed"
    if state == "status-check":
        return "status-check"

    importance = str(record.get("importance_level") or "unassessed")
    if importance not in {"high", "medium"}:
        return "low-significance"

    scope = str(record.get("review_scope") or "unclassified")
    if scope != "result-only":
        return "derivation-or-expert"

    feasibility = ci_feasibility(record)
    if feasibility in {"runnable", "partial", "specified", "bounded-llm"}:
        return "research-ready"
    return "verifier-blocked"


def ranking_rationale(record: dict[str, Any]) -> str:
    lane = ranking_lane(record)
    importance = str(record.get("importance_level") or "unassessed")
    scope = str(record.get("review_scope") or "unclassified")
    feasibility = ci_feasibility(record)
    timeout = int(record.get("ci_timeout_minutes") or 0)
    speed, _ = timeout_class(timeout)
    return (
        f"{importance} importance; {scope} review; "
        f"{feasibility} acceptance path; {speed} CI timeout; lane={lane}"
    )


def ranking_key(record: dict[str, Any]) -> tuple[Any, ...]:
    lane = ranking_lane(record)
    importance = str(record.get("importance_level") or "unassessed")
    scope = str(record.get("review_scope") or "unclassified")
    timeout = int(record.get("ci_timeout_minutes") or 0)
    _, speed_order = timeout_class(timeout)
    conclusion = str(record.get("resolution_conclusion") or "unclassified")
    return (
        LANE_ORDER[lane],
        IMPORTANCE_ORDER.get(importance, 4),
        REVIEW_SCOPE_ORDER.get(scope, 4),
        speed_order,
        timeout if timeout > 0 else 10**9,
        OPENNESS_ORDER.get(conclusion, 5),
        str(record.get("id") or ""),
    )


def verifier_queue_key(record: dict[str, Any]) -> tuple[Any, ...]:
    lane = ranking_lane(record)
    feasibility = ci_feasibility(record)
    if lane == "research-ready" and feasibility in {"partial", "specified"}:
        queue_group = 0
    elif lane == "verifier-blocked":
        queue_group = 1
    elif lane == "research-ready":
        queue_group = 2
    else:
        queue_group = 3 + LANE_ORDER[lane]
    verifier_state_order = {
        "partial": 0,
        "specified": 1,
        "blocked": 2,
        "manual-only": 3,
        "runnable": 4,
        "bounded-llm": 5,
    }
    base = ranking_key(record)
    return (
        queue_group,
        base[1],
        verifier_state_order[feasibility],
        *base[2:],
    )


def annotate_record(record: dict[str, Any]) -> dict[str, Any]:
    timeout = int(record.get("ci_timeout_minutes") or 0)
    speed, _ = timeout_class(timeout)
    return {
        **record,
        "ranking_lane": ranking_lane(record),
        "openness_state": openness_state(record),
        "ci_feasibility": ci_feasibility(record),
        "ci_timeout_class": speed,
        "ranking_rationale": ranking_rationale(record),
    }


def rank_records(
    records: Iterable[dict[str, Any]], *, queue: str = "research"
) -> list[dict[str, Any]]:
    if queue not in {"research", "verifier"}:
        raise ValueError(f"unknown ranking queue: {queue}")
    key = ranking_key if queue == "research" else verifier_queue_key
    return [annotate_record(record) for record in sorted(records, key=key)]
