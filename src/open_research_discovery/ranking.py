from __future__ import annotations

from typing import Any, Iterable

from .problem_contract import VERIFICATION_DIFFICULTY_RUBRIC


SIGNIFICANCE_ORDER = {"high": 0, "medium": 1, "low": 2}
CI_ORDER = {"specified": 0, "manual-only": 1, "delegated": 2}


def ci_feasibility(record: dict[str, Any]) -> str:
    status = str(record.get("ci_status") or "manual-only")
    return status if status in CI_ORDER else "manual-only"


def ranking_lane(record: dict[str, Any]) -> str:
    """Every valid contract belongs to the same catalog lane."""

    return "catalog"


def ranking_key(record: dict[str, Any]) -> tuple[Any, ...]:
    significance = str(
        record.get("scientific_significance_level") or "low"
    )
    difficulty = record.get("verification_difficulty")
    return (
        SIGNIFICANCE_ORDER.get(significance, 3),
        int(difficulty) if difficulty is not None else 11,
        CI_ORDER.get(ci_feasibility(record), 3),
        str(record.get("id") or ""),
    )


def ranking_rationale(record: dict[str, Any]) -> str:
    significance = str(
        record.get("scientific_significance_level") or "low"
    )
    difficulty = record.get("verification_difficulty")
    rendered_difficulty = (
        "delegated" if difficulty is None else f"{int(difficulty)}/10"
    )
    return (
        f"scientific significance {significance}; residual verification "
        f"difficulty {rendered_difficulty}; CI {ci_feasibility(record)}"
    )


def annotate_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **record,
        "ranking_lane": ranking_lane(record),
        "ci_feasibility": ci_feasibility(record),
        "ranking_rationale": ranking_rationale(record),
    }


def rank_records(
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [annotate_record(record) for record in sorted(records, key=ranking_key)]
