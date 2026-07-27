from __future__ import annotations

from typing import Any, Iterable


RESULT_ONLY_DEFINITION = (
    "Ask one question: can an independent reviewer basically decide correctness "
    "from only the final result naturally required by the original problem, without "
    "reviewing the solver's reasoning process? If yes, the scope is result-only. If "
    "the reviewer must inspect a mathematical or scientific derivation, it is "
    "result-and-derivation. A source-faithful executable artifact may itself be the "
    "final result when the problem fixes the scientific target, baseline, regime, "
    "and comparison axes strongly enough that replay directly decides the claim. "
    "Routine reproducibility details such as versions, seeds, repetitions, and "
    "statistical tolerances may be frozen in the result; this does not authorize "
    "inventing a benchmark, proxy, threshold, certificate, formalization, or file "
    "format that changes the scientific target merely to change the label."
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
    "derivation-or-expert": 1,
    "status-check": 2,
    "low-significance": 3,
    "closed": 4,
}

CI_BONUS_ORDER = {
    "runnable": 0,
    "partial": 1,
    "specified": 2,
    "bounded-llm": 3,
    "manual-only": 4,
    "blocked": 5,
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
    scope = str(record.get("solution_review_scope") or "unclassified")
    if status == "implemented":
        return "runnable"
    if status == "partial":
        return "partial"
    if status == "pseudocode":
        return "specified"
    if status == "solution-reviewer-only" and scope == "result-only":
        return "bounded-llm"
    if status == "solution-reviewer-only":
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

    scope = str(record.get("solution_review_scope") or "unclassified")
    if scope != "result-only":
        return "derivation-or-expert"

    return "research-ready"


def ranking_rationale(record: dict[str, Any]) -> str:
    lane = ranking_lane(record)
    importance = str(record.get("importance_level") or "unassessed")
    scope = str(record.get("solution_review_scope") or "unclassified")
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
    scope = str(record.get("solution_review_scope") or "unclassified")
    timeout = int(record.get("ci_timeout_minutes") or 0)
    _, speed_order = timeout_class(timeout)
    conclusion = str(record.get("resolution_conclusion") or "unclassified")
    return (
        LANE_ORDER[lane],
        IMPORTANCE_ORDER.get(importance, 4),
        REVIEW_SCOPE_ORDER.get(scope, 4),
        CI_BONUS_ORDER.get(ci_feasibility(record), 6),
        speed_order,
        timeout if timeout > 0 else 10**9,
        OPENNESS_ORDER.get(conclusion, 5),
        str(record.get("id") or ""),
    )


def verifier_queue_key(record: dict[str, Any]) -> tuple[Any, ...]:
    lane = ranking_lane(record)
    feasibility = ci_feasibility(record)
    if lane == "research-ready" and feasibility in {
        "partial",
        "specified",
        "blocked",
        "manual-only",
    }:
        queue_group = 0
    elif lane == "research-ready":
        queue_group = 1
    else:
        queue_group = 2 + LANE_ORDER[lane]
    base = ranking_key(record)
    return (
        queue_group,
        base[1],
        CI_BONUS_ORDER.get(feasibility, 6),
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
