from open_research_discovery.retriage import (
    apply_problem_review,
    progress_for,
    validate_problem_review_set,
)


def sample_review() -> dict:
    return {
        "importance_level": "high",
        "importance_rationale": "Named bottleneck with downstream consequences.",
        "audit_priority": "high",
        "post_audit_priority": "high",
        "solution_review_scope": "result-only",
        "estimated_solution_review_time": "20 minutes",
        "acceptance_boundary": "Check the submitted finite witness.",
        "ci_status": "pseudocode",
    }


def test_partial_resolution_is_retriaged() -> None:
    review = sample_review()
    problem = {
        "importance": {},
        "resolution_audit": {"status": "partially_resolved"},
        "solution_review_contract": {},
        "ci_contract": {},
    }

    updated = apply_problem_review(problem, review, "2026-07-25")

    assert updated["research_triage"]["importance_level"] == "high"
    assert updated["solution_review_contract"]["scope"] == "result-only"
    assert updated["research_triage"]["route"] == "candidate-result"
    assert updated["resolution_audit"]["progress_assessment"] == {
        "major_progress_found": True,
        "effect": "narrows",
        "surviving_core_reassessed": True,
        "importance_reassessed": True,
        "solution_review_reassessed": True,
        "decision": "rewrite-core",
        "derived_problem_ids": [],
    }


def test_resolved_problem_can_route_to_derived_audit() -> None:
    review = sample_review() | {
        "progress_decision": "new-derived-problem",
        "derived_problem_ids": ["OMP-0070"],
    }

    assert progress_for("resolved", review)["decision"] == "new-derived-problem"
    assert progress_for("resolved", review)["derived_problem_ids"] == ["OMP-0070"]


def test_review_set_requires_exact_problem_coverage() -> None:
    errors = validate_problem_review_set(
        {"OMP-0001": sample_review()}, {"OMP-0001", "OMP-0002"}
    )

    assert errors == ["missing problem-review IDs: OMP-0002"]
