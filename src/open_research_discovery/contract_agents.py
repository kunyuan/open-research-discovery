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
    schema_path = repository_root / "schemas" / "problem.schema.json"
    require_valid_problem_contract(contract, schema_path)
    prompt = f"""
You are an independent Problem Contract Reviewer. Review this open scientific
problem; do not solve it and do not require literal identity with a source.

Return accept only if the contract is a complete, self-contained, scientifically
solid and consequential research problem for which a submitted answer can be
unambiguously accepted or rejected. A source-grounded generalization is allowed
when its scientific bridge is sound and explicit. Reject or request rewrite for
misquotation, scope drift, weakened targets, unnecessary restrictions, hidden
solver-chosen targets, a merely technical low-impact task presented as broadly
important, or a scope so general that resolution is indeterminate.

Review every field in the contract. In particular, check that each significance
entry states a real concrete effect, every listed solution difficulty is a
solving obstacle rather than an acceptance rule, every answer type has a complete
acceptance boundary, and each CI contract describes only a real mechanical
procedure. Null CI is valid. Do not add any field outside the schema.

Scientific-significance rubric:
{SCIENTIFIC_SIGNIFICANCE_RUBRIC}

Verification-difficulty rubric:
{VERIFICATION_DIFFICULTY_RUBRIC}

Return accept when dispatchable, rewrite when the same problem can be repaired,
and reject only when repair requires a different problem or new evidence.

Problem Contract:
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
    schema_path = repository_root / "schemas" / "problem.schema.json"
    require_valid_problem_contract(contract, schema_path)
    if not instruction.strip():
        raise ValueError("rewrite instruction must not be empty")
    prompt = f"""
You are a Problem Contract Rewriter. Apply the instruction while preserving
problem_id and the scientific identity of the problem. Return the complete
rewritten content, not a patch or commentary. Use only fields represented by
the output schema. Do not add workflow metadata.

The keys of verification_contract are represented as answer_type entries here.
Each needs an unambiguous acceptance contract and a truthful CI contract; use an
empty string when no mechanical CI is possible. Recompute one overall residual
verification-difficulty score across all answer types.

Scientific-significance rubric:
{SCIENTIFIC_SIGNIFICANCE_RUBRIC}

Verification-difficulty rubric:
{VERIFICATION_DIFFICULTY_RUBRIC}

Instruction:
{instruction.strip()}

Current content:
{json.dumps(contract_to_agent_content(contract), ensure_ascii=False, indent=2)}
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
