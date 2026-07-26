from __future__ import annotations

import json
from pathlib import Path


CASES = json.loads(
    (
        Path(__file__).parent
        / "fixtures"
        / "solution_review_scope_cases.json"
    ).read_text(encoding="utf-8")
)


def test_solution_review_scope_casebook_fixture_is_complete() -> None:
    required = {
        "id",
        "source_statement",
        "proposed_result",
        "expected_solution_review_scope",
        "expected_ci_status",
        "rationale",
    }
    assert len(CASES) >= 6
    assert len({case["id"] for case in CASES}) == len(CASES)
    for case in CASES:
        assert required <= set(case)
        assert case["expected_solution_review_scope"] in {
            "result-only",
            "result-and-derivation",
            "expert-intensive",
            "unclassified",
        }
        assert case["expected_ci_status"] in {
            "implemented",
            "partial",
            "pseudocode",
            "solution-reviewer-only",
            "blocked",
        }
        assert all(str(case[field]).strip() for field in required)


def test_proof_format_pair_changes_only_the_delivery_contract() -> None:
    pair = [case for case in CASES if case.get("pair_id") == "proof-format"]
    assert len(pair) == 2
    assert {case["expected_solution_review_scope"] for case in pair} == {
        "result-only",
        "result-and-derivation",
    }
    assert all("theorem T" in case["source_statement"] for case in pair)
