from pathlib import Path

from open_research_discovery.common import dump_yaml, load_yaml
from open_research_discovery.validation import (
    validate_agentgitlab_snapshot,
    validate_problem,
    validate_registry,
)


def test_draft_schema_uses_plain_result_and_review_fields(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["id"] = "ORP-0001"
    path = tmp_path / "problem.yaml"
    dump_yaml(path, problem)

    assert validate_problem(path, root / "schemas" / "problem.schema.json") == []
    assert "artifact_type" not in problem["discovery_contract"]
    assert "verification_profile" not in problem["discovery_contract"]
    assert problem["discovery_contract"] == {"expected_result": ""}


def test_ready_problem_requires_current_open_core_and_result_only(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["id"] = "ORP-0001"
    problem["status"] = "ready"
    path = tmp_path / "problem.yaml"
    dump_yaml(path, problem)

    errors = validate_problem(path, root / "schemas" / "problem.schema.json")

    assert "ready problem must be still_open or partially_resolved" in errors
    assert any("surviving_open_core" in error for error in errors)
    assert any("expected_result" in error for error in errors)
    assert (
        "ready problem requires solution_review_contract.scope=result-only"
        in errors
    )
    assert "ready problem requires route candidate-result" in errors


def test_ready_problem_accepts_result_only_with_blocked_ci(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    problem_path = tmp_path / "problem.yaml"
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["id"] = "ORP-0001"
    problem["title"] = "Result-only example"
    problem["status"] = "ready"
    problem["source_open_questions"] = [
        {
            "node_id": "gcn_example",
            "paper_id": "paper-example",
            "local_id": "paper:paper-example::open_question",
            "exact_text": "Find a finite counterexample.",
            "publication_date": "2026-01-01",
            "source_path": "data.papers[].open_questions",
        }
    ]
    problem["resolution_audit"].update(
        {
            "checked_at": "2026-07-25",
            "checked_through": "2026-07-25",
            "status": "still_open",
            "surviving_open_core": "Find a finite counterexample.",
            "evidence": [{"type": "review"}],
        }
    )
    problem["importance"].update(
        {
            "motivation": "Named finite bottleneck.",
            "consequences_of_progress": "Refutes a used conjecture.",
            "current_best_result": "No counterexample in the audited literature.",
        }
    )
    problem["research_triage"] = {
        "reviewed_at": "2026-07-25",
        "importance_level": "high",
        "audit_priority": "high",
        "post_audit_priority": "high",
        "route": "candidate-result",
        "rationale": "Important and result-only.",
    }
    problem["discovery_contract"].update(
        {
            "expected_result": "A finite machine-readable counterexample.",
        }
    )
    problem["solution_review_contract"] = {
        "scope": "result-only",
        "rationale": (
            "The counterexample answers the scoped conjecture and every "
            "condition is directly checkable."
        ),
        "checklist": "README.md#review-scope",
        "estimated_review_time": "20 minutes",
        "acceptance_boundary": "Check every hypothesis and recompute failure.",
    }
    problem["ci_contract"]["status"] = "blocked"
    problem["ci_contract"]["timeout_minutes"] = 0
    dump_yaml(problem_path, problem)

    assert validate_problem(
        problem_path, root / "schemas" / "problem.schema.json"
    ) == []


def test_partially_resolved_ready_problem_requires_reassessment(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["id"] = "ORP-0001"
    problem["status"] = "ready"
    problem["resolution_audit"]["status"] = "partially_resolved"
    path = tmp_path / "problem.yaml"
    dump_yaml(path, problem)
    errors = validate_problem(path, root / "schemas" / "problem.schema.json")
    assert (
        "partially resolved ready problem requires a major-progress assessment"
        in errors
    )


def test_registry_rejects_duplicate_ids_and_repositories(tmp_path: Path) -> None:
    path = tmp_path / "repos.yaml"
    dump_yaml(
        path,
        {
            "schema_version": 1,
            "repos": [
                {"id": "OMP-0001", "repo": "https://example.test/one"},
                {"id": "OMP-0001", "repo": "https://example.test/one"},
            ],
        },
    )

    errors = validate_registry(path)

    assert "duplicate problem id: OMP-0001" in errors
    assert "duplicate repo: https://example.test/one" in errors


def test_agentgitlab_snapshot_matches_external_registry(tmp_path: Path) -> None:
    registry = tmp_path / "repos.yaml"
    snapshot = tmp_path / "agentgitlab.yaml"
    dump_yaml(
        registry,
        {
            "schema_version": 1,
            "repos": [
                {"id": "ORP-0001", "repo": "https://example.test/problem"}
            ],
        },
    )
    dump_yaml(
        snapshot,
        {
            "schema_version": 1,
            "namespace": "research",
            "projects": [
                {
                    "id": "ORP-0001",
                    "project": "research/orp-0001",
                    "issue_iid": 1,
                    "baseline_commit": "a" * 40,
                }
            ],
        },
    )

    assert validate_agentgitlab_snapshot(snapshot, registry) == []
