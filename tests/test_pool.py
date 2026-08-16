import json
import threading
from pathlib import Path

from open_research_discovery.common import dump_yaml, load_yaml
from open_research_discovery.pool import (
    dedup_candidates,
    normalize_text,
    problem_to_record,
    statement_fingerprint,
    validate_pool,
)
from open_research_discovery.pool_sync import sync_pool


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROBLEM_SCHEMA = REPOSITORY_ROOT / "schemas" / "problem.schema.json"


def record(
    problem_id: str,
    statement: str,
    *,
    source_nodes: list[str] | None = None,
    route: str = "candidate-result",
) -> dict[str, object]:
    return {
        "id": problem_id,
        "title": statement,
        "domain": "graph theory",
        "status": "resolution-audited",
        "importance_level": "high",
        "post_audit_priority": "high",
        "route": route,
        "statement_sha256": statement_fingerprint(statement),
        "search_text": normalize_text(statement),
        "source_nodes": source_nodes or [],
        "source_local_ids": [],
    }


def test_statement_fingerprint_ignores_case_and_punctuation() -> None:
    assert statement_fingerprint("Does X exist?") == statement_fingerprint(
        "does x exist"
    )


def test_dedup_candidates_prioritize_shared_source() -> None:
    records = [
        record("OMP-0001", "First formulation", source_nodes=["gcn_1"]),
        record("OMP-0002", "Different wording", source_nodes=["gcn_1"]),
    ]
    candidates = dedup_candidates(records)
    assert candidates[0]["score"] == 1.0
    assert candidates[0]["signals"]["shared_sources"] == ["gcn_1"]


def test_known_relation_is_exposed_for_review() -> None:
    records = [
        record("OMP-0001", "Find a Steiner system above strength five"),
        record("OMP-0002", "Construct a Steiner design above strength five"),
    ]
    relations = {
        "relations": [
            {
                "source": "OMP-0001",
                "target": "OMP-0002",
                "type": "derived",
            }
        ]
    }
    candidates = dedup_candidates(records, relations=relations, threshold=0.1)
    assert candidates[0]["known_relation"] == "derived"
    assert candidates[0]["decision"] == "known-derived"


def test_problem_record_exposes_operational_resolution_conclusion() -> None:
    problem = {
        "id": "OMP-0001",
        "title": "Audited example",
        "domain": "graph theory",
        "status": "resolution-audited",
        "question": {
            "canonical_statement": "Does the example exist?",
            "aliases": [],
        },
        "source_open_questions": [],
        "resolution_audit": {
            "status": "still_open",
            "checked_through": "2026-07-25",
            "conclusion": {
                "label": "likely_open",
                "confidence": "medium",
            },
        },
        "research_triage": {},
        "discovery_contract": {},
        "solution_review_contract": {},
        "ci_contract": {},
    }

    record = problem_to_record(problem, "OMP-0001-audited-example")

    assert record["resolution_conclusion"] == "likely_open"
    assert record["resolution_confidence"] == "medium"
    assert record["resolution_checked_at"] == "2026-07-25"


def test_sync_pool_serializes_concurrent_catalog_updates(
    tmp_path: Path,
) -> None:
    workers = 6
    out = tmp_path / "pool"
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def sync_one(index: int) -> None:
        problem = load_yaml(REPOSITORY_ROOT / "tests" / "fixtures" / "problem-draft.yaml")
        problem["id"] = f"ORP-{index + 1:04d}"
        problem["title"] = f"Concurrent sync problem {index}"
        problem["domain"] = "graph theory"
        problem["status"] = "resolution-audited"
        source_root = tmp_path / f"input-{index}"
        dump_yaml(
            source_root
            / f"ORP-{index + 1:04d}-problem-{index}"
            / "problem.yaml",
            problem,
        )
        try:
            barrier.wait(timeout=30)
            sync_pool(
                source_root,
                out,
                problem_schema=PROBLEM_SCHEMA,
                preserve_existing=True,
            )
        except BaseException as error:
            with errors_lock:
                errors.append(error)

    threads = [
        threading.Thread(target=sync_one, args=(index,))
        for index in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []

    catalog_path = out / "catalog.jsonl"
    records = [
        json.loads(line)
        for line in catalog_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected_ids = [f"ORP-{index + 1:04d}" for index in range(workers)]
    assert [row["id"] for row in records] == expected_ids
    assert all(
        (out / "problems" / f"{problem_id}.yaml").is_file()
        for problem_id in expected_ids
    )
    # The lock file lives next to the catalog but is never synced as a record.
    assert (out / ".sync.lock").is_file()


def _synced_pool(tmp_path: Path) -> Path:
    problem = load_yaml(REPOSITORY_ROOT / "tests" / "fixtures" / "problem-draft.yaml")
    problem["id"] = "ORP-0001"
    problem["status"] = "resolution-audited"
    source_root = tmp_path / "input"
    dump_yaml(source_root / "ORP-0001-draft" / "problem.yaml", problem)
    out = tmp_path / "pool"
    sync_pool(source_root, out, problem_schema=PROBLEM_SCHEMA)
    dump_yaml(out / "relations.yaml", {"schema_version": 1, "relations": []})
    return out


def test_validate_pool_accepts_fresh_synced_pool(tmp_path: Path) -> None:
    assert validate_pool(_synced_pool(tmp_path)) == []
