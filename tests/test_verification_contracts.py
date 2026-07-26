from pathlib import Path

from open_research_discovery.verification_contracts import (
    contract_for,
    render_ci,
    render_review,
    render_workflow,
)


def problem(mode: str = "machine-checkable", ease: str = "easy") -> dict:
    return {
        "id": "OMP-0001",
        "title": "Concrete finite target",
        "question": {"canonical_statement": "Find a finite object with property P."},
        "resolution_audit": {
            "status": "still_open",
            "checked_at": "2026-07-25",
        },
        "discovery_contract": {
            "artifact_type": "counterexample",
            "candidate_format": "submission/candidate.json",
            "success_condition": "The checker confirms P.",
            "verification_profile": {
                "mode": mode,
                "ease": ease,
                "rationale": "finite",
            },
        },
    }


def test_machine_stub_gets_result_only_pseudocode_contract(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "verifier").mkdir(parents=True)
    (repo / "verifier" / "check.py").write_text("verifier_not_implemented")
    item = problem()
    reviewer, ci = contract_for(item, repo)
    assert reviewer["scope"] == "result-only"
    assert ci["status"] == "pseudocode"
    item["reviewer_contract"] = reviewer
    item["ci_contract"] = ci
    assert "Find a finite object with property P." in render_review(item)
    assert "independently_recompute_violation" in render_ci(item)


def test_implemented_machine_checker_gets_executable_ci(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "verifier").mkdir(parents=True)
    (repo / "verifier" / "check.py").write_text("print('implemented')")
    _, ci = contract_for(problem(), repo)
    assert ci["status"] == "implemented"
    assert "timeout-minutes: 120" in render_workflow(ci["timeout_minutes"])


def test_expert_problem_requires_intensive_review(tmp_path: Path) -> None:
    reviewer, ci = contract_for(
        problem(mode="expert-review", ease="hard"), tmp_path
    )
    assert reviewer["scope"] == "expert-intensive"
    assert reviewer["estimated_review_time"] == "1-3 expert-days"
    assert ci["status"] == "reviewer-only"


def test_cross_disciplinary_artifact_gets_specific_acceptance_checks(
    tmp_path: Path,
) -> None:
    item = problem()
    item["id"] = "ORP-0001"
    item["discovery_contract"]["artifact_type"] = "dataset"
    reviewer, ci = contract_for(item, tmp_path)
    item["reviewer_contract"] = reviewer
    item["ci_contract"] = ci

    assert "schema, provenance, license" in render_review(item)
    assert "load_versioned_dataset_and_provenance" in render_ci(item)
