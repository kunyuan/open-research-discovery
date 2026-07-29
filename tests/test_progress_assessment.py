import pytest

from open_research_discovery.progress import progress_assessment


def test_reassessment_flags_require_updated_fields() -> None:
    decision = {
        "audit_status": "partially_resolved",
        "progress_assessment": {
            "major_progress_found": True,
            "effect": "narrows",
            "surviving_core_reassessed": True,
            "importance_reassessed": True,
            "solution_review_reassessed": True,
            "decision": "rewrite-core",
            "derived_problem_ids": [],
        },
    }

    with pytest.raises(ValueError, match="post-progress importance"):
        progress_assessment(decision)

    decision["importance"] = {"motivation": "updated"}
    with pytest.raises(
        ValueError, match="post-progress solution_review_contract"
    ):
        progress_assessment(decision)


def test_explicit_post_progress_reassessment_is_preserved() -> None:
    assessment = {
        "major_progress_found": True,
        "effect": "narrows",
        "surviving_core_reassessed": True,
        "importance_reassessed": True,
        "solution_review_reassessed": True,
        "decision": "rewrite-core",
        "derived_problem_ids": [],
    }
    decision = {
        "audit_status": "partially_resolved",
        "progress_assessment": assessment,
        "importance": {"motivation": "updated"},
        "solution_review_contract": {"verification_difficulty": 0},
    }

    assert progress_assessment(decision) == assessment
