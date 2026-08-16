from __future__ import annotations

from typing import Any, Iterable


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
    "exists; manual execution of a fixed procedure stays 0. Calibrate an exact "
    "solution to score 2, rather than 0, when its practical acceptance path "
    "relies primarily on independent numerical reproduction of the original "
    "finite-size model. The light residual consists of checking faithful model, "
    "basis, boundary, and observable conventions; numerical precision, "
    "tolerances, and coverage; and exceptional parameter cases. Do not count "
    "the difficulty of discovering the exact solution. When specification "
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

STATUS_ORDER = {
    "ready": 0,
    "open": 0,
    "uncertain": 1,
    "resolved-externally": 2,
    "refuted-externally": 2,
}

SIGNIFICANCE_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "unassessed": 3,
}


def _difficulty(record: dict[str, Any]) -> int:
    value = record.get("verification_difficulty")
    return int(value) if value is not None else 10


def ranking_key(record: dict[str, Any]) -> tuple[Any, ...]:
    """Open problems first, then significance, then reviewer burden."""

    return (
        STATUS_ORDER.get(str(record.get("status") or ""), 3),
        SIGNIFICANCE_ORDER.get(
            str(record.get("significance_level") or "unassessed"), 3
        ),
        _difficulty(record),
        str(record.get("id") or ""),
    )


def ranking_rationale(record: dict[str, Any]) -> str:
    significance = str(record.get("significance_level") or "unassessed")
    difficulty = _difficulty(record)
    status = str(record.get("status") or "")
    return (
        f"{significance} significance; verification difficulty "
        f"{difficulty}/10; status={status}"
    )


def annotate_record(record: dict[str, Any]) -> dict[str, Any]:
    return {**record, "ranking_rationale": ranking_rationale(record)}


def rank_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [annotate_record(record) for record in sorted(records, key=ranking_key)]
