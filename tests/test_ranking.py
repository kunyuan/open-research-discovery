from open_research_discovery.ranking import (
    ci_feasibility,
    rank_records,
    ranking_key,
    ranking_lane,
)


def record(
    problem_id: str,
    *,
    significance: str = "high",
    verification_difficulty: int | None = 0,
    ci_status: str = "specified",
) -> dict[str, object]:
    return {
        "id": problem_id,
        "title": f"Problem {problem_id}",
        "scientific_significance_level": significance,
        "verification_difficulty": verification_difficulty,
        "ci_status": ci_status,
    }


def test_significance_ranks_before_verification_difficulty() -> None:
    medium = record("ORP-0002", significance="medium", verification_difficulty=0)
    high = record("ORP-0001", significance="high", verification_difficulty=9)
    ranked = rank_records([medium, high])
    assert [item["id"] for item in ranked] == ["ORP-0001", "ORP-0002"]


def test_verification_difficulty_is_a_score_not_a_gate() -> None:
    assert ranking_lane(record("ORP-0001", verification_difficulty=0)) == "catalog"
    assert ranking_lane(record("ORP-0002", verification_difficulty=10)) == "catalog"


def test_ci_description_is_not_a_gate() -> None:
    manual = record("ORP-0001", ci_status="manual-only")
    specified = record("ORP-0002", ci_status="specified")
    assert ci_feasibility(manual) == "manual-only"
    assert ci_feasibility(specified) == "specified"
    assert ranking_lane(manual) == ranking_lane(specified) == "catalog"


def test_parent_delegation_sorts_after_scored_peer_only_as_tie_break() -> None:
    delegated = record("ORP-0002", verification_difficulty=None, ci_status="delegated")
    leaf = record("ORP-0001", verification_difficulty=10)
    assert ranking_key(leaf) < ranking_key(delegated)
