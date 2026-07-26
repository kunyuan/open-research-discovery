#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with (root / "problem.yaml").open(encoding="utf-8") as handle:
        problem = yaml.safe_load(handle)
    with (root / "schema" / "problem.schema.json").open(encoding="utf-8") as handle:
        schema = json.load(handle)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(problem),
        key=lambda error: list(error.path),
    )
    messages = []
    for error in errors:
        location = ".".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{location}: {error.message}")

    if problem.get("status") == "ready":
        sources = problem.get("source_open_questions") or []
        audit = problem.get("resolution_audit") or {}
        importance = problem.get("importance") or {}
        triage = problem.get("research_triage") or {}
        contract = problem.get("discovery_contract") or {}
        reviewer = problem.get("reviewer_contract") or {}
        ci = problem.get("ci_contract") or {}
        if not sources or not any(
            str(source.get("local_id") or "").endswith("::open_question")
            for source in sources
        ):
            messages.append("ready problem requires ::open_question source provenance")
        if audit.get("status") not in {"still_open", "partially_resolved"}:
            messages.append("ready problem requires a current-open resolution status")
        for field in ("checked_at", "checked_through", "surviving_open_core"):
            if not str(audit.get(field) or "").strip():
                messages.append(f"ready problem requires resolution_audit.{field}")
        if not audit.get("evidence"):
            messages.append("ready problem requires resolution_audit.evidence")
        progress = audit.get("progress_assessment") or {}
        if audit.get("status") == "partially_resolved" and not progress.get(
            "major_progress_found"
        ):
            messages.append(
                "partially resolved ready problem requires a major-progress assessment"
            )
        if progress.get("major_progress_found"):
            for field in (
                "surviving_core_reassessed",
                "importance_reassessed",
                "verification_reassessed",
            ):
                if progress.get(field) is not True:
                    messages.append(
                        f"major progress requires progress_assessment.{field}=true"
                    )
            if progress.get("decision") in {None, "unassessed"}:
                messages.append("major progress requires a post-progress decision")
        for field in ("motivation", "consequences_of_progress", "current_best_result"):
            if not str(importance.get(field) or "").strip():
                messages.append(f"ready problem requires importance.{field}")
        if triage.get("importance_level") not in {"high", "medium"}:
            messages.append(
                "ready problem requires high or medium intrinsic importance"
            )
        if triage.get("post_audit_priority") not in {"high", "medium", "low"}:
            messages.append("ready problem requires an active post-audit priority")
        if triage.get("route") not in {
            "candidate-machine",
            "candidate-llm",
            "candidate-hybrid",
        }:
            messages.append("ready problem requires a candidate verification route")
        for field in ("candidate_format", "verifier_command", "success_condition"):
            if not str(contract.get(field) or "").strip():
                messages.append(f"ready problem requires discovery_contract.{field}")
        profile = contract.get("verification_profile") or {}
        mode = profile.get("mode")
        ease = profile.get("ease")
        protocol = str(profile.get("protocol") or "").strip()
        if mode in {None, "unclassified"}:
            messages.append("ready problem requires a classified verification mode")
        if ease in {None, "unclassified"}:
            messages.append("ready problem requires a classified verification ease")
        if not protocol:
            messages.append("ready problem requires a verification protocol")
        for field in (
            "scope",
            "difficulty",
            "checklist",
            "estimated_review_time",
            "acceptance_boundary",
        ):
            if not str(reviewer.get(field) or "").strip():
                messages.append(f"ready problem requires reviewer_contract.{field}")
        checklist = root / str(reviewer.get("checklist") or "")
        if not checklist.is_file():
            messages.append(f"review checklist file does not exist: {checklist}")
        elif "review_contract_not_generated" in checklist.read_text(encoding="utf-8"):
            messages.append("ready problem cannot use an ungenerated review contract")
        for field in (
            "workflow",
            "driver",
            "pseudocode",
            "runner",
            "estimated_runtime",
        ):
            if not str(ci.get(field) or "").strip():
                messages.append(f"ready problem requires ci_contract.{field}")
        for field in ("workflow", "driver", "pseudocode"):
            declared = root / str(ci.get(field) or "")
            if not declared.is_file():
                messages.append(f"declared CI file does not exist: {declared}")
        if mode == "machine-checkable" and ci.get("status") != "implemented":
            messages.append(
                "machine-checkable ready problem requires implemented CI"
            )
        if mode == "hybrid" and ci.get("status") not in {"implemented", "partial"}:
            messages.append(
                "hybrid ready problem requires implemented or partial CI"
            )
        if mode == "llm-reviewable" and ci.get("status") not in {
            "implemented",
            "partial",
            "reviewer-only",
        }:
            messages.append(
                "LLM-reviewable ready problem requires an executable review path"
            )
        if mode in {"llm-reviewable", "hybrid"} and protocol:
            review = root / protocol
            if not review.is_file():
                messages.append(f"review protocol file does not exist: {protocol}")
            elif "review_contract_not_generated" in review.read_text(
                encoding="utf-8"
            ):
                messages.append(
                    "ready problem cannot use an ungenerated review contract"
                )

        if mode in {"machine-checkable", "hybrid"}:
            verifier = root / "verifier" / "check.py"
            if not verifier.exists():
                messages.append("machine or hybrid ready problem requires verifier/check.py")
            elif "verifier_not_implemented" in verifier.read_text(encoding="utf-8"):
                messages.append(
                    "machine or hybrid ready problem cannot use the template verifier stub"
                )
        if mode == "expert-review":
            messages.append(
                "expert-review problem belongs in the manual-review queue, not status ready"
            )

    if messages:
        for message in messages:
            print(message)
        return 1
    print("problem contract is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
