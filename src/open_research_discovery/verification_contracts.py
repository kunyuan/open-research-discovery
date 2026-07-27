from __future__ import annotations

from pathlib import Path
from typing import Any


SOLUTION_REVIEW_SCOPES = {
    "result-only",
    "result-and-derivation",
    "expert-intensive",
    "unclassified",
}

CI_STATUSES = {
    "implemented",
    "partial",
    "pseudocode",
    "solution-reviewer-only",
    "blocked",
}


def verifier_is_implemented(repo: Path) -> bool:
    verifier = repo / "verifier" / "check.py"
    return verifier.is_file() and "verifier_not_implemented" not in verifier.read_text(
        encoding="utf-8"
    )


def solution_review_and_ci_contracts_for(
    problem: dict[str, Any], repo: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize explicit contracts without inferring science from a result type."""

    discovery = problem.get("discovery_contract") or {}
    existing_solution_review = problem.get("solution_review_contract") or {}
    existing_ci = problem.get("ci_contract") or {}

    scope = str(existing_solution_review.get("scope") or "unclassified")
    if scope not in SOLUTION_REVIEW_SCOPES:
        scope = "unclassified"
    expected_result = str(discovery.get("expected_result") or "")
    solution_review = {
        "scope": scope,
        "rationale": str(
            existing_solution_review.get("rationale")
            or "requires a problem-specific rationale"
        ),
        "checklist": "verifier/solution-review.md",
        "estimated_review_time": str(
            existing_solution_review.get("estimated_review_time")
            or "requires a problem-specific estimate"
        ),
        "acceptance_boundary": str(
            existing_solution_review.get("acceptance_boundary")
            or expected_result
        ),
    }

    status = str(existing_ci.get("status") or "")
    if status not in CI_STATUSES:
        status = "implemented" if verifier_is_implemented(repo) else "blocked"
    raw_timeout = existing_ci.get("timeout_minutes")
    ci = {
        "status": status,
        "workflow": ".github/workflows/verify.yml",
        "driver": "tools/ci_verify.py",
        "pseudocode": "verifier/ci.md",
        "runner": str(existing_ci.get("runner") or "ubuntu-latest"),
        "estimated_runtime": str(
            existing_ci.get("estimated_runtime")
            or "requires a problem-specific estimate"
        ),
        "timeout_minutes": 10 if raw_timeout is None else int(raw_timeout),
    }
    return solution_review, ci


def render_solution_review(problem: dict[str, Any]) -> str:
    question = problem["question"]
    discovery = problem["discovery_contract"]
    solution_review = problem["solution_review_contract"]
    audit = problem["resolution_audit"]
    return "\n".join(
        [
            "# Solution Reviewer acceptance protocol",
            "",
            "Judge the submitted result against this exact problem without reviewing",
            "the solver's reasoning process.",
            "",
            f"- Problem: `{problem['id']}` — {problem['title']}",
            f"- Exact target: {question['canonical_statement']}",
            f"- Expected result: {discovery['expected_result']}",
            f"- Acceptance boundary: {solution_review['acceptance_boundary']}",
            f"- Review scope: `{solution_review['scope']}`",
            f"- Rationale: {solution_review['rationale']}",
            f"- Estimated review time: {solution_review['estimated_review_time']}",
            f"- Current-status audit: `{audit['status']}` checked {audit['checked_at']}",
            "",
            "## Solution Review checks",
            "",
            "1. Freeze the exact claim, assumptions, conventions, and answer format.",
            "2. Confirm that the submission contains the declared final result.",
            "3. Apply the problem-specific acceptance boundary above.",
            "4. Record every check performed and every failed condition.",
            "5. Reject `result-only` if correctness requires substantive review of",
            "   a non-machine-checkable mathematical or scientific derivation.",
            "",
            "An ordinary written proof remains `result-and-derivation`. Executable",
            "formal proof code counts as the result only when the original problem",
            "requests that answer format; do not upgrade an ordinary proof question",
            "to Lean, Coq, or Isabelle after the fact. Apply the same rule to",
            "unrequested SOS, primal-dual, or other proof-certificate formats.",
            "",
            "Return `accept-local`, `reject`, `needs-expert`, or",
            "`protocol-incomplete`. Local acceptance does not establish novelty or",
            "current openness.",
            "",
        ]
    )


def render_ci(problem: dict[str, Any]) -> str:
    discovery = problem["discovery_contract"]
    solution_review = problem["solution_review_contract"]
    ci = problem["ci_contract"]
    return "\n".join(
        [
            "# CI design and executable boundary",
            "",
            f"- Problem: `{problem['id']}` — {problem['title']}",
            f"- Status: `{ci['status']}`",
            f"- Runner: {ci['runner']}",
            f"- Estimated runtime: {ci['estimated_runtime']}",
            f"- Hard timeout: {ci['timeout_minutes']} minutes",
            f"- Expected result: {discovery['expected_result']}",
            f"- Acceptance condition: {solution_review['acceptance_boundary']}",
            "",
            "```text",
            "load and schema-validate problem.yaml",
            "parse the submitted result",
            "run the problem-specific checks named by the acceptance condition",
            "emit a structured pass/fail report",
            "```",
            "",
            "Replace this generic outline with problem-specific pseudocode before",
            "claiming CI buildability. Structural CI alone is not substantive",
            "scientific verification.",
            "",
        ]
    )


def render_workflow(timeout_minutes: int) -> str:
    workflow_timeout = max(1, timeout_minutes)
    return f"""name: verify

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  contract:
    runs-on: ubuntu-latest
      timeout-minutes: {workflow_timeout}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv run python tools/ci_verify.py
"""
