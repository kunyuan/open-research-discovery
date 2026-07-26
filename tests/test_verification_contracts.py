from __future__ import annotations

from pathlib import Path

from open_research_discovery.verification_contracts import (
    solution_review_and_ci_contracts_for,
    render_ci,
    render_solution_review,
    render_workflow,
)


def problem() -> dict:
    return {
        "id": "ORP-0001",
        "title": "Finite witness",
        "question": {"canonical_statement": "Find a finite witness."},
        "resolution_audit": {
            "status": "still_open",
            "checked_at": "2026-07-26",
        },
        "discovery_contract": {
            "expected_result": "A machine-readable finite witness.",
            "candidate_format": "JSON",
            "success_condition": "Every hypothesis holds and the target fails.",
        },
        "solution_review_contract": {
            "scope": "result-only",
            "checklist": "verifier/solution-review.md",
            "estimated_review_time": "20 minutes",
            "acceptance_boundary": "Check hypotheses and recompute the failure.",
        },
        "ci_contract": {
            "status": "pseudocode",
            "workflow": ".github/workflows/verify.yml",
            "driver": "tools/ci_verify.py",
            "pseudocode": "verifier/ci.md",
            "runner": "ubuntu-latest",
            "estimated_runtime": "5 minutes",
            "timeout_minutes": 10,
        },
    }


def test_contract_for_preserves_explicit_judgments(tmp_path: Path) -> None:
    solution_review, ci = solution_review_and_ci_contracts_for(
        problem(), tmp_path
    )
    assert solution_review["scope"] == "result-only"
    assert solution_review["acceptance_boundary"].startswith(
        "Check hypotheses"
    )
    assert ci["status"] == "pseudocode"
    assert ci["estimated_runtime"] == "5 minutes"


def test_renderers_use_plain_expected_result_without_type_dispatch() -> None:
    item = problem()
    review = render_solution_review(item)
    ci = render_ci(item)
    assert "A machine-readable finite witness." in review
    assert "artifact_type" not in review
    assert "A machine-readable finite witness." in ci
    assert "problem-specific" in ci


def test_missing_ci_contract_does_not_infer_scientific_type(
    tmp_path: Path,
) -> None:
    item = problem()
    item.pop("ci_contract")
    _, ci = solution_review_and_ci_contracts_for(item, tmp_path)
    assert ci["status"] == "blocked"


def test_zero_timeout_means_no_runnable_ci(tmp_path: Path) -> None:
    item = problem()
    item["ci_contract"]["status"] = "blocked"
    item["ci_contract"]["timeout_minutes"] = 0

    _, ci = solution_review_and_ci_contracts_for(item, tmp_path)

    assert ci["timeout_minutes"] == 0
    assert "timeout-minutes: 1" in render_workflow(ci["timeout_minutes"])
