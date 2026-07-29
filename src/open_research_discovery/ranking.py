from __future__ import annotations

from typing import Any, Iterable


DEFAULT_MAX_VERIFICATION_DIFFICULTY = 3

VERIFICATION_DIFFICULTY_RUBRIC = (
    "Score the residual verification burden on an independent reviewer after "
    "every mechanically delegable check has been delegated, from 0 to 10. Score "
    "the cheapest sound verification path the contract permits, not the solver's "
    "path and not the scientific difficulty of discovering the answer. "
    "Verification modes, cheapest first: (M) mechanical checks such as kernels, "
    "type checkers, test suites, SMT/SAT solvers, numerical substitution, and "
    "finite enumeration; (R) replayable procedures under a pinned protocol; (C) "
    "certificate checks, where a witness or exact object settles the claim; (D) "
    "derivation review, reconstructing the submitter's reasoning; (H) holistic "
    "judgment of a natural-language argument as a whole. M, R, and C cost the "
    "reviewer a small constant regardless of the underlying proof or computation "
    "size; D grows with chain length, dependency depth, and non-standard "
    "technique; H cannot be decomposed. When the acceptance condition can be "
    "settled by a submitted finite witness, such as a counterexample, an "
    "explicit construction, or a certified number, score the cost of checking "
    "that witness, never the cost of constructing it: construction is the "
    "solver's discovery burden, not the reviewer's verification burden. An "
    "either-or contract, such as prove-or-refute, takes the cheapest sound "
    "branch, so do not score it by the derivation a proof would need when a "
    "counterexample would be checked directly. Score 0 when every "
    "load-bearing claim is "
    "discharged by M, R, or C and specification fidelity is trivial, meaning the "
    "formal statement, protocol, or target is pinned by the contract or directly "
    "comparable to the problem statement. Score 0 does not require that CI "
    "exists; manual execution of a fixed procedure stays 0. When specification "
    "fidelity is not trivial, count it as residual work: verifying that a formal "
    "statement faithfully encodes the problem is itself derivation review. "
    "Scores 1-3: the residual is a few independent, local, standard reasoning "
    "units, each checkable at a glance. Scores 4-6: the residual contains "
    "connected derivations whose steps depend on one another, or specification "
    "fidelity itself requires substantial reconstruction. Scores 7-9: the "
    "residual is a long, fragile, or novel chain, or requires reviewing "
    "substantial code for correctness rather than running it. Score 10: the "
    "essential claim cannot be decomposed into independently checkable units. "
    "Do not move burden into an unverified specification gap to lower the "
    "score. Do not invent a proxy benchmark or weaken the scientific target. A "
    "single finite instance does not refute a uniform or asymptotic claim when "
    "falsity needs an infinite family or limiting argument. CI is tracked "
    "separately: it records how much of the delegable checking has been "
    "automated, not the structural difficulty. CI cannot lower the score, but a "
    "better contract design, such as required certificates or pinned formal "
    "statements, can."
)


IMPORTANCE_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "unassessed": 3,
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
    "review-heavy": 1,
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


def verification_limit(record: dict[str, Any]) -> int:
    return int(
        record.get(
            "max_verification_difficulty",
            DEFAULT_MAX_VERIFICATION_DIFFICULTY,
        )
    )


def ci_feasibility(record: dict[str, Any]) -> str:
    status = str(record.get("ci_status") or "blocked")
    difficulty = int(record.get("verification_difficulty", 10))
    if status == "implemented":
        return "runnable"
    if status == "partial":
        return "partial"
    if status == "pseudocode":
        return "specified"
    if (
        status == "solution-reviewer-only"
        and difficulty <= verification_limit(record)
    ):
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

    difficulty = int(record.get("verification_difficulty", 10))
    if difficulty > verification_limit(record):
        return "review-heavy"

    return "research-ready"


def ranking_rationale(record: dict[str, Any]) -> str:
    lane = ranking_lane(record)
    importance = str(record.get("importance_level") or "unassessed")
    difficulty = int(record.get("verification_difficulty", 10))
    feasibility = ci_feasibility(record)
    timeout = int(record.get("ci_timeout_minutes") or 0)
    speed, _ = timeout_class(timeout)
    return (
        f"{importance} importance; verification difficulty {difficulty}/10; "
        f"{feasibility} acceptance path; {speed} CI timeout; lane={lane}"
    )


def ranking_key(record: dict[str, Any]) -> tuple[Any, ...]:
    lane = ranking_lane(record)
    importance = str(record.get("importance_level") or "unassessed")
    difficulty = int(record.get("verification_difficulty", 10))
    timeout = int(record.get("ci_timeout_minutes") or 0)
    _, speed_order = timeout_class(timeout)
    conclusion = str(record.get("resolution_conclusion") or "unclassified")
    return (
        LANE_ORDER[lane],
        IMPORTANCE_ORDER.get(importance, 4),
        difficulty,
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
