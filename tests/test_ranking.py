from open_research_discovery.ranking import (
    ci_feasibility,
    rank_records,
    ranking_key,
    ranking_lane,
    timeout_class,
)


def record(
    problem_id: str,
    *,
    importance: str = "high",
    conclusion: str = "confirmed_open",
    resolution: str = "still_open",
    scope: str = "result-only",
    ci_status: str = "implemented",
    timeout: int = 10,
) -> dict[str, object]:
    return {
        "id": problem_id,
        "title": f"Problem {problem_id}",
        "importance_level": importance,
        "resolution_conclusion": conclusion,
        "resolution_status": resolution,
        "review_scope": scope,
        "ci_status": ci_status,
        "ci_timeout_minutes": timeout,
        "ci_estimated_runtime": "under ten minutes",
    }


def test_ready_result_only_problem_ranks_before_expert_problem() -> None:
    ready = record("OMP-0002", importance="medium")
    expert = record(
        "OMP-0001",
        importance="high",
        scope="expert-intensive",
        ci_status="reviewer-only",
    )
    ranked = rank_records([expert, ready])
    assert [item["id"] for item in ranked] == ["OMP-0002", "OMP-0001"]
    assert ranked[0]["ranking_lane"] == "research-ready"
    assert "result-only review" in ranked[0]["ranking_rationale"]


def test_bounded_llm_review_is_an_explicit_accepted_lane() -> None:
    item = record(
        "OMP-0001",
        ci_status="reviewer-only",
    )
    assert ci_feasibility(item) == "bounded-llm"
    assert ranking_lane(item) == "research-ready"


def test_pseudocode_machine_checker_enters_verifier_queue() -> None:
    item = record("OMP-0001", ci_status="pseudocode", timeout=30)
    assert ranking_lane(item) == "research-ready"
    assert rank_records([item], queue="verifier")[0]["ci_timeout_class"] == (
        "moderate"
    )


def test_blocked_ci_does_not_block_result_only_research() -> None:
    item = record("OMP-0001", ci_status="blocked")
    assert ci_feasibility(item) == "blocked"
    assert ranking_lane(item) == "research-ready"


def test_ci_is_a_bonus_without_changing_research_readiness() -> None:
    implemented = record("OMP-0001", ci_status="implemented")
    specified = record("OMP-0001", ci_status="pseudocode")
    assert ranking_lane(implemented) == "research-ready"
    assert ranking_lane(specified) == "research-ready"
    assert ranking_key(implemented) < ranking_key(specified)


def test_verifier_queue_prioritizes_unimplemented_checkers() -> None:
    implemented = record("OMP-0001", ci_status="implemented")
    specified = record("OMP-0002", ci_status="pseudocode")
    partial = record("OMP-0003", ci_status="partial")
    ranked = rank_records(
        [implemented, specified, partial], queue="verifier"
    )
    assert [item["id"] for item in ranked] == [
        "OMP-0003",
        "OMP-0002",
        "OMP-0001",
    ]


def test_uncertain_and_closed_items_are_labelled_not_dropped() -> None:
    uncertain = record(
        "OMP-0001",
        conclusion="needs_reformulation",
        resolution="uncertain",
    )
    closed = record(
        "OMP-0002", conclusion="resolved", resolution="resolved"
    )
    ranked = rank_records([closed, uncertain])
    assert [item["ranking_lane"] for item in ranked] == [
        "status-check",
        "closed",
    ]


def test_solver_difficulty_metadata_does_not_affect_ranking_dimensions() -> None:
    first = record("OMP-0001")
    second = dict(first)
    first["searchability"] = 0
    first["feedback_density"] = 0
    first["expected_solve_time"] = "centuries"
    first["post_audit_priority"] = "hold"
    first["route"] = "manual-review"
    second["searchability"] = 3
    second["feedback_density"] = 3
    second["expected_solve_time"] = "seconds"
    second["post_audit_priority"] = "high"
    second["route"] = "candidate-result"
    assert ranking_key(first) == ranking_key(second)


def test_timeout_classes_use_hard_ci_ceiling() -> None:
    assert timeout_class(10)[0] == "fast"
    assert timeout_class(30)[0] == "moderate"
    assert timeout_class(120)[0] == "slow"
    assert timeout_class(121)[0] == "very-slow"
    assert timeout_class(0)[0] == "unknown"
