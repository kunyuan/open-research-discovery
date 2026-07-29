from __future__ import annotations

import json
from pathlib import Path

from open_research_discovery.ranking import VERIFICATION_DIFFICULTY_RUBRIC


CASES = json.loads(
    (
        Path(__file__).parent
        / "fixtures"
        / "verification_difficulty_cases.json"
    ).read_text(encoding="utf-8")
)


def test_verification_difficulty_casebook_fixture_is_complete() -> None:
    required = {
        "id",
        "source_statement",
        "proposed_result",
        "expected_verification_difficulty",
        "expected_ci_status",
        "rationale",
    }
    assert len(CASES) >= 6
    assert len({case["id"] for case in CASES}) == len(CASES)
    for case in CASES:
        assert required <= set(case)
        difficulty = case["expected_verification_difficulty"]
        assert isinstance(difficulty, int) and not isinstance(difficulty, bool)
        assert 0 <= difficulty <= 10
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
    assert {
        case["expected_verification_difficulty"] for case in pair
    } == {0, 10}
    assert all("theorem T" in case["source_statement"] for case in pair)


def test_optimum_is_not_upgraded_by_an_unrequested_certificate() -> None:
    pair = [case for case in CASES if case.get("pair_id") == "optimum-format"]
    assert len(pair) == 2
    by_id = {case["id"]: case for case in pair}
    assert (
        by_id["ordinary-exact-optimum"]["expected_verification_difficulty"]
        == 7
    )
    assert (
        by_id["requested-optimum-certificate"]["expected_verification_difficulty"]
        == 0
    )


def test_executable_comparison_is_separated_from_general_guarantee() -> None:
    pair = [case for case in CASES if case.get("pair_id") == "algorithm-scope"]
    assert len(pair) == 2
    by_id = {case["id"]: case for case in pair}
    assert (
        by_id["executable-comparison"]["expected_verification_difficulty"]
        == 0
    )
    assert (
        by_id["algorithm-complexity"]["expected_verification_difficulty"]
        == 8
    )
    assert "specified code and noise regime" in by_id["executable-comparison"][
        "source_statement"
    ]


def test_parameterized_exact_spectrum_is_zero() -> None:
    case = next(case for case in CASES if case["id"] == "exact-spectrum-family")
    assert case["expected_verification_difficulty"] == 0
    assert "characteristic polynomial" in case["rationale"]


def test_uniform_epsilon_delta_refutation_needs_family_review() -> None:
    case = next(
        case
        for case in CASES
        if case["id"] == "uniform-epsilon-delta-counterexample"
    )
    assert case["expected_verification_difficulty"] == 6


def test_zero_does_not_require_machine_verification() -> None:
    by_id = {case["id"]: case for case in CASES}
    for case_id in (
        "finite-counterexample",
        "exact-solution",
        "exact-spectrum-family",
    ):
        assert by_id[case_id]["expected_verification_difficulty"] == 0


def test_natural_language_proof_is_ten_and_lean_is_zero() -> None:
    by_id = {case["id"]: case for case in CASES}
    assert by_id["ordinary-proof"]["expected_verification_difficulty"] == 10
    assert by_id["requested-lean-proof"]["expected_verification_difficulty"] == 0


def test_zero_definition_does_not_require_ci() -> None:
    assert "Score 0 does not require that CI exists" in (
        VERIFICATION_DIFFICULTY_RUBRIC
    )


def test_holistic_and_nonexistence_residual_scores() -> None:
    by_id = {case["id"]: case for case in CASES}
    assert (
        by_id["broad-robustness-from-finite-benchmark"][
            "expected_verification_difficulty"
        ]
        == 9
    )
    assert (
        by_id["object-and-nonexistence"]["expected_verification_difficulty"]
        == 8
    )


def test_light_residual_anchor_cases() -> None:
    by_id = {case["id"]: case for case in CASES}
    expected = {
        "kkt-certificate-with-duality": 1,
        "pinned-lean-statement-fidelity": 2,
        "reduction-to-solved-problem": 3,
    }
    for case_id, difficulty in expected.items():
        assert by_id[case_id]["expected_verification_difficulty"] == difficulty
