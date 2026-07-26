from pathlib import Path

from open_research_discovery.common import dump_yaml, load_yaml
from open_research_discovery.problem_repo import create_problem_repo
from open_research_discovery.validation import (
    validate_agentgitlab_snapshot,
    validate_problem,
    validate_registry,
)


def test_schema_accepts_new_namespace_and_scientific_artifacts(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "template" / "problem.yaml")
    problem["id"] = "ORP-0001"
    problem["discovery_contract"]["artifact_type"] = "experimental-result"
    path = tmp_path / "problem.yaml"
    dump_yaml(path, problem)

    assert validate_problem(path, root / "schemas" / "problem.schema.json") == []


def test_ready_problem_requires_current_open_core_and_verifier(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    problem = load_yaml(root / "template" / "problem.yaml")
    problem["status"] = "ready"
    path = tmp_path / "problem.yaml"
    dump_yaml(path, problem)

    errors = validate_problem(path, root / "schemas" / "problem.schema.json")

    assert "ready problem must be still_open or partially_resolved" in errors
    assert any("surviving_open_core" in error for error in errors)
    assert any("candidate_format" in error for error in errors)
    assert "ready problem requires a classified verification mode" in errors
    assert "ready problem requires a classified verification ease" in errors
    assert "ready problem requires a verification protocol" in errors


def test_ready_problem_accepts_bounded_llm_review_protocol(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    repo = tmp_path / "omp-0001-llm-review"
    create_problem_repo(
        root / "template",
        repo,
        schema_path=root / "schemas" / "problem.schema.json",
        problem_id="OMP-0001",
        title="LLM-reviewable example",
        slug="llm-reviewable-example",
        source_node="gcn_example",
    )
    problem_path = repo / "problem.yaml"
    problem = load_yaml(problem_path)
    problem["status"] = "ready"
    problem["source_open_questions"][0].update(
        {
            "paper_id": "paper-example",
            "local_id": "paper:paper-example::open_question",
            "exact_text": "Is the finite statement true?",
            "publication_date": "2026-01-01",
        }
    )
    problem["resolution_audit"].update(
        {
            "checked_at": "2026-07-25",
            "checked_through": "2026-07-25",
            "status": "still_open",
            "surviving_open_core": "Decide the finite statement.",
            "evidence": [{"type": "review"}],
        }
    )
    problem["importance"].update(
        {
            "motivation": "Named finite bottleneck.",
            "consequences_of_progress": "Closes the bottleneck.",
            "current_best_result": "Open in the cited review.",
        }
    )
    problem["research_triage"] = {
        "reviewed_at": "2026-07-25",
        "importance_level": "high",
        "audit_priority": "high",
        "post_audit_priority": "high",
        "route": "candidate-llm",
        "rationale": "The finite statement is important and locally reviewable.",
    }
    problem["discovery_contract"].update(
        {
            "candidate_format": "A short derivation in submission/solution.md.",
            "verifier_command": "independent LLM review using verifier/review.md",
            "success_condition": "Every item in verifier/review.md passes.",
            "verification_profile": {
                "mode": "llm-reviewable",
                "ease": "easy",
                "protocol": "verifier/review.md",
                "rationale": "The complete answer and definitions fit in a bounded checklist.",
            },
        }
    )
    problem["reviewer_contract"] = {
        "scope": "result-and-derivation",
        "difficulty": "easy",
        "checklist": "verifier/review.md",
        "estimated_review_time": "20-45 reviewer-agent minutes",
        "acceptance_boundary": "Every item in verifier/review.md passes.",
    }
    problem["ci_contract"] = {
        "status": "reviewer-only",
        "workflow": ".github/workflows/verify.yml",
        "driver": "tools/ci_verify.py",
        "pseudocode": "verifier/ci.md",
        "runner": (
            "ubuntu-latest for structural checks; substantive review runs "
            "outside GitHub Actions"
        ),
        "estimated_runtime": (
            "under 2 minutes structural CI; 20-45 minutes reviewer-agent time"
        ),
        "timeout_minutes": 10,
    }
    dump_yaml(problem_path, problem)

    errors = validate_problem(problem_path, root / "schemas" / "problem.schema.json")
    assert "ready problem cannot use an ungenerated review contract" in errors

    (repo / "verifier" / "review.md").write_text(
        "# Review\n\n1. Check every definition.\n2. Check the two displayed implications.\n",
        encoding="utf-8",
    )
    errors = validate_problem(problem_path, root / "schemas" / "problem.schema.json")
    assert errors == []

    problem["discovery_contract"]["verification_profile"]["mode"] = "expert-review"
    dump_yaml(problem_path, problem)
    errors = validate_problem(problem_path, root / "schemas" / "problem.schema.json")
    assert (
        "expert-review problem belongs in the manual-review queue, not status ready"
        in errors
    )

    problem["discovery_contract"]["verification_profile"]["mode"] = "llm-reviewable"
    problem["resolution_audit"]["status"] = "partially_resolved"
    dump_yaml(problem_path, problem)
    errors = validate_problem(problem_path, root / "schemas" / "problem.schema.json")
    assert (
        "partially resolved ready problem requires a major-progress assessment"
        in errors
    )

    problem["resolution_audit"]["progress_assessment"] = {
        "major_progress_found": True,
        "effect": "narrows",
        "surviving_core_reassessed": True,
        "importance_reassessed": True,
        "verification_reassessed": True,
        "decision": "rewrite-core",
        "derived_problem_ids": [],
    }
    dump_yaml(problem_path, problem)
    errors = validate_problem(problem_path, root / "schemas" / "problem.schema.json")
    assert errors == []


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
