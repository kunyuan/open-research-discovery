from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .problem_contract import (
    SCIENTIFIC_SIGNIFICANCE_RUBRIC,
    VERIFICATION_DIFFICULTY_RUBRIC,
    contract_to_agent_content,
    dump_problem_contract,
    problem_contract_from_agent_content,
    require_valid_problem_contract,
)


def review_problem_contract(
    *,
    contract: dict[str, Any],
    repository_root: Path,
    runner: Any,
    output_path: Path,
    events_path: Path,
) -> dict[str, Any]:
    schema_path = repository_root / "schemas" / "problem-contract.schema.json"
    require_valid_problem_contract(contract, schema_path)
    prompt = f"""
You are an independent Problem Contract Reviewer. Review only the contract
below. Do not solve the research problem and do not search for new literature.

Check that the title, abstract, background, references, previous progress, and
problem statement are mutually consistent and self-contained. Check that every
scientific-significance entry names a real affected field and states a concrete
effect. Check that the listed solution difficulties are possible solving
obstacles rather than acceptance criteria.

For every answer type in verification_contract, check that its contract states
what must be submitted and gives an unambiguous pass/fail boundary. Check that
its ci_contract describes only a real mechanical check; null is valid when no
such check exists. Then review the single overall verification_difficulty score
across all answer types using this rubric:

{VERIFICATION_DIFFICULTY_RUBRIC}

Scientific significance uses this rubric:

{SCIENTIFIC_SIGNIFICANCE_RUBRIC}

Return accept only when the contract is ready to dispatch. Return rewrite when
the supplied contract can be repaired and provide one concrete rewrite_prompt.
Return reject only when the problem cannot be made dispatchable without
changing its identity or obtaining new evidence.

Problem contract:
{json.dumps(contract, ensure_ascii=False, indent=2)}
""".strip()
    result = runner.run(
        role="problem-contract-reviewer",
        prompt=prompt,
        schema_path=repository_root
        / "schemas"
        / "stages"
        / "problem-contract-review.schema.json",
        output_path=output_path,
        events_path=events_path,
    )
    review = result.output
    if review.get("problem_id") != contract["problem_id"]:
        raise ValueError("Problem Contract Reviewer returned the wrong problem_id")
    return review


def rewrite_problem_contract(
    *,
    contract: dict[str, Any],
    instruction: str,
    repository_root: Path,
    runner: Any,
    agent_output_path: Path,
    events_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    schema_path = repository_root / "schemas" / "problem-contract.schema.json"
    require_valid_problem_contract(contract, schema_path)
    if not instruction.strip():
        raise ValueError("rewrite instruction must not be empty")
    content = contract_to_agent_content(contract)
    prompt = f"""
You are a Problem Contract Rewriter. Rewrite the supplied contract according to
the user instruction while preserving the identity in problem_id. Return the
complete rewritten content, not a patch and not commentary.

Do not add fields outside the Problem Schema. The keys of
verification_contracts are the accepted answer types. Each answer type must
have a concrete acceptance contract and a truthful CI contract; use an empty
string when no mechanical CI is possible. Recompute the one overall
verification-difficulty score after considering every answer type.

Scientific-significance rubric:
{SCIENTIFIC_SIGNIFICANCE_RUBRIC}

Verification-difficulty rubric:
{VERIFICATION_DIFFICULTY_RUBRIC}

User instruction:
{instruction.strip()}

Current contract content:
{json.dumps(content, ensure_ascii=False, indent=2)}
""".strip()
    result = runner.run(
        role="problem-contract-rewriter",
        prompt=prompt,
        schema_path=repository_root
        / "schemas"
        / "stages"
        / "problem-contract-content.schema.json",
        output_path=agent_output_path,
        events_path=events_path,
    )
    rewritten = problem_contract_from_agent_content(
        problem_id=str(contract["problem_id"]),
        content=result.output,
        schema_path=schema_path,
    )
    dump_problem_contract(output_path, rewritten, schema_path)
    return rewritten
