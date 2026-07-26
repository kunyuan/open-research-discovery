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
            "verification_reassessed": True,
            "decision": "rewrite-core",
            "derived_problem_ids": [],
        },
    }

    with pytest.raises(ValueError, match="post-progress importance"):
        progress_assessment(decision)

    decision["importance"] = {"motivation": "updated"}
    with pytest.raises(ValueError, match="post-progress verification_profile"):
        progress_assessment(decision)


def test_explicit_post_progress_reassessment_is_preserved() -> None:
    assessment = {
        "major_progress_found": True,
        "effect": "narrows",
        "surviving_core_reassessed": True,
        "importance_reassessed": True,
        "verification_reassessed": True,
        "decision": "rewrite-core",
        "derived_problem_ids": [],
    }
    decision = {
        "audit_status": "partially_resolved",
        "progress_assessment": assessment,
        "importance": {"motivation": "updated"},
        "verification_profile": {"mode": "machine-checkable"},
    }

    assert progress_assessment(decision) == assessment
