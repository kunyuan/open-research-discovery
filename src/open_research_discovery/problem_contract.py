from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from .common import dump_json


SCHEMA_VERSION = "1.0"

README_SECTIONS = (
    "Background",
    "Problem Statement",
    "Scientific Significance",
    "Answer Types",
    "Verification Standard",
    "Current Progress",
    "References",
)

SCIENTIFIC_SIGNIFICANCE_RUBRIC = (
    "Classify each affected field separately: high means a direct change to "
    "core understanding, methods, or capability; medium means clear progress "
    "or material downstream impact; low means local, indirect, or incremental "
    "impact. State concretely what changes."
)

VERIFICATION_DIFFICULTY_RUBRIC = (
    "Assign one overall 0-10 score across every answer type. First remove all "
    "parts checkable by CI, formal checkers, tests, substitution, finite "
    "enumeration, replay, or certificates, even if the automation is not yet "
    "implemented. Score only residual Agent or human judgment: 0 none; 1-3 a "
    "few local standard checks; 4-6 connected derivations or substantial "
    "problem-answer correspondence work; 7-9 long, fragile, or novel reasoning "
    "or substantial code review; 10 holistic expert judgment. This measures "
    "verification difficulty, not solution difficulty, and is not a gate. "
    "Score 0 does not require that CI exists or has been implemented."
)


class ProblemContractError(ValueError):
    """The supplied Problem Contract is invalid."""


def default_schema_path(repository_root: Path) -> Path:
    return repository_root / "schemas" / "problem.schema.json"


def load_problem_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProblemContractError("problem contract must be a JSON object")
    return value


def validate_problem_contract(
    contract: dict[str, Any], schema_path: Path
) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    findings = sorted(
        Draft202012Validator(schema).iter_errors(contract),
        key=lambda error: list(error.path),
    )
    errors = [
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in findings
    ]
    verification = contract.get("verification_contract")
    difficulty = contract.get("verification_difficulty")
    children = contract.get("subproblem_ids") or []
    if verification is None and not children:
        errors.append(
            "a problem without subproblems requires verification_contract"
        )
    if verification is None and difficulty is not None:
        errors.append(
            "verification_difficulty must be null when verification_contract is null"
        )
    if verification is not None and difficulty is None:
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


def _texts(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def contract_to_agent_content(contract: dict[str, Any]) -> dict[str, Any]:
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
        "references": list(contract["references"]),
        "previous_progress": list(contract["previous_progress"]),
        "problem_statement": contract["problem_statement"],
        "scientific_significance": [
            {"field": field, **impact}
            for field, impact in contract["scientific_significance"].items()
        ],
        "solution_difficulty": list(contract["solution_difficulty"]),
        "verification_contracts": [
            {"answer_type": answer_type, **value}
            for answer_type, value in (
                contract.get("verification_contract") or {}
            ).items()
        ],
        "verification_difficulty_score": difficulty["score"],
        "verification_difficulty_rationale": difficulty["rationale"],
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
    verification: dict[str, Any] = {}
    for item in content["verification_contracts"]:
        answer_type = str(item["answer_type"]).strip()
        if answer_type in verification:
            raise ProblemContractError(
                f"duplicate verification answer type: {answer_type}"
            )
        verification[answer_type] = {
            "contract": str(item["contract"]).strip(),
            "ci_contract": str(item["ci_contract"] or "").strip() or None,
        }
    contract = {
        "schema_version": SCHEMA_VERSION,
        "problem_id": problem_id,
        "parent_problem_id": str(content["parent_problem_id"]).strip() or None,
        "subproblem_ids": _texts(content["subproblem_ids"]),
        "title": str(content["title"]).strip(),
        "abstract": str(content["abstract"]).strip(),
        "background": str(content["background"]).strip(),
        "references": _texts(content["references"]),
        "previous_progress": _texts(content["previous_progress"]),
        "problem_statement": str(content["problem_statement"]).strip(),
        "scientific_significance": significance,
        "solution_difficulty": _texts(content["solution_difficulty"]),
        "verification_contract": verification or None,
        "verification_difficulty": (
            {
                "score": int(content["verification_difficulty_score"]),
                "rationale": str(
                    content["verification_difficulty_rationale"]
                ).strip(),
            }
            if verification
            else None
        ),
    }
    require_valid_problem_contract(contract, schema_path)
    return contract


def problem_contract_from_research(
    *,
    problem_id: str,
    candidate: dict[str, Any],
    assessment: dict[str, Any],
    schema_path: Path,
) -> dict[str, Any]:
    """Project a campaign Research artifact onto the public 14-field contract.

    Campaign evidence, status judgments, routing, and compute estimates remain
    in the run directory. Only values required to state and verify the problem
    cross this boundary.
    """

    draft = assessment["problem"]
    question = draft["question"]
    audit = draft["resolution_audit"]
    importance = draft["importance"]
    significance = draft["scientific_significance"]
    title = draft["title"]
    statement = audit.get("surviving_open_core") or question["canonical_statement"]
    background_parts = [*question.get("definitions", []), question.get("scope")]
    previous_progress = [importance.get("current_best_result")]
    significance_description = " ".join(
        str(item.get("description") or "")
        for item in significance.values()
    )
    verification = draft["verification_contract"]
    verification_score = draft["verification_difficulty"]["score"]
    verification_rationale = draft["verification_difficulty"]["rationale"]
    solution_difficulty = draft["solution_difficulty"]
    evidence = audit.get("evidence") or []
    references = []
    for item in evidence:
        parts = _texts(
            [
                item.get("title") or item.get("citation"),
                item.get("identifier"),
                item.get("url"),
            ]
        )
        if parts:
            references.append(" — ".join(parts))
    for source in candidate.get("source_records") or candidate.get(
        "source_open_questions"
    ) or []:
        parts = _texts(
            [
                source.get("paper_title"),
                source.get("paper_doi"),
                source.get("source_url"),
            ]
        )
        if parts:
            references.append(" — ".join(parts))
    contract = {
        "schema_version": SCHEMA_VERSION,
        "problem_id": problem_id,
        "parent_problem_id": None,
        "subproblem_ids": [],
        "title": str(title).strip(),
        "abstract": str(
            significance_description or statement
        ).strip(),
        "background": "\n\n".join(_texts(background_parts)),
        "references": _texts(references),
        "previous_progress": _texts(previous_progress),
        "problem_statement": str(statement).strip(),
        "scientific_significance": significance,
        "solution_difficulty": _texts(solution_difficulty),
        "verification_contract": verification,
        "verification_difficulty": {
            "score": int(verification_score),
            "rationale": str(verification_rationale).strip(),
        },
    }
    require_valid_problem_contract(contract, schema_path)
    return contract


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
        "### Solution difficulty",
        "",
        *(
            [f"- {item}" for item in contract["solution_difficulty"]]
            or ["- Delegated to subproblems."]
        ),
        "",
        "## Problem Statement",
        "",
        str(contract["problem_statement"]),
        "",
        "## Scientific Significance",
        "",
    ]
    for field, impact in contract["scientific_significance"].items():
        lines.append(f"- **{field} — {impact['level']}**: {impact['description']}")
    lines.extend(["", "## Answer Types", ""])
    verification = contract.get("verification_contract")
    if verification is None:
        lines.append("- Verification is delegated to the listed subproblems.")
    else:
        lines.extend(f"- `{answer_type}`" for answer_type in verification)
    lines.extend(
        [
            "",
            "## Verification Standard",
            "",
            "The contracts below evaluate answers to the Problem Statement; they do not narrow it.",
            "",
        ]
    )
    if verification is None:
        lines.append("Verification is delegated to the listed subproblems.")
    else:
        for answer_type, value in verification.items():
            lines.extend(
                [
                    f"### {answer_type}",
                    "",
                    value["contract"],
                    "",
                    "**CI contract:**",
                    "",
                    value["ci_contract"] or "No CI contract is defined.",
                    "",
                ]
            )
    lines.extend(["### Overall verification difficulty", ""])
    difficulty = contract.get("verification_difficulty")
    if difficulty is None:
        lines.append("Verification is delegated to the listed subproblems.")
    else:
        lines.extend(
            [f"Overall score: `{difficulty['score']}/10`.", "", difficulty["rationale"]]
        )
    lines.extend(["", "## Current Progress", ""])
    lines.extend(f"- {item}" for item in contract["previous_progress"])
    if not contract["previous_progress"]:
        lines.append("- None recorded.")
    lines.extend(["", "### Problem decomposition", ""])
    parent = contract.get("parent_problem_id")
    lines.append(f"- Parent problem: `{parent}`" if parent else "- Parent problem: none")
    children = contract.get("subproblem_ids") or []
    lines.extend(f"- Subproblem: `{item}`" for item in children)
    if not children:
        lines.append("- Subproblems: none")
    lines.extend(["", "## References", ""])
    lines.extend(f"- {item}" for item in contract["references"])
    if not contract["references"]:
        lines.append("- None recorded.")
    return "\n".join(lines).rstrip() + "\n"


def validate_problem_readme(
    path: Path, contract: dict[str, Any] | None = None
) -> list[str]:
    if not path.is_file():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    positions: list[int] = []
    for section in README_SECTIONS:
        heading = f"## {section}"
        position = text.find(heading)
        if position < 0:
            errors.append(f"README.md is missing {heading}")
        positions.append(position)
    present = [position for position in positions if position >= 0]
    if present != sorted(present):
        errors.append("README.md sections are out of order")
    if "\\(" in text or "\\)" in text:
        errors.append("inline math must use $ ... $")
    if "\\[" in text or "\\]" in text:
        errors.append("display math must use $$ ... $$")
    if contract is not None and text != render_problem_contract_readme(contract):
        errors.append("README.md is not the deterministic projection of problem.json")
    return errors


def write_problem_contract_repository(
    *, contract: dict[str, Any], schema_path: Path, out_dir: Path
) -> Path:
    require_valid_problem_contract(contract, schema_path)
    if not out_dir.is_dir():
        raise FileNotFoundError(f"repository directory does not exist: {out_dir}")
    dump_json(out_dir / "problem.json", contract)
    (out_dir / "README.md").write_text(
        render_problem_contract_readme(contract), encoding="utf-8"
    )
    return out_dir


def materialize_problem_contract_repository(
    *, contract: dict[str, Any], schema_path: Path, out_dir: Path
) -> Path:
    if out_dir.exists():
        raise FileExistsError(f"output path already exists: {out_dir}")
    out_dir.mkdir(parents=True)
    return write_problem_contract_repository(
        contract=contract, schema_path=schema_path, out_dir=out_dir
    )
