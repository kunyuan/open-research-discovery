from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .common import PROBLEM_ID_PATTERN, load_yaml

READY_RESOLUTION_STATUSES = {"still_open", "partially_resolved"}


def schema_errors(instance: Any, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    return [
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    ]


def validate_problem(problem_path: Path, schema_path: Path) -> list[str]:
    problem = load_yaml(problem_path)
    with schema_path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    errors = schema_errors(problem, schema)

    ready = problem.get("status") == "ready"
    audit = problem.get("resolution_audit") or {}
    contract = problem.get("discovery_contract") or {}
    sources = problem.get("source_open_questions") or []
    importance = problem.get("importance") or {}
    triage = problem.get("research_triage") or {}
    solution_review = problem.get("solution_review_contract") or {}
    ci = problem.get("ci_contract") or {}

    if ready:
        if not sources:
            errors.append("ready problem requires at least one source_open_question")
        elif not any(
            source.get("source_path") == "data.papers[].open_questions"
            or str(source.get("local_id") or "").endswith("::open_question")
            for source in sources
        ):
            errors.append(
                "ready problem requires dedicated open_questions source provenance"
            )
        if audit.get("status") not in READY_RESOLUTION_STATUSES:
            errors.append("ready problem must be still_open or partially_resolved")
        for field in ("checked_at", "checked_through"):
            if not str(audit.get(field) or "").strip():
                errors.append(f"ready problem requires resolution_audit.{field}")
        if not str(audit.get("surviving_open_core") or "").strip():
            errors.append("ready problem requires resolution_audit.surviving_open_core")
        if not audit.get("evidence"):
            errors.append("ready problem requires resolution_audit.evidence")
        progress = audit.get("progress_assessment") or {}
        if audit.get("status") == "partially_resolved" and not progress.get(
            "major_progress_found"
        ):
            errors.append("partially resolved ready problem requires a major-progress assessment")
        if progress.get("major_progress_found"):
            for field in (
                "surviving_core_reassessed",
                "importance_reassessed",
                "solution_review_reassessed",
            ):
                if progress.get(field) is not True:
                    errors.append(f"major progress requires progress_assessment.{field}=true")
            if progress.get("decision") in {None, "unassessed"}:
                errors.append("major progress requires a post-progress decision")
        for field in ("motivation", "consequences_of_progress", "current_best_result"):
            if not str(importance.get(field) or "").strip():
                errors.append(f"ready problem requires importance.{field}")
        if triage.get("importance_level") not in {"high", "medium"}:
            errors.append("ready problem requires high or medium intrinsic importance")
        if triage.get("post_audit_priority") not in {"high", "medium", "low"}:
            errors.append("ready problem requires an active post-audit priority")
        if triage.get("route") != "candidate-result":
            errors.append("ready problem requires route candidate-result")
        for field in (
            "expected_result",
            "candidate_format",
            "verifier_command",
            "success_condition",
            "solution_route",
        ):
            if not str(contract.get(field) or "").strip():
                errors.append(f"ready problem requires discovery_contract.{field}")
        if solution_review.get("scope") != "result-only":
            errors.append(
                "ready problem requires "
                "solution_review_contract.scope=result-only"
            )
        for field in (
            "scope",
            "checklist",
            "estimated_review_time",
            "acceptance_boundary",
        ):
            if not str(solution_review.get(field) or "").strip():
                errors.append(
                    f"ready problem requires solution_review_contract.{field}"
                )
        checklist = problem_path.parent / str(
            solution_review.get("checklist") or ""
        )
        if not checklist.is_file():
            errors.append(
                f"Solution Reviewer checklist file does not exist: {checklist}"
            )
        elif "review_contract_not_generated" in checklist.read_text(encoding="utf-8"):
            errors.append(
                "ready problem cannot use an ungenerated Solution Reviewer "
                "contract"
            )
        for field in (
            "workflow",
            "driver",
            "pseudocode",
            "runner",
            "estimated_runtime",
        ):
            if not str(ci.get(field) or "").strip():
                errors.append(f"ready problem requires ci_contract.{field}")
        for field in ("workflow", "driver", "pseudocode"):
            declared = problem_path.parent / str(ci.get(field) or "")
            if not declared.is_file():
                errors.append(f"declared CI file does not exist: {declared}")
    return errors


def validate_registry(registry_path: Path) -> list[str]:
    data = load_yaml(registry_path)
    errors: list[str] = []
    repos = data.get("repos")
    if not isinstance(repos, list):
        return ["registry.repos must be a list"]
    seen_ids: set[str] = set()
    seen_repos: set[str] = set()
    for index, item in enumerate(repos):
        if not isinstance(item, dict):
            errors.append(f"repos[{index}] must be a mapping")
            continue
        problem_id = str(item.get("id") or "")
        repo = str(item.get("repo") or "")
        if not problem_id:
            errors.append(f"repos[{index}].id is required")
        elif problem_id in seen_ids:
            errors.append(f"duplicate problem id: {problem_id}")
        if not repo:
            errors.append(f"repos[{index}].repo is required")
        elif repo in seen_repos:
            errors.append(f"duplicate repo: {repo}")
        seen_ids.add(problem_id)
        seen_repos.add(repo)
    return errors


def validate_agentgitlab_snapshot(
    snapshot_path: Path,
    registry_path: Path,
) -> list[str]:
    snapshot = load_yaml(snapshot_path)
    registry = load_yaml(registry_path)
    errors: list[str] = []
    namespace = str(snapshot.get("namespace") or "")
    projects = snapshot.get("projects")
    known_ids = {
        str(item.get("id") or "")
        for item in registry.get("repos") or []
        if isinstance(item, dict)
    }
    if not namespace:
        errors.append("agentgitlab.namespace is required")
    if not isinstance(projects, list):
        return ["agentgitlab.projects must be a list"]

    seen_ids: set[str] = set()
    seen_projects: set[str] = set()
    for index, item in enumerate(projects):
        if not isinstance(item, dict):
            errors.append(f"agentgitlab.projects[{index}] must be a mapping")
            continue
        problem_id = str(item.get("id") or "")
        project = str(item.get("project") or "")
        commit = str(item.get("baseline_commit") or "")
        issue_iid = item.get("issue_iid")
        if not re.fullmatch(PROBLEM_ID_PATTERN, problem_id):
            errors.append(
                f"agentgitlab.projects[{index}].id is not a valid problem ID"
            )
        elif problem_id not in known_ids:
            errors.append(
                f"agentgitlab.projects[{index}] unknown problem id: {problem_id}"
            )
        elif problem_id in seen_ids:
            errors.append(f"duplicate AgentGitLab problem id: {problem_id}")
        if not project.startswith(f"{namespace}/"):
            errors.append(
                f"agentgitlab.projects[{index}].project must be under {namespace}/"
            )
        elif project in seen_projects:
            errors.append(f"duplicate AgentGitLab project: {project}")
        if not isinstance(issue_iid, int) or issue_iid < 1:
            errors.append(
                f"agentgitlab.projects[{index}].issue_iid must be a positive integer"
            )
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            errors.append(
                f"agentgitlab.projects[{index}].baseline_commit must be a full SHA"
            )
        seen_ids.add(problem_id)
        seen_projects.add(project)
    return errors
