from pathlib import Path

from open_research_discovery.common import dump_yaml, load_yaml
from open_research_discovery.validation import (
    validate_agentgitlab_snapshot,
    validate_problem,
    validate_registry,
    validate_registry_pool_consistency,
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


def test_ready_problem_requires_current_open_core_and_clear_verification(
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
        "ready threshold-free problem requires verification_clarity=clear" in errors
    )
    assert "ready problem requires route candidate-result" in errors


def test_ready_problem_accepts_zero_difficulty_with_blocked_ci(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    problem_path = tmp_path / "problem.yaml"
    problem = load_yaml(root / "tests" / "fixtures" / "problem-draft.yaml")
    problem["id"] = "ORP-0001"
    problem["title"] = "Final-result-scoped example"
    problem["schema_version"] = 4
    problem["status"] = "ready"
    problem["sources"] = [
        {
            "source_key": "lkm:gcn_example",
            "kind": "lkm_open_question",
            "title": "A paper with an explicit open question",
            "identifier": "gcn_example",
            "url": "https://example.test/source",
            "locator": "Section 2",
            "date": "2026-01-01",
            "exact_excerpt": "Find a finite counterexample.",
            "surrounding_context": "The paper asks: find a finite counterexample.",
            "source_intent": "The authors pose the finite counterexample search.",
            "relationship": "This dedicated open-question record poses the problem.",
        }
    ]
    problem["resolution_audit"].update(
        {
            "checked_through": "2026-07-25",
            "status": "still_open",
            "surviving_open_core": "Find a finite counterexample.",
            "evidence": [
                {
                    "source": "web",
                    "title": "Later status review",
                    "identifier": "10.0000/later",
                    "url": "https://example.test/later",
                    "date": "2026",
                    "content_level": "abstract",
                    "relation": "continuing_open",
                    "supports": "The finite target remains untreated.",
                    "direct_support": True,
                }
            ],
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
        "importance_level": "high",
        "scientific_significance_score": 8,
        "scientific_significance_rationale": (
            "A counterexample would overturn a standard heuristic."
        ),
        "post_audit_priority": "high",
        "route": "candidate-result",
        "verification_threshold_applied": False,
    }
    problem["discovery_contract"].update(
        {
            "expected_result": "A finite machine-readable counterexample.",
            "answer_types": ["counterexample"],
        }
    )
    problem["solution_review_contract"] = {
        "verification_difficulty": 0,
        "verification_clarity": "clear",
        "verification_standard": (
            "Accept only a finite object that satisfies every stated hypothesis "
            "and violates the bound under recomputation."
        ),
        "rationale": (
            "The counterexample answers the scoped conjecture and every "
            "condition is directly checkable."
        ),
        "checklist": "README.md#verification-difficulty",
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


def _catalog_record() -> dict:
    return {
        "id": "ORP-0001",
        "status": "ready",
        "importance_level": "high",
        "verification_difficulty": 2,
    }


def test_registry_pool_consistency_accepts_matching_rows() -> None:
    rows = [
        {
            "id": "ORP-0001",
            "repo": "https://example.test/problem",
            "status": "ready",
            "importance_level": "high",
            "verification_difficulty": 2,
        }
    ]

    assert validate_registry_pool_consistency(rows, [_catalog_record()]) == []


def test_registry_pool_consistency_reports_unknown_ids() -> None:
    rows = [{"id": "ORP-0002", "repo": "https://example.test/other"}]

    errors = validate_registry_pool_consistency(rows, [_catalog_record()])

    assert errors == ["registry id not in pool catalog: ORP-0002"]


def test_registry_pool_consistency_reports_field_drift() -> None:
    rows = [
        {
            "id": "ORP-0001",
            "repo": "https://example.test/problem",
            "status": "draft",
            "verification_difficulty": 5,
        }
    ]

    errors = validate_registry_pool_consistency(rows, [_catalog_record()])

    assert (
        "ORP-0001 registry.status=draft != catalog.status=ready" in errors
    )
    assert (
        "ORP-0001 registry.verification_difficulty=5 "
        "!= catalog.verification_difficulty=2" in errors
    )


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
