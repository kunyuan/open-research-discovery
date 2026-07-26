from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_research_discovery.benchmark import (
    BenchmarkError,
    export_benchmark_inputs,
    score_benchmark,
    select_stratified_cases,
)
from open_research_discovery.common import dump_json


def _candidate(candidate_id: str, domain: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "domain": domain,
        "canonical_title": f"Candidate {candidate_id}",
        "canonical_statement": "Determine whether the stated finite condition holds.",
        "aliases": ["Finite-condition question"],
        "source_support": [
            {
                "source_key": "global_id:gcn-open-1",
                "exact_excerpt": "Does the finite condition hold?",
            }
        ],
        "source_open_questions": [
            {
                "content": "Does the finite condition hold?",
                "id": "paper:1::open_question",
                "global_id": "gcn-open-1",
                "paper_id": "1",
                "paper_title": "A source paper",
                "paper_doi": "10.0000/source",
                "source_path": "data.papers[].open_questions",
            }
        ],
    }


def test_export_benchmark_inputs_keeps_labels_out_of_input(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "run"
    for candidate_id, domain in (
        ("CAN-111111111111", "mathematics"),
        ("CAN-222222222222", "physics"),
    ):
        dump_json(
            run_dir / "candidates" / candidate_id / "canonicalization.json",
            _candidate(candidate_id, domain),
        )
    dump_json(
        run_dir / "state.json",
        {
            "active_candidate_ids": [
                "CAN-111111111111",
                "CAN-222222222222",
            ]
        },
    )
    selection = tmp_path / "selection.json"
    dump_json(selection, {"candidate_ids": ["CAN-222222222222"]})
    out_dir = tmp_path / "benchmark"
    manifest = export_benchmark_inputs(
        run_dir=run_dir,
        out_dir=out_dir,
        schema_path=repository_root
        / "schemas"
        / "benchmark"
        / "input.schema.json",
        selection_path=selection,
    )
    assert manifest["case_count"] == 1
    case = json.loads(
        (
            out_dir
            / "cases"
            / "ORSB-222222222222"
            / "input.json"
        ).read_text(encoding="utf-8")
    )
    assert case["candidate_id"] == "CAN-222222222222"
    assert case["schema_version"] == 2
    assert case["task"]["identify_solution_route"] is True
    assert case["task"]["judge_ci_buildability"] is True
    assert "importance_level" not in case
    assert "triage" not in json.dumps(case)


def test_export_rejects_unknown_selection_ids(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "run"
    dump_json(
        run_dir
        / "candidates"
        / "CAN-111111111111"
        / "canonicalization.json",
        _candidate("CAN-111111111111", "mathematics"),
    )
    dump_json(
        run_dir / "state.json",
        {"active_candidate_ids": ["CAN-111111111111"]},
    )
    selection = tmp_path / "selection.json"
    dump_json(selection, ["CAN-999999999999"])
    with pytest.raises(BenchmarkError, match="unknown candidate"):
        export_benchmark_inputs(
            run_dir=run_dir,
            out_dir=tmp_path / "benchmark",
            schema_path=repository_root
            / "schemas"
            / "benchmark"
            / "input.schema.json",
            selection_path=selection,
        )


def test_export_ignores_superseded_canonicalization_directories(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "run"
    for candidate_id in ("CAN-111111111111", "CAN-222222222222"):
        dump_json(
            run_dir
            / "candidates"
            / candidate_id
            / "canonicalization.json",
            _candidate(candidate_id, "mathematics"),
        )
    dump_json(
        run_dir / "state.json",
        {"active_candidate_ids": ["CAN-222222222222"]},
    )
    manifest = export_benchmark_inputs(
        run_dir=run_dir,
        out_dir=tmp_path / "benchmark",
        schema_path=repository_root
        / "schemas"
        / "benchmark"
        / "input.schema.json",
    )
    assert manifest["case_count"] == 1
    assert manifest["cases"][0]["candidate_id"] == "CAN-222222222222"


def test_benchmark_prediction_and_gold_schemas_are_valid() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    for name in ("prediction", "gold"):
        schema = json.loads(
            (
                repository_root
                / "schemas"
                / "benchmark"
                / f"{name}.schema.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)


def test_score_benchmark_reports_unsafe_dispatch_false_positive(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    case_id = "ORSB-111111111111"
    prediction = {
        "schema_version": 2,
        "case_id": case_id,
        "importance": {
            "label": "high",
            "confidence": 0.9,
            "rationale": "The result would change a shared method.",
            "consequences_of_progress": "A common bottleneck would be removed.",
        },
        "review": {
            "scope": "result-only",
            "confidence": 0.8,
            "solution_route": "Submit a finite certificate.",
            "route_scientific_effect": "resolves-core",
            "route_sufficiency": True,
            "route_scope_limitations": "None.",
            "expected_artifact": "A finite certificate.",
            "acceptance_boundary": "Check the certificate only.",
            "rationale": "The predicate appears finite.",
        },
        "ci": {
            "buildability": "machine",
            "confidence": 0.8,
            "verification_contract": "Parse and recompute the predicate.",
            "pseudocode": ["assert verify(candidate)"],
            "estimated_runtime": "under one minute",
            "timeout_minutes": 5,
            "rationale": "Exact arithmetic appears sufficient.",
        },
    }
    gold = {
        "schema_version": 2,
        "case_id": case_id,
        "label_status": "silver",
        "as_of_date": "2026-07-26",
        "current_status": "still-open",
        "surviving_core": "Establish the general mechanism experimentally.",
        "importance": {
            "label": "medium",
            "rationale": "The result is field-specific.",
            "evidence_refs": ["source-1"],
        },
        "review": {
            "scope": "expert-intensive",
            "solution_route": "Establish the general mechanism experimentally.",
            "route_scientific_effect": "proves-core",
            "route_sufficiency": True,
            "route_scope_limitations": "Requires causal evidence across the stated regime.",
            "expected_artifact": "A multi-method experimental dossier.",
            "acceptance_boundary": "Experts must assess causal sufficiency.",
            "rationale": "A finite certificate cannot establish the mechanism.",
        },
        "ci": {
            "buildability": "not-buildable",
            "verification_contract": "No bounded automated acceptance predicate exists.",
            "pseudocode": [],
            "estimated_runtime": "not bounded",
            "timeout_minutes": 1440,
            "rationale": "Wet-lab and specialist interpretation are load-bearing.",
        },
        "adjudication": {
            "blind_reviews": ["judge-a.json", "judge-b.json"],
            "agreement": "full",
            "disagreements": [],
            "notes": "Both judges found the same verification boundary.",
        },
    }
    dump_json(tmp_path / "predictions" / "prediction.json", prediction)
    dump_json(tmp_path / "gold" / "gold.json", gold)
    report = score_benchmark(
        predictions_root=tmp_path / "predictions",
        gold_root=tmp_path / "gold",
        prediction_schema=repository_root
        / "schemas"
        / "benchmark"
        / "prediction.schema.json",
        gold_schema=repository_root
        / "schemas"
        / "benchmark"
        / "gold.schema.json",
    )
    assert report["case_count"] == 1
    assert report["unsafe_dispatch_false_positives"] == 1
    assert report["dispatch_precision"] == 0.0
    assert report["importance_accuracy"] == 0.0
    assert report["route_sufficiency_accuracy"] == 1.0
    assert report["route_effect_accuracy"] == 0.0


def test_select_stratified_cases_balances_domains_and_rare_tags(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidates = [
        ("CAN-111111111111", "mathematics", "pass", "high", "result-only"),
        (
            "CAN-222222222222",
            "mathematics",
            "pass",
            "medium",
            "result-and-derivation",
        ),
        (
            "CAN-333333333333",
            "mathematics",
            "low_priority",
            "low",
            "expert-intensive",
        ),
        ("CAN-444444444444", "physics", "pass", "high", "result-only"),
        (
            "CAN-555555555555",
            "physics",
            "pass",
            "medium",
            "result-and-derivation",
        ),
        (
            "CAN-666666666666",
            "physics",
            "low_priority",
            "low",
            "expert-intensive",
        ),
    ]
    for candidate_id, domain, gate, importance, review_scope in candidates:
        candidate_dir = run_dir / "candidates" / candidate_id
        dump_json(
            candidate_dir / "canonicalization.json",
            _candidate(candidate_id, domain),
        )
        dump_json(
            candidate_dir / "triage.json",
            {
                "gate": gate,
                "importance_level": importance,
                "solution_route": "Submit the scoped result.",
                "route_scientific_effect": (
                    "uncertain"
                    if gate == "low_priority"
                    else "resolves-core"
                ),
                "route_sufficiency": gate != "low_priority",
                "route_scope_limitations": "Limited to the atomic candidate.",
                "review_scope": review_scope,
                "ci_feasibility": (
                    "blocked" if gate == "low_priority" else "pseudocode"
                ),
                "verification_mode": (
                    "expert-review"
                    if review_scope == "expert-intensive"
                    else "machine-checkable"
                ),
                "verification_ease": (
                    "hard" if review_scope == "expert-intensive" else "easy"
                ),
                "artifact_type": (
                    "experimental-result"
                    if review_scope == "expert-intensive"
                    else "counterexample"
                ),
            },
        )
    dump_json(
        run_dir / "state.json",
        {"active_candidate_ids": [item[0] for item in candidates]},
    )
    output = select_stratified_cases(
        run_dir=run_dir,
        per_domain=2,
        out_path=tmp_path / "selection.json",
    )
    assert len(output["candidate_ids"]) == 4
    by_domain = {}
    for item in output["selected"]:
        by_domain.setdefault(item["domain"], []).append(item)
    assert {domain: len(items) for domain, items in by_domain.items()} == {
        "mathematics": 2,
        "physics": 2,
    }
    assert all(
        any(
            item["provisional"]["gate"] == "low_priority"
            for item in domain_items
        )
        for domain_items in by_domain.values()
    )


def test_select_stratified_cases_can_limit_domains(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidates = [
        ("CAN-111111111111", "mathematics"),
        ("CAN-222222222222", "physics"),
        ("CAN-333333333333", "biology"),
    ]
    for candidate_id, domain in candidates:
        candidate_dir = run_dir / "candidates" / candidate_id
        dump_json(
            candidate_dir / "canonicalization.json",
            _candidate(candidate_id, domain),
        )
        dump_json(
            candidate_dir / "triage.json",
            {
                "gate": "pass",
                "importance_level": "high",
                "solution_route": "Submit one finite counterexample.",
                "route_scientific_effect": "refutes-core",
                "route_sufficiency": True,
                "route_scope_limitations": "Accepts refutation only.",
                "review_scope": "result-only",
                "ci_feasibility": "pseudocode",
                "verification_mode": "machine-checkable",
                "verification_ease": "easy",
                "artifact_type": "counterexample",
            },
        )
    dump_json(
        run_dir / "state.json",
        {"active_candidate_ids": [item[0] for item in candidates]},
    )
    output = select_stratified_cases(
        run_dir=run_dir,
        per_domain=1,
        domains=["mathematics", "physics"],
        out_path=tmp_path / "selection.json",
    )
    assert output["domains"] == ["mathematics", "physics"]
    assert {
        item["domain"] for item in output["selected"]
    } == {"mathematics", "physics"}
    assert "biology" not in {
        item["domain"] for item in output["selected"]
    }
