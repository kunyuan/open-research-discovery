from __future__ import annotations

from pathlib import Path
from typing import Any


REVIEW_SCOPES = {
    "result-only",
    "result-and-derivation",
    "expert-intensive",
    "unclassified",
}

CI_STATUSES = {
    "implemented",
    "partial",
    "pseudocode",
    "reviewer-only",
    "blocked",
}


def verifier_is_implemented(repo: Path) -> bool:
    verifier = repo / "verifier" / "check.py"
    return verifier.is_file() and "verifier_not_implemented" not in verifier.read_text(
        encoding="utf-8"
    )


def contract_for(
    problem: dict[str, Any], repo: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize explicit contracts without inferring science from a result type."""

    discovery = problem.get("discovery_contract") or {}
    existing_reviewer = problem.get("reviewer_contract") or {}
    existing_ci = problem.get("ci_contract") or {}

    scope = str(existing_reviewer.get("scope") or "unclassified")
    if scope not in REVIEW_SCOPES:
        scope = "unclassified"
    success = str(discovery.get("success_condition") or "")
    reviewer = {
        "scope": scope,
        "checklist": "verifier/review.md",
        "estimated_review_time": str(
            existing_reviewer.get("estimated_review_time")
            or "requires a problem-specific estimate"
        ),
        "acceptance_boundary": str(
            existing_reviewer.get("acceptance_boundary") or success
        ),
    }

    status = str(existing_ci.get("status") or "")
    if status not in CI_STATUSES:
        status = "implemented" if verifier_is_implemented(repo) else "blocked"
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
        "timeout_minutes": int(existing_ci.get("timeout_minutes") or 10),
    }
    return reviewer, ci


def render_review(problem: dict[str, Any]) -> str:
    question = problem["question"]
    discovery = problem["discovery_contract"]
    reviewer = problem["reviewer_contract"]
    audit = problem["resolution_audit"]
    return "\n".join(
        [
            "# Reviewer-agent acceptance protocol",
            "",
            "Judge the submitted result against this exact problem. Do not inspect or",
            "require the solver's search log or hidden reasoning process.",
            "",
            f"- Problem: `{problem['id']}` — {problem['title']}",
            f"- Exact target: {question['canonical_statement']}",
            f"- Expected result: {discovery['expected_result']}",
            f"- Candidate format: {discovery['candidate_format']}",
            f"- Acceptance boundary: {reviewer['acceptance_boundary']}",
            f"- Review scope: `{reviewer['scope']}`",
            f"- Estimated review time: {reviewer['estimated_review_time']}",
            f"- Current-status audit: `{audit['status']}` checked {audit['checked_at']}",
            "",
            "## Review",
            "",
            "1. Freeze the exact claim, assumptions, conventions, and answer format.",
            "2. Confirm that the submission contains the declared final result.",
            "3. Apply the problem-specific acceptance boundary above.",
            "4. Record every check performed and every failed condition.",
            "5. Reject `result-only` if correctness cannot be decided without a",
            "   derivation or explanation outside the submitted result.",
            "",
            "A program or formal proof is itself the result only when the original",
            "problem requests that answer format; do not upgrade an ordinary proof",
            "question to Lean, Coq, or Isabelle after the fact.",
            "",
            "Return `accept-local`, `reject`, `needs-expert`, or",
            "`protocol-incomplete`. Local acceptance does not establish novelty or",
            "current openness.",
            "",
        ]
    )


def render_ci(problem: dict[str, Any]) -> str:
    discovery = problem["discovery_contract"]
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
            f"- Acceptance condition: {discovery['success_condition']}",
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
    timeout-minutes: {timeout_minutes}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv run python tools/ci_verify.py
"""
