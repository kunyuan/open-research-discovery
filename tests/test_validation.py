from pathlib import Path

from open_research_discovery.common import dump_json
from open_research_discovery.validation import validate_problem


def _problem_contract() -> dict:
    return {
        "schema_version": "1.0",
        "problem_id": "ORP-0001",
        "parent_problem_id": None,
        "subproblem_ids": [],
        "title": "Example problem",
        "abstract": "Resolve a precise example.",
        "background": "Definitions and known results.",
        "references": ["A source"],
        "previous_progress": ["A special case is known."],
        "problem_statement": "Prove or disprove P for every object in C.",
        "scientific_significance": {
            "mathematics": {
                "level": "medium",
                "description": "Clarifies whether method M extends to C.",
            }
        },
        "solution_difficulty": ["Existing techniques cover only subclasses."],
        "verification_contract": {
            "proof": {
                "contract": "Accept a proof of P for every object in C.",
                "ci_contract": None,
            }
        },
        "verification_difficulty": {
            "score": 5,
            "rationale": "No mechanical proof checker is available.",
        },
    }


def test_minimal_problem_contract_validates(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / "problem.json"
    dump_json(path, _problem_contract())
    assert validate_problem(path, root / "schemas" / "problem.schema.json") == []


def test_workflow_field_is_not_part_of_problem_contract(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    problem = _problem_contract()
    problem["status"] = "ready"
    path = tmp_path / "problem.json"
    dump_json(path, problem)
    errors = validate_problem(path, root / "schemas" / "problem.schema.json")
    assert any("Additional properties" in error for error in errors)


def test_leaf_cannot_delegate_without_subproblems(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    problem = _problem_contract()
    problem["verification_contract"] = None
    problem["verification_difficulty"] = None
    path = tmp_path / "problem.json"
    dump_json(path, problem)
    errors = validate_problem(path, root / "schemas" / "problem.schema.json")
    assert "a problem without subproblems requires verification_contract" in errors
