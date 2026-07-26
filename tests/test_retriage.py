from open_research_discovery.retriage import apply_review, progress_for, validate_review_set


def sample_review() -> dict:
    return {
        "importance_level": "high",
        "importance_rationale": "Named bottleneck with downstream consequences.",
        "audit_priority": "high",
        "verification_mode": "machine-checkable",
        "verification_ease": "easy",
        "verification_rationale": "A finite witness has an exact checker.",
        "post_audit_priority": "high",
        "route": "candidate-machine",
    }


def test_partial_resolution_is_retriaged() -> None:
    review = sample_review()
    problem = {
        "importance": {},
        "resolution_audit": {"status": "partially_resolved"},
        "discovery_contract": {},
    }

    updated = apply_review(problem, review, "2026-07-25")

    assert updated["research_triage"]["importance_level"] == "high"
    assert updated["discovery_contract"]["verification_profile"]["mode"] == (
        "machine-checkable"
    )
    assert updated["resolution_audit"]["progress_assessment"] == {
        "major_progress_found": True,
        "effect": "narrows",
        "surviving_core_reassessed": True,
        "importance_reassessed": True,
        "verification_reassessed": True,
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
    errors = validate_review_set({"OMP-0001": sample_review()}, {"OMP-0001", "OMP-0002"})

    assert errors == ["missing review IDs: OMP-0002"]
