from open_research_discovery.ranking import rank_records, ranking_key


def record(
    problem_id: str,
    *,
    status: str = "ready",
    significance: str = "high",
    verification_difficulty: int = 0,
) -> dict[str, object]:
    return {
        "id": problem_id,
        "title": f"Problem {problem_id}",
        "status": status,
        "significance_level": significance,
        "verification_difficulty": verification_difficulty,
    }


def test_open_problems_rank_before_uncertain_and_closed() -> None:
    closed = record("ORP-0001", status="resolved-externally")
    uncertain = record("ORP-0002", status="uncertain")
    open_problem = record("ORP-0003", status="open")
    ranked = rank_records([closed, uncertain, open_problem])
    assert [item["id"] for item in ranked] == ["ORP-0003", "ORP-0002", "ORP-0001"]


def test_lower_verification_difficulty_ranks_first_within_a_lane() -> None:
    easy = record("ORP-0002", significance="medium")
    hard = record("ORP-0001", significance="medium", verification_difficulty=9)
    ranked = rank_records([hard, easy])
    assert [item["id"] for item in ranked] == ["ORP-0002", "ORP-0001"]
    assert "verification difficulty 0/10" in ranked[0]["ranking_rationale"]


def test_significance_dominates_difficulty() -> None:
    high = record("ORP-0001", significance="high", verification_difficulty=9)
    low = record("ORP-0002", significance="low", verification_difficulty=0)
    ranked = rank_records([low, high])
    assert [item["id"] for item in ranked] == ["ORP-0001", "ORP-0002"]


def test_solver_difficulty_metadata_does_not_affect_ranking() -> None:
    first = record("ORP-0001")
    second = dict(first)
    first["searchability"] = 0
    first["feedback_density"] = 0
    first["expected_solve_time"] = "centuries"
    second["searchability"] = 3
    second["feedback_density"] = 3
    second["expected_solve_time"] = "seconds"
    assert ranking_key(first) == ranking_key(second)


def test_missing_fields_fall_back_to_neutral_order() -> None:
    assert rank_records([{"id": "ORP-0001"}])[0]["id"] == "ORP-0001"
