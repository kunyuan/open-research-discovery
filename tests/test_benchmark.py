from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_research_discovery.agent import AgentRun
from open_research_discovery.benchmark import (
    CONTRACT_REVIEW_FIELDS,
    BenchmarkError,
    evaluate_benchmark,
    score_benchmark,
    validate_benchmark_dataset,
)
from open_research_discovery.common import dump_json


def _contract() -> dict:
    return {
        "schema_version": "1.0",
        "problem_id": "ORP-TEST-1",
        "parent_problem_id": None,
        "subproblem_ids": [],
        "title": "Determine the fixed finite invariant",
        "abstract": "Determine one invariant for the fixed finite model.",
        "background": "The source establishes the finite model but not its invariant.",
        "references": ["Source paper — doi:10.0000/example"],
        "previous_progress": ["The model and elementary bounds are known."],
        "problem_statement": "Compute the invariant for the fixed model M.",
        "scientific_significance": {
            "finite-model theory": {
                "level": "medium",
                "description": "The value closes the classification of M.",
            }
        },
        "solution_difficulty": ["The state space grows exponentially."],
        "verification_contract": {
            "exact value": {
                "contract": "Submit the exact integer and a derivation for M.",
                "ci_contract": "Parse the integer and independently enumerate M.",
            }
        },
        "verification_difficulty": {
            "score": 1,
            "rationale": "Enumeration is mechanical; only model fidelity remains.",
        },
    }


def _field_reviews(
    overrides: dict[str, str] | None = None,
) -> dict[str, dict]:
    overrides = overrides or {}
    return {
        field: {
            "verdict": overrides.get(field, "pass"),
            "rationale": f"Reference judgment for {field}.",
            "evidence_refs": [] if field != "evidence_fidelity" else ["SRC-1"],
        }
        for field in CONTRACT_REVIEW_FIELDS
    }


def _review(
    case_id: str,
    *,
    overrides: dict[str, str] | None = None,
    verdict: str = "accept",
) -> dict:
    return {
        "schema_version": 1,
        "case_id": case_id,
        "problem_id": "ORP-TEST-1",
        "field_reviews": _field_reviews(overrides),
        "overall_verdict": verdict,
        "overall_rationale": "The field judgments determine this verdict.",
        "must_fix": [
            {"field": field, "issue": f"Repair {field}."}
            for field, status in (overrides or {}).items()
            if status != "pass"
        ],
        "rewrite_prompt": "Repair every listed field." if verdict == "rewrite" else "",
    }


def _write_dataset(
    tmp_path: Path,
    *,
    evidence_mode: str = "frozen-evidence",
    contract: dict | None = None,
    gold_status: str = "provisional",
    gold_overrides: dict[str, str] | None = None,
    gold_verdict: str = "accept",
) -> Path:
    dataset = tmp_path / "dataset"
    case_id = "ORCB-111111111111"
    input_document = {
        "schema_version": 1,
        "case_id": case_id,
        "domain": "physics",
        "topic": "A fixed finite invariant",
        "candidate_contract": contract or _contract(),
        "frozen_evidence": {
            "sources": [
                {
                    "source_id": "SRC-1",
                    "exact_excerpt": "The invariant remains unknown.",
                    "surrounding_context": "For M, the invariant remains unknown.",
                }
            ]
        },
        "evidence_mode": evidence_mode,
    }
    dump_json(dataset / "cases" / case_id / "input.json", input_document)
    dump_json(
        dataset / "manifest.json",
        {
            "schema_version": 1,
            "benchmark_id": "problem-contract",
            "benchmark_version": "test-v0",
            "case_count": 1,
            "cases": [
                {
                    "case_id": case_id,
                    "domain": "physics",
                    "title": _contract()["title"],
                    "input_path": f"cases/{case_id}/input.json",
                    "gold_path": f"gold/{case_id}/gold.json",
                }
            ],
        },
    )
    reviewers = ["reviewer-a"]
    agreement = "single-review"
    if gold_status in {"silver", "gold"}:
        reviewers.append("reviewer-b")
        agreement = "full"
    dump_json(
        dataset / "gold" / case_id / "gold.json",
        {
            "schema_version": 1,
            "case_id": case_id,
            "label_status": gold_status,
            "as_of_date": "2026-08-03",
            "review": _review(
                case_id,
                overrides=gold_overrides,
                verdict=gold_verdict,
            ),
            "adjudication": {
                "reviewers": reviewers,
                "agreement": agreement,
                "disagreements": [],
                "notes": "Test adjudication.",
            },
        },
    )
    return dataset


def _schema_paths(repository_root: Path) -> dict[str, Path]:
    return {
        "input_schema": repository_root / "schemas/benchmark/input.schema.json",
        "prediction_schema": repository_root
        / "schemas/benchmark/prediction.schema.json",
        "gold_schema": repository_root / "schemas/benchmark/gold.schema.json",
        "problem_schema": repository_root / "schemas/problem-contract.schema.json",
    }


def test_contract_benchmark_schemas_are_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("input", "prediction", "gold"):
        schema = json.loads(
            (root / "schemas" / "benchmark" / f"{name}.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)


def test_validate_reports_provisional_contract_verdicts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    dataset = _write_dataset(
        tmp_path,
        gold_overrides={"problem_statement": "major_issue"},
        gold_verdict="rewrite",
    )
    report = validate_benchmark_dataset(dataset_dir=dataset, **_schema_paths(root))
    assert report["case_count"] == 1
    assert report["label_statuses"] == {"provisional": 1}
    assert report["contract_verdicts"] == {"rewrite": 1}
    assert report["formal_gold_ready"] is False


def test_validate_rejects_invalid_problem_contract(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    invalid = _contract()
    invalid.pop("problem_statement")
    dataset = _write_dataset(tmp_path, contract=invalid)
    with pytest.raises(BenchmarkError, match="invalid candidate contract"):
        validate_benchmark_dataset(dataset_dir=dataset, **_schema_paths(root))


def test_validate_requires_two_reviewers_for_silver(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    dataset = _write_dataset(tmp_path, gold_status="silver")
    gold_path = dataset / "gold/ORCB-111111111111/gold.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    gold["adjudication"]["reviewers"] = ["reviewer-a"]
    dump_json(gold_path, gold)
    with pytest.raises(BenchmarkError, match="fewer than two reviewers"):
        validate_benchmark_dataset(dataset_dir=dataset, **_schema_paths(root))


def test_score_reports_field_metrics_and_unsafe_accept(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    dataset = _write_dataset(
        tmp_path,
        gold_overrides={
            "problem_statement": "major_issue",
            "verification_contract": "major_issue",
            "cross_field_consistency": "minor_issue",
        },
        gold_verdict="rewrite",
    )
    predictions = tmp_path / "predictions"
    dump_json(
        predictions / "ORCB-111111111111/prediction.json",
        _review(
            "ORCB-111111111111",
            overrides={"problem_statement": "major_issue"},
            verdict="accept",
        ),
    )
    report = score_benchmark(
        predictions_root=predictions,
        gold_root=dataset / "gold",
        prediction_schema=root / "schemas/benchmark/prediction.schema.json",
        gold_schema=root / "schemas/benchmark/gold.schema.json",
    )
    assert report["case_count"] == 1
    assert report["unsafe_accept_count"] == 1
    assert report["overall_verdict_accuracy"] == 0.0
    assert report["acceptance_decision_accuracy"] == 0.0
    assert report["issue_detection_recall"] == pytest.approx(1 / 3)
    assert report["major_issue_recall"] == pytest.approx(1 / 2)
    assert report["per_field"]["problem_statement"]["accuracy"] == 1.0
    assert report["formal_gold_ready"] is False


def test_score_rejects_gold_leakage(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    dataset = _write_dataset(tmp_path)
    gold = json.loads(
        (dataset / "gold/ORCB-111111111111/gold.json").read_text(encoding="utf-8")
    )
    predictions = tmp_path / "predictions"
    dump_json(predictions / "prediction.json", gold["review"])
    with pytest.raises(BenchmarkError, match="identical to gold"):
        score_benchmark(
            predictions_root=predictions,
            gold_root=dataset / "gold",
            prediction_schema=root / "schemas/benchmark/prediction.schema.json",
            gold_schema=root / "schemas/benchmark/gold.schema.json",
        )


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs) -> AgentRun:
        self.calls.append(kwargs)
        case_id = kwargs["output_path"].parent.name
        output = _review(case_id)
        dump_json(kwargs["output_path"], output)
        kwargs["events_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["events_path"].write_text("", encoding="utf-8")
        return AgentRun(
            output=output,
            metadata={
                "role": kwargs["role"],
                "network_access": False,
                "sandbox": "read-only",
            },
        )


def test_evaluate_runs_only_offline_contract_review_and_resumes(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    dataset = _write_dataset(tmp_path)
    runner = _FakeRunner()
    out = tmp_path / "evaluation"
    kwargs = {
        "dataset_dir": dataset,
        "out_dir": out,
        "runner": runner,
        "workers": 1,
        "resume": False,
        "input_schema": root / "schemas/benchmark/input.schema.json",
        "prediction_schema": root / "schemas/benchmark/prediction.schema.json",
        "problem_schema": root / "schemas/problem-contract.schema.json",
    }
    report = evaluate_benchmark(**kwargs)
    assert report["task"] == "review-fixed-problem-contract"
    assert report["network_policy"] == "offline"
    assert len(runner.calls) == 1
    assert runner.calls[0]["role"] == "contract-benchmark-reviewer"
    assert "do not generate a replacement" in runner.calls[0]["prompt"]
    assert "scientific_significance" in runner.calls[0]["prompt"]
    assert "verification_difficulty" in runner.calls[0]["prompt"]

    kwargs["resume"] = True
    resumed = evaluate_benchmark(**kwargs)
    assert resumed["predictions"][0]["reused"] is True
    assert len(runner.calls) == 1


def test_evaluate_rejects_live_retrieval_case(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    dataset = _write_dataset(tmp_path)
    input_path = dataset / "cases/ORCB-111111111111/input.json"
    case = json.loads(input_path.read_text(encoding="utf-8"))
    case["evidence_mode"] = "live-retrieval"
    dump_json(input_path, case)
    with pytest.raises(BenchmarkError, match="evidence_mode.*frozen-evidence"):
        evaluate_benchmark(
            dataset_dir=dataset,
            out_dir=tmp_path / "evaluation",
            input_schema=root / "schemas/benchmark/input.schema.json",
            prediction_schema=root / "schemas/benchmark/prediction.schema.json",
            problem_schema=root / "schemas/problem-contract.schema.json",
            runner=_FakeRunner(),
        )
