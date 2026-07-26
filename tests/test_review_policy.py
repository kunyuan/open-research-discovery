from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_research_discovery.review_policy import (
    RouteContractError,
    review_scope_for,
    validate_route_contract,
)


def _cases() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "review_scope_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["id"])
def test_review_scope_regression_matrix(case: dict) -> None:
    decision = case["decision"]
    assert review_scope_for(decision["acceptance_obligations"]) == decision[
        "review_scope"
    ]
    validate_route_contract(case["candidate"], decision)


def test_formal_proof_metamorphic_pair_changes_only_source_contract() -> None:
    cases = {case["id"]: case for case in _cases()}
    ordinary = cases["ordinary-proof"]
    formal = cases["source-requested-formal-proof"]

    assert ordinary["pair_id"] == formal["pair_id"]
    assert (
        ordinary["candidate"]["canonical_statement"]
        == formal["candidate"]["canonical_statement"]
    )
    ordinary_support = ordinary["candidate"]["source_support"][0]
    formal_support = formal["candidate"]["source_support"][0]
    assert ordinary_support["source_key"] == formal_support["source_key"]
    assert set(ordinary_support) == set(formal_support)
    assert ordinary_support["formal_proof_requested"] is False
    assert formal_support["formal_proof_requested"] is True
    assert ordinary["decision"]["review_scope"] == "result-and-derivation"
    assert formal["decision"]["review_scope"] == "result-only"


def test_ordinary_proof_cannot_be_relabelled_as_source_requested_formal() -> None:
    case = next(case for case in _cases() if case["id"] == "ordinary-proof")
    invalid = json.loads(json.dumps(case["decision"]))
    invalid["review_scope"] = "result-only"
    invalid["acceptance_obligations"][0][
        "kind"
    ] = "source-requested-formal-proof"

    with pytest.raises(RouteContractError, match="source does not request"):
        validate_route_contract(case["candidate"], invalid)


def test_lean_cannot_be_disguised_as_a_direct_certificate() -> None:
    case = next(case for case in _cases() if case["id"] == "ordinary-proof")
    invalid = json.loads(json.dumps(case["decision"]))
    invalid["artifact_type"] = "formal-proof"
    invalid["uses_proof_assistant"] = True
    invalid["review_scope"] = "result-only"
    invalid["acceptance_obligations"][0]["kind"] = "direct-artifact"

    with pytest.raises(
        RouteContractError,
        match="proof-assistant deliverable requires",
    ):
        validate_route_contract(case["candidate"], invalid)


def test_declared_scope_cannot_hide_a_derivation_obligation() -> None:
    case = next(
        case
        for case in _cases()
        if case["id"] == "algorithm-with-complexity-proof"
    )
    invalid = json.loads(json.dumps(case["decision"]))
    invalid["review_scope"] = "result-only"

    with pytest.raises(RouteContractError, match="expected 'result-and-derivation'"):
        validate_route_contract(case["candidate"], invalid)


def test_acceptance_obligation_must_copy_the_source_excerpt_exactly() -> None:
    case = next(
        case for case in _cases() if case["id"] == "finite-counterexample"
    )
    invalid = json.loads(json.dumps(case["decision"]))
    invalid["acceptance_obligations"][0][
        "exact_excerpt"
    ] = "A sharpened conjecture invented by the agent."

    with pytest.raises(RouteContractError, match="exactly match"):
        validate_route_contract(case["candidate"], invalid)
