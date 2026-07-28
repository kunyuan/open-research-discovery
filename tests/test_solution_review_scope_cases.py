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


def test_optimum_is_not_upgraded_by_an_unrequested_certificate() -> None:
    pair = [case for case in CASES if case.get("pair_id") == "optimum-format"]
    assert len(pair) == 2
    by_id = {case["id"]: case for case in pair}
    assert (
        by_id["ordinary-exact-optimum"]["expected_solution_review_scope"]
        == "result-and-derivation"
    )
    assert (
        by_id["requested-optimum-certificate"]["expected_solution_review_scope"]
        == "result-only"
    )


def test_executable_comparison_is_separated_from_general_guarantee() -> None:
    pair = [case for case in CASES if case.get("pair_id") == "algorithm-scope"]
    assert len(pair) == 2
    by_id = {case["id"]: case for case in pair}
    assert (
        by_id["executable-comparison"]["expected_solution_review_scope"]
        == "result-only"
    )
    assert (
        by_id["algorithm-complexity"]["expected_solution_review_scope"]
        == "result-and-derivation"
    )
    assert "specified code and noise regime" in by_id["executable-comparison"][
        "source_statement"
    ]


def test_parameterized_exact_spectrum_is_result_only() -> None:
    case = next(case for case in CASES if case["id"] == "exact-spectrum-family")
    assert case["expected_solution_review_scope"] == "result-only"
    assert "characteristic polynomial" in case["rationale"]


def test_uniform_epsilon_delta_refutation_needs_family_review() -> None:
    case = next(
        case
        for case in CASES
        if case["id"] == "uniform-epsilon-delta-counterexample"
    )
    assert case["expected_solution_review_scope"] == "result-and-derivation"
    assert "No single finite instance" in case["rationale"]
