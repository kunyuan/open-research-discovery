from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .common import dump_json


SCHEMA_VERSION = "1.0"

SCIENTIFIC_SIGNIFICANCE_RUBRIC = (
    "Classify each affected field separately. high means solving the problem "
    "would directly change a core understanding, method, or capability; medium "
    "means clear progress or material downstream impact; low means a local, "
    "indirect, or incremental effect. Every entry must say concretely what changes."
    " Breadth alone is not impact: a narrow result may be high-impact when it "
    "removes a load-bearing bottleneck, while a broad but consequence-free slogan "
    "may be low-impact."
)

VERIFICATION_DIFFICULTY_RUBRIC = (
    "Assign one overall score after considering every answer type in "
    "verification_contract. For each answer type, first remove everything that "
    "can be checked by CI, a formal checker, tests, substitution, finite "
    "enumeration, replay, certificates, or another clear mechanical procedure. "
    "Remove mechanically checkable work even when its CI implementation does not "
    "yet exist. Score 0 does not require that CI exists. Score only the residual "
    "Agent or human Reviewer judgment: 0 means "
    "none remains; 1-3 means a few independent local standard checks; 4-6 means "
    "connected derivations or substantial reconstruction of the correspondence "
    "between the problem and answer; 7-9 means long, fragile, or novel reasoning "
    "or substantial code review; 10 means a load-bearing claim requires holistic "
    "expert judgment. The score measures review difficulty, not solution difficulty, "
    "and is not a publication threshold."
)


class ProblemContractError(ValueError):
    """A problem contract is invalid or cannot be constructed faithfully."""


def default_schema_path(repository_root: Path) -> Path:
    return repository_root / "schemas" / "problem-contract.schema.json"


def load_problem_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProblemContractError("problem contract must be a JSON object")
    return value


def validate_problem_contract(
    contract: dict[str, Any], schema_path: Path
) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    findings = sorted(
        validator.iter_errors(contract), key=lambda error: list(error.path)
    )
    errors = [
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in findings
    ]

    contracts = contract.get("verification_contract")
    difficulty = contract.get("verification_difficulty")
    subproblems = contract.get("subproblem_ids") or []
    if contracts is None and not subproblems:
        errors.append(
            "a problem without subproblems requires verification_contract"
        )
    if contracts is None and difficulty is not None:
        errors.append(
            "verification_difficulty must be null when verification_contract is null"
        )
    if contracts is not None and difficulty is None:
        errors.append(
            "verification_difficulty is required when verification_contract is present"
        )
    return errors


def require_valid_problem_contract(
    contract: dict[str, Any], schema_path: Path
) -> None:
    errors = validate_problem_contract(contract, schema_path)
    if errors:
        raise ProblemContractError("; ".join(errors))


def dump_problem_contract(
    path: Path, contract: dict[str, Any], schema_path: Path
) -> None:
    require_valid_problem_contract(contract, schema_path)
    dump_json(path, contract)


def _unique_text(values: list[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _reference_strings(assessment: dict[str, Any]) -> list[str]:
    explicit = _unique_text(list(assessment.get("references") or []))
    if explicit:
        return explicit
    references: list[str] = []
    for evidence in assessment.get("evidence") or []:
        title = str(evidence.get("title") or "").strip()
        identifier = str(evidence.get("identifier") or "").strip()
        url = str(evidence.get("url") or "").strip()
        parts = [part for part in (title, identifier, url) if part]
        if parts:
            references.append(" — ".join(parts))
    return _unique_text(references)


def _infer_answer_type(expected_result: str) -> str:
    lowered = expected_result.lower()
    for needle, answer_type in (
        ("counterexample", "counterexample"),
        ("exact solution", "exact_solution"),
        ("proof", "proof"),
        ("experiment", "experiment"),
        ("dataset", "dataset"),
        ("algorithm", "algorithm"),
        ("code", "code"),
        ("construction", "construction"),
    ):
        if needle in lowered:
            return answer_type
    return "result"


def _verification_contracts(assessment: dict[str, Any]) -> dict[str, Any]:
    entries = list(assessment.get("verification_contracts") or [])
    if not entries:
        expected = str(assessment.get("expected_result") or "").strip()
        contract = str(assessment.get("acceptance_boundary") or "").strip()
        if expected:
            contract = f"{expected} {contract}".strip()
        ci_steps = _unique_text(list(assessment.get("ci_pseudocode") or []))
        ci_contract = " ".join(ci_steps) if ci_steps else None
        entries = [
            {
                "answer_type": _infer_answer_type(expected),
                "contract": contract,
                "ci_contract": ci_contract or "",
            }
        ]

    contracts: dict[str, Any] = {}
    for entry in entries:
        answer_type = str(entry.get("answer_type") or "").strip()
        if not answer_type:
            raise ProblemContractError("verification contract answer_type is empty")
        if answer_type in contracts:
            raise ProblemContractError(
                f"duplicate verification contract answer type: {answer_type}"
            )
        ci_contract = str(entry.get("ci_contract") or "").strip() or None
        contracts[answer_type] = {
            "contract": str(entry.get("contract") or "").strip(),
            "ci_contract": ci_contract,
        }
    return contracts


def problem_contract_from_assessment(
    *,
    problem_id: str,
    candidate: dict[str, Any],
    assessment: dict[str, Any],
    schema_path: Path,
    parent_problem_id: str | None = None,
    subproblem_ids: list[str] | None = None,
) -> dict[str, Any]:
    significance_entries = list(
        assessment.get("scientific_significance_areas") or []
    )
    if not significance_entries:
        significance_entries = [
            {
                "field": str(candidate.get("domain") or "research"),
                "level": str(assessment.get("importance_level") or "low"),
                "description": str(
                    assessment.get("consequences_of_progress")
                    or assessment.get("importance_motivation")
                    or ""
                ),
            }
        ]
    significance: dict[str, Any] = {}
    for entry in significance_entries:
        field = str(entry.get("field") or "").strip()
        if not field:
            raise ProblemContractError("scientific significance field is empty")
        if field in significance:
            raise ProblemContractError(
                f"duplicate scientific significance field: {field}"
            )
        significance[field] = {
            "level": str(entry.get("level") or ""),
            "description": str(entry.get("description") or "").strip(),
        }

    statement = str(
        assessment.get("surviving_open_core")
        or assessment.get("canonical_statement")
        or ""
    ).strip()
    abstract = str(assessment.get("abstract") or "").strip()
    if not abstract:
        abstract = " ".join(
            part
            for part in (
                str(assessment.get("importance_motivation") or "").strip(),
                statement,
            )
            if part
        )
    previous_progress = _unique_text(
        list(assessment.get("previous_progress") or [])
    )
    if not previous_progress:
        previous_progress = _unique_text(
            [assessment.get("current_best_result")]
        )
    solution_difficulty = _unique_text(
        list(assessment.get("solution_difficulty") or [])
    )
    if not solution_difficulty:
        solution_difficulty = _unique_text(
            [(assessment.get("compute") or {}).get("notes")]
        )

    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "problem_id": problem_id,
        "parent_problem_id": parent_problem_id,
        "subproblem_ids": list(subproblem_ids or []),
        "title": str(assessment.get("canonical_title") or "").strip(),
        "abstract": abstract,
        "background": "\n\n".join(
            _unique_text(
                [
                    *list(assessment.get("definitions") or []),
                    assessment.get("scope"),
                ]
            )
        ),
        "references": _reference_strings(assessment),
        "previous_progress": previous_progress,
        "problem_statement": statement,
        "scientific_significance": significance,
        "solution_difficulty": solution_difficulty,
        "verification_contract": _verification_contracts(assessment),
        "verification_difficulty": {
            "score": int(assessment.get("verification_difficulty", 10)),
            "rationale": str(
                assessment.get("verification_difficulty_rationale") or ""
            ).strip(),
        },
    }
    require_valid_problem_contract(contract, schema_path)
    return contract


def contract_to_agent_content(contract: dict[str, Any]) -> dict[str, Any]:
    significance = [
        {
            "field": field,
            "level": value["level"],
            "description": value["description"],
        }
        for field, value in (contract.get("scientific_significance") or {}).items()
    ]
    verification = [
        {
            "answer_type": answer_type,
            "contract": value["contract"],
            "ci_contract": value.get("ci_contract") or "",
        }
        for answer_type, value in (contract.get("verification_contract") or {}).items()
    ]
    difficulty = contract.get("verification_difficulty") or {
        "score": 0,
        "rationale": "Delegated to subproblems.",
    }
    return {
        "parent_problem_id": contract.get("parent_problem_id") or "",
        "subproblem_ids": list(contract.get("subproblem_ids") or []),
        "title": contract["title"],
        "abstract": contract["abstract"],
        "background": contract["background"],
        "references": list(contract.get("references") or []),
        "previous_progress": list(contract.get("previous_progress") or []),
        "problem_statement": contract["problem_statement"],
        "scientific_significance": significance,
        "solution_difficulty": list(contract.get("solution_difficulty") or []),
        "verification_contracts": verification,
        "verification_difficulty_score": int(difficulty["score"]),
        "verification_difficulty_rationale": str(difficulty["rationale"]),
    }


def problem_contract_from_agent_content(
    *,
    problem_id: str,
    content: dict[str, Any],
    schema_path: Path,
) -> dict[str, Any]:
    significance: dict[str, Any] = {}
    for item in content["scientific_significance"]:
        field = str(item["field"]).strip()
        if field in significance:
            raise ProblemContractError(
                f"duplicate scientific significance field: {field}"
            )
        significance[field] = {
            "level": item["level"],
            "description": str(item["description"]).strip(),
        }
    contracts: dict[str, Any] = {}
    for item in content["verification_contracts"]:
        answer_type = str(item["answer_type"]).strip()
        if answer_type in contracts:
            raise ProblemContractError(
                f"duplicate verification contract answer type: {answer_type}"
            )
        contracts[answer_type] = {
            "contract": str(item["contract"]).strip(),
            "ci_contract": str(item["ci_contract"]).strip() or None,
        }
    subproblem_ids = list(content["subproblem_ids"])
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "problem_id": problem_id,
        "parent_problem_id": str(content["parent_problem_id"]).strip() or None,
        "subproblem_ids": subproblem_ids,
        "title": str(content["title"]).strip(),
        "abstract": str(content["abstract"]).strip(),
        "background": str(content["background"]).strip(),
        "references": _unique_text(content["references"]),
        "previous_progress": _unique_text(content["previous_progress"]),
        "problem_statement": str(content["problem_statement"]).strip(),
        "scientific_significance": significance,
        "solution_difficulty": _unique_text(content["solution_difficulty"]),
        "verification_contract": contracts or None,
        "verification_difficulty": (
            {
                "score": int(content["verification_difficulty_score"]),
                "rationale": str(
                    content["verification_difficulty_rationale"]
                ).strip(),
            }
            if contracts
            else None
        ),
    }
    require_valid_problem_contract(contract, schema_path)
    return contract


def _bullets(values: list[object], empty: str = "None recorded.") -> list[str]:
    rendered = _unique_text(values)
    return [f"- {value}" for value in rendered] or [f"- {empty}"]


def render_problem_contract_readme(contract: dict[str, Any]) -> str:
    lines = [
        f"# {contract['title']}",
        "",
        str(contract["abstract"]),
        "",
        f"Problem ID: `{contract['problem_id']}`",
        "",
        "## Background",
        "",
        str(contract["background"]),
        "",
        "## Problem Statement",
        "",
        str(contract["problem_statement"]),
        "",
        "## Scientific Significance",
        "",
    ]
    for field, impact in contract["scientific_significance"].items():
        lines.append(
            f"- **{field} — {impact['level']}**: {impact['description']}"
        )
    lines.extend(["", "## Previous Progress", ""])
    lines.extend(_bullets(contract["previous_progress"]))
    lines.extend(["", "## Solution Difficulty", ""])
    lines.extend(_bullets(contract["solution_difficulty"]))
    lines.extend(["", "## Verification Contracts", ""])
    contracts = contract.get("verification_contract")
    if contracts is None:
        lines.append("Verification is delegated to the listed subproblems.")
    else:
        for answer_type, value in contracts.items():
            lines.extend(
                [
                    f"### {answer_type}",
                    "",
                    str(value["contract"]),
                    "",
                    "**CI contract:**",
                    "",
                    str(value.get("ci_contract") or "No CI contract is defined."),
                    "",
                ]
            )
        if lines[-1] == "":
            lines.pop()
    lines.extend(["", "## Verification Difficulty", ""])
    difficulty = contract.get("verification_difficulty")
    if difficulty is None:
        lines.append("Verification is delegated to the listed subproblems.")
    else:
        lines.extend(
            [
                f"Overall score: `{difficulty['score']}/10`.",
                "",
                str(difficulty["rationale"]),
            ]
        )
    lines.extend(["", "## References", ""])
    lines.extend(_bullets(contract["references"]))
    lines.extend(["", "## Problem Decomposition", ""])
    parent = contract.get("parent_problem_id")
    lines.append(f"- Parent problem: `{parent}`" if parent else "- Parent problem: none")
    subproblems = contract.get("subproblem_ids") or []
    lines.extend(
        [f"- Subproblem: `{problem_id}`" for problem_id in subproblems]
        or ["- Subproblems: none"]
    )
    return "\n".join(lines).rstrip() + "\n"


def validate_problem_contract_readme(path: Path) -> list[str]:
    if not path.is_file():
        return ["missing README.md"]
    text = path.read_text(encoding="utf-8")
    sections = (
        "Background",
        "Problem Statement",
        "Scientific Significance",
        "Previous Progress",
        "Solution Difficulty",
        "Verification Contracts",
        "Verification Difficulty",
        "References",
        "Problem Decomposition",
    )
    return [
        f"README.md is missing section: {section}"
        for section in sections
        if f"## {section}" not in text
    ]


def materialize_problem_contract_repository(
    *,
    contract: dict[str, Any],
    schema_path: Path,
    out_dir: Path,
) -> Path:
    if out_dir.exists():
        raise FileExistsError(f"output path already exists: {out_dir}")
    out_dir.mkdir(parents=True)
    return write_problem_contract_repository(
        contract=contract,
        schema_path=schema_path,
        out_dir=out_dir,
    )


def write_problem_contract_repository(
    *,
    contract: dict[str, Any],
    schema_path: Path,
    out_dir: Path,
) -> Path:
    require_valid_problem_contract(contract, schema_path)
    if not out_dir.is_dir():
        raise FileNotFoundError(f"repository directory does not exist: {out_dir}")
    dump_json(out_dir / "problem.json", contract)
    (out_dir / "README.md").write_text(
        render_problem_contract_readme(contract), encoding="utf-8"
    )
    errors = validate_problem_contract_readme(out_dir / "README.md")
    if errors:
        raise ProblemContractError("; ".join(errors))
    return out_dir
