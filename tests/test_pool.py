from open_research_discovery.pool import (
    VIEW_SPECS,
    dedup_candidates,
    field_matches,
    filter_records,
    normalize_text,
    problem_to_record,
    statement_fingerprint,
)


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


def test_filter_records_uses_intersection() -> None:
    records = [
        record("OMP-0001", "one"),
        record("OMP-0002", "two", route="status-audit"),
    ]
    selected = filter_records(
        records,
        {"importance_level": {"high"}, "route": {"candidate-result"}},
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
            "checked_at": "2026-07-25",
            "conclusion": {
                "label": "likely_open",
                "confidence": "medium",
                "rationale": "Later work treats special cases but gives no closure.",
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
    assert "special cases" in record["resolution_rationale"]
