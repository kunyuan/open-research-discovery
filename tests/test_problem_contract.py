from __future__ import annotations

import json
from pathlib import Path

from open_research_discovery.problem_contract import (
    contract_to_agent_content,
    problem_contract_from_agent_content,
    render_problem_contract_readme,
    validate_problem_contract,
)


REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "schemas" / "problem.schema.json"

EXPECTED_FIELDS = {
    "schema_version",
    "problem_id",
    "parent_problem_id",
    "subproblem_ids",
    "title",
    "abstract",
    "background",
    "references",
    "previous_progress",
    "problem_statement",
    "scientific_significance",
    "solution_difficulty",
    "verification_contract",
    "verification_difficulty",
}


def contract() -> dict:
    return {
        "schema_version": "1.0",
        "problem_id": "example-problem",
        "parent_problem_id": None,
        "subproblem_ids": [],
        "title": "A determinate example problem",
        "abstract": "Resolve a precise mathematical boundary case.",
        "background": "All terms in the problem statement are standard.",
        "references": ["Example paper — 10.1234/example"],
        "previous_progress": ["A restricted case has been proved."],
        "problem_statement": "Prove or disprove statement P for every object in C.",
        "scientific_significance": {
            "mathematics": {
                "level": "high",
                "description": "Determines whether method M extends to C.",
            }
        },
        "solution_difficulty": ["Known local arguments do not compose."],
        "verification_contract": {
            "proof": {
                "contract": "Accept a proof deriving P for every object in C.",
                "ci_contract": None,
            },
            "counterexample": {
                "contract": "Accept an explicit member of C for which P fails.",
                "ci_contract": "Parse the witness and check membership in C and failure of P.",
            },
        },
        "verification_difficulty": {
            "score": 6,
            "rationale": "Witness checks are mechanical; a general proof needs connected expert review.",
        },
    }


def test_schema_has_exactly_the_agreed_fields() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["required"]) == EXPECTED_FIELDS
    assert set(schema["properties"]) == EXPECTED_FIELDS
    assert schema["additionalProperties"] is False


def test_contract_rejects_non_schema_workflow_fields() -> None:
    value = contract()
    value["status"] = "ready"
    errors = validate_problem_contract(value, SCHEMA)
    assert any("Additional properties" in error for error in errors)


def test_parent_may_delegate_verification_to_children() -> None:
    value = contract()
    value["subproblem_ids"] = ["example-child"]
    value["solution_difficulty"] = []
    value["verification_contract"] = None
    value["verification_difficulty"] = None
    assert validate_problem_contract(value, SCHEMA) == []


def test_leaf_requires_verification_and_one_residual_score() -> None:
    value = contract()
    value["verification_contract"] = None
    value["verification_difficulty"] = None
    errors = validate_problem_contract(value, SCHEMA)
    assert "a problem without subproblems requires verification_contract" in errors


def test_agent_projection_round_trips_without_extra_fields() -> None:
    original = contract()
    rebuilt = problem_contract_from_agent_content(
        problem_id=original["problem_id"],
        content=contract_to_agent_content(original),
        schema_path=SCHEMA,
    )
    assert rebuilt == original
    assert set(rebuilt) == EXPECTED_FIELDS


def test_readme_is_a_deterministic_seven_section_projection() -> None:
    readme = render_problem_contract_readme(contract())
    expected = [
        "## Background",
        "## Problem Statement",
        "## Scientific Significance",
        "## Answer Types",
        "## Verification Standard",
        "## Current Progress",
        "## References",
    ]
    assert [line for line in readme.splitlines() if line.startswith("## ")] == expected
