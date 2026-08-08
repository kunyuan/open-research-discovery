import importlib.util
import json
import threading
from pathlib import Path

import pytest

from open_research_discovery.common import dump_json, dump_yaml
from open_research_discovery.pool import (
    VIEW_SPECS,
    dedup_candidates,
    field_matches,
    filter_records,
    normalize_text,
    problem_to_record,
    statement_fingerprint,
    validate_pool,
)


def record(
    problem_id: str,
    statement: str,
    *,
    source_nodes: list[str] | None = None,
    significance: str = "high",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "id": problem_id,
        "title": statement,
        "domain": "graph theory",
        "scientific_significance_level": significance,
        "verification_difficulty": 6,
        "ci_status": "manual-only",
        "statement_sha256": statement_fingerprint(statement),
        "search_text": normalize_text(statement),
        "source_nodes": source_nodes or [],
        "source_local_ids": [],
    }


def problem_contract(problem_id: str, title: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "problem_id": problem_id,
        "parent_problem_id": None,
        "subproblem_ids": [],
        "title": title,
        "abstract": "A finite graph-theory problem.",
        "background": "All graph classes and predicates are fixed here.",
        "references": ["A source reference"],
        "previous_progress": ["The claim is known for smaller instances."],
        "problem_statement": "Determine whether the stated graph exists.",
        "scientific_significance": {
            "graph theory": {
                "level": "high",
                "description": "It settles a standard extremal construction question.",
            }
        },
        "solution_difficulty": ["The search space grows rapidly."],
        "verification_contract": {
            "proof": {
                "contract": "Submit a proof of existence or nonexistence for the fixed class.",
                "ci_contract": None,
            }
        },
        "verification_difficulty": {
            "score": 6,
            "rationale": "No mechanical check removes the connected proof review.",
        },
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


def test_filter_records_uses_intersection() -> None:
    records = [
        record("OMP-0001", "one"),
        record("OMP-0002", "two", significance="medium"),
    ]
    selected = filter_records(
        records,
        {"scientific_significance_level": {"high"}},
    )
    assert [row["id"] for row in selected] == ["OMP-0001"]


def test_filter_records_matches_zero_verification_difficulty() -> None:
    records = [
        {**record("OMP-0001", "one"), "verification_difficulty": 0},
        {**record("OMP-0002", "two"), "verification_difficulty": 3},
    ]
    selected = filter_records(records, {"verification_difficulty": {"0"}})
    assert [row["id"] for row in selected] == ["OMP-0001"]


def test_verification_zero_view_selects_zero_difficulty_records() -> None:
    _, field, values = VIEW_SPECS["verification-0"]
    records = [
        {**record("OMP-0001", "one"), "verification_difficulty": 0},
        {**record("OMP-0002", "two"), "verification_difficulty": 7},
    ]
    selected = [row for row in records if field_matches(row, field, values)]
    assert [row["id"] for row in selected] == ["OMP-0001"]


def test_problem_record_rejects_unsupported_schema() -> None:
    with pytest.raises(ValueError, match="only Problem Contract"):
        problem_to_record({"schema_version": 4, "id": "OMP-0001"}, "unsupported")


def _load_sync_pool():
    script = Path(__file__).resolve().parents[1] / "scripts" / "sync_pool.py"
    spec = importlib.util.spec_from_file_location("sync_pool", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sync_pool_serializes_concurrent_catalog_updates(
    tmp_path: Path,
) -> None:
    sync_pool = _load_sync_pool().sync_pool
    workers = 6
    out = tmp_path / "pool"
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def sync_one(index: int) -> None:
        problem_id = f"ORP-{index + 1:04d}"
        problem = problem_contract(problem_id, f"Concurrent sync problem {index}")
        source_root = tmp_path / f"input-{index}"
        dump_json(
            source_root
            / f"{problem_id}-problem-{index}"
            / "problem.json",
            problem,
        )
        try:
            barrier.wait(timeout=30)
            sync_pool(source_root, out, preserve_existing=True)
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
        (out / "problems" / f"{problem_id}.json").is_file()
        for problem_id in expected_ids
    )
    # The lock file lives next to the catalog but is never synced as a record.
    assert (out / ".sync.lock").is_file()
    assert (out / "views" / "all.md").is_file()


def _synced_pool(tmp_path: Path) -> Path:
    sync_pool = _load_sync_pool().sync_pool
    problem = problem_contract("ORP-0001", "Synced example")
    source_root = tmp_path / "input"
    dump_json(source_root / "ORP-0001-draft" / "problem.json", problem)
    out = tmp_path / "pool"
    sync_pool(source_root, out)
    dump_yaml(out / "relations.yaml", {"schema_version": 1, "relations": []})
    return out


def test_validate_pool_accepts_fresh_synced_pool(tmp_path: Path) -> None:
    assert validate_pool(_synced_pool(tmp_path)) == []


def test_validate_pool_flags_missing_generated_views(tmp_path: Path) -> None:
    pool = _synced_pool(tmp_path)
    (pool / "views" / "all.md").unlink()
    (pool / "views" / "by-domain.md").unlink()
    errors = validate_pool(pool)
    assert "missing generated view: all.md" in errors
    assert "missing generated view: by-domain.md" in errors


def test_validate_pool_flags_stale_view_content(tmp_path: Path) -> None:
    pool = _synced_pool(tmp_path)
    view = pool / "views" / "all.md"
    view.write_text(
        view.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8"
    )
    errors = validate_pool(pool)
    assert any(
        error.startswith("stale generated view: all.md") for error in errors
    )
