#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    problem = yaml.safe_load((root / "problem.yaml").read_text(encoding="utf-8"))
    schema = json.loads(
        (root / "schema" / "problem.schema.json").read_text(encoding="utf-8")
    )
    messages = [
        f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}"
        for error in sorted(
            Draft202012Validator(schema).iter_errors(problem),
            key=lambda item: list(item.path),
        )
    ]

    if problem.get("status") == "ready":
        sources = problem.get("source_open_questions") or []
        audit = problem.get("resolution_audit") or {}
        importance = problem.get("importance") or {}
        triage = problem.get("research_triage") or {}
        discovery = problem.get("discovery_contract") or {}
        reviewer = problem.get("reviewer_contract") or {}
        ci = problem.get("ci_contract") or {}

        if not sources or not any(
            source.get("source_path") == "data.papers[].open_questions"
            or str(source.get("local_id") or "").endswith("::open_question")
            for source in sources
        ):
            messages.append("ready problem requires open_questions provenance")
        if audit.get("status") not in {"still_open", "partially_resolved"}:
            messages.append("ready problem requires a current-open resolution status")
        for field in ("checked_at", "checked_through", "surviving_open_core"):
            if not str(audit.get(field) or "").strip():
                messages.append(f"ready problem requires resolution_audit.{field}")
        if not audit.get("evidence"):
            messages.append("ready problem requires resolution_audit.evidence")
        for field in ("motivation", "consequences_of_progress", "current_best_result"):
            if not str(importance.get(field) or "").strip():
                messages.append(f"ready problem requires importance.{field}")
        if triage.get("importance_level") not in {"high", "medium"}:
            messages.append("ready problem requires high or medium importance")
        if triage.get("route") != "candidate-result":
            messages.append("ready problem requires route candidate-result")
        for field in (
            "expected_result",
            "candidate_format",
            "verifier_command",
            "success_condition",
            "solution_route",
        ):
            if not str(discovery.get(field) or "").strip():
                messages.append(f"ready problem requires discovery_contract.{field}")
        if reviewer.get("scope") != "result-only":
            messages.append("ready problem requires result-only review")
        for field in (
            "checklist",
            "estimated_review_time",
            "acceptance_boundary",
        ):
            if not str(reviewer.get(field) or "").strip():
                messages.append(f"ready problem requires reviewer_contract.{field}")
        for field in ("workflow", "driver", "pseudocode"):
            declared = root / str(ci.get(field) or "")
            if not declared.is_file():
                messages.append(f"declared CI file does not exist: {declared}")

    if messages:
        print("\n".join(messages))
        return 1
    print("problem contract is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
