from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_research_discovery.benchmark import (
    BenchmarkError,
    _gold_dispatch_ready,
    _prediction_dispatch_ready,
    evaluate_benchmark,
    export_benchmark_inputs,
    score_benchmark,
    select_stratified_cases,
    validate_benchmark_dataset,
)
from open_research_discovery.agent import AgentRun
from open_research_discovery.common import dump_json, dump_yaml
from open_research_discovery.ranking import VERIFICATION_DIFFICULTY_RUBRIC


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
    assert case["schema_version"] == 9
    assert case["task"]["describe_expected_result"] is True
    assert "identify_acceptance_obligations" not in case["task"]
    assert case["task"]["judge_verification_difficulty"] is True
    assert case["task"]["judge_ci_buildability"] is True
    assert (
        case["task"]["verification_difficulty_rubric"]
        == VERIFICATION_DIFFICULTY_RUBRIC
    )
    assert case["evidence_mode"] == "frozen-evidence"
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


def test_dispatch_readiness_does_not_require_ci() -> None:
    prediction = {
        "importance": {"label": "high"},
        "solution_review": {"verification_difficulty": 0},
        "ci": {"buildability": "not-buildable"},
    }
    gold = {
        "current_status": "still_open",
        "importance": {"label": "high"},
        "solution_review": {"verification_difficulty": 0},
        "ci": {"buildability": "not-buildable"},
    }
    assert _prediction_dispatch_ready(prediction)
    assert _gold_dispatch_ready(gold)


def test_score_benchmark_reports_unsafe_dispatch_false_positive(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    case_id = "ORSB-111111111111"
    prediction = {
        "schema_version": 9,
        "case_id": case_id,
        "importance": {
            "label": "high",
            "confidence": 0.9,
            "rationale": "The result would change a shared method.",
        },
        "solution_review": {
            "verification_difficulty": 0,
            "confidence": 0.8,
            "expected_result": "A finite certificate.",
            "rationale": (
                "The certificate answers the scoped question, and its "
                "predicate is directly checkable."
            ),
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
        "schema_version": 9,
        "case_id": case_id,
        "label_status": "silver",
        "as_of_date": "2026-07-26",
        "current_status": "still_open",
        "surviving_core": "Establish the general mechanism experimentally.",
        "importance": {
            "label": "medium",
            "rationale": "The result is field-specific.",
            "evidence_refs": ["source-1"],
        },
        "solution_review": {
            "verification_difficulty": 9,
            "expected_result": "A multi-method experimental dossier.",
            "rationale": (
                "The dossier must establish causality across the stated "
                "regime, which requires specialist judgment."
            ),
        },
        "ci": {
            "buildability": "not-buildable",
            "verification_contract": "No bounded automated acceptance predicate exists.",
            "pseudocode": [],
            "estimated_runtime": "not bounded",
            "timeout_minutes": 0,
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


def test_score_benchmark_uses_campaign_verification_threshold(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    case_id = "ORSB-111111111111"
    prediction = {
        "schema_version": 9,
        "case_id": case_id,
        "importance": {
            "label": "high",
            "confidence": 0.9,
            "rationale": "The result would change a shared method.",
        },
        "solution_review": {
            "verification_difficulty": 4,
            "confidence": 0.8,
            "expected_result": "A short derivation plus a final constant.",
            "rationale": (
                "The final constant answers the scoped question; one "
                "standard lemma must be spot-checked."
            ),
        },
        "ci": {
            "buildability": "machine",
            "confidence": 0.8,
            "verification_contract": "Recompute the constant.",
            "pseudocode": ["assert recompute(candidate) == candidate"],
            "estimated_runtime": "under one minute",
            "timeout_minutes": 5,
            "rationale": "Exact arithmetic appears sufficient.",
        },
    }
    gold = {
        "schema_version": 9,
        "case_id": case_id,
        "label_status": "silver",
        "as_of_date": "2026-07-26",
        "current_status": "still_open",
        "surviving_core": "Determine the constant for the stated regime.",
        "importance": {
            "label": "high",
            "rationale": "The result would change a shared method.",
            "evidence_refs": ["source-1"],
        },
        "solution_review": {
            "verification_difficulty": 4,
            "expected_result": "A short derivation plus a final constant.",
            "rationale": (
                "The final constant answers the scoped question; one "
                "standard lemma must be spot-checked."
            ),
        },
        "ci": {
            "buildability": "machine",
            "verification_contract": "Recompute the constant.",
            "pseudocode": ["assert recompute(candidate) == candidate"],
            "estimated_runtime": "under one minute",
            "timeout_minutes": 5,
            "rationale": "Exact arithmetic appears sufficient.",
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
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    dump_yaml(
        run_dir / "campaign.yaml",
        {"limits": {"max_verification_difficulty": 5}},
    )
    kwargs = {
        "predictions_root": tmp_path / "predictions",
        "gold_root": tmp_path / "gold",
        "prediction_schema": repository_root
        / "schemas"
        / "benchmark"
        / "prediction.schema.json",
        "gold_schema": repository_root
        / "schemas"
        / "benchmark"
        / "gold.schema.json",
    }
    campaign_report = score_benchmark(run_dir=run_dir, **kwargs)
    assert campaign_report["max_verification_difficulty"] == 5
    assert campaign_report["cases"][0]["predicted_dispatch_ready"] is True
    assert campaign_report["cases"][0]["gold_dispatch_ready"] is True
    default_report = score_benchmark(**kwargs)
    assert default_report["max_verification_difficulty"] == 3
    assert default_report["cases"][0]["predicted_dispatch_ready"] is False
    assert default_report["cases"][0]["gold_dispatch_ready"] is False


def test_select_stratified_cases_balances_domains_and_rare_tags(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidates = [
        ("CAN-111111111111", "mathematics", "pass", "high", 0),
        (
            "CAN-222222222222",
            "mathematics",
            "pass",
            "medium",
            3,
        ),
        (
            "CAN-333333333333",
            "mathematics",
            "deferred",
            "low",
            9,
        ),
        ("CAN-444444444444", "physics", "pass", "high", 0),
        (
            "CAN-555555555555",
            "physics",
            "pass",
            "medium",
            3,
        ),
        (
            "CAN-666666666666",
            "physics",
            "deferred",
            "low",
            9,
        ),
    ]
    for (
        candidate_id,
        domain,
        gate,
        importance,
        verification_difficulty,
    ) in candidates:
        candidate_dir = run_dir / "candidates" / candidate_id
        dump_json(
            candidate_dir / "canonicalization.json",
            _candidate(candidate_id, domain),
        )
        dump_json(
            candidate_dir / "triage.json",
            {
                "importance_level": importance,
                "expected_result": "The scoped final result.",
                "verification_difficulty": verification_difficulty,
                "ci_status": (
                    "blocked" if gate == "deferred" else "pseudocode"
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
            item["provisional"]["gate"] == "deferred"
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
                "importance_level": "high",
                "expected_result": "One finite counterexample.",
                "verification_difficulty": 0,
                "ci_status": "pseudocode",
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


class _FakeBenchmarkRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs) -> AgentRun:
        self.calls.append(kwargs)
        case_id = kwargs["output_path"].parent.name
        output = {
            "schema_version": 9,
            "case_id": case_id,
            "importance": {
                "label": "medium",
                "confidence": 0.8,
                "rationale": "The question controls a recognized finite boundary.",
            },
            "solution_review": {
                "verification_difficulty": 0,
                "confidence": 0.9,
                "expected_result": "A finite counterexample.",
                "rationale": "The final witness can be checked directly.",
            },
            "ci": {
                "buildability": "machine",
                "confidence": 0.9,
                "verification_contract": "Parse and check the finite witness.",
                "pseudocode": ["assert check(candidate)"],
                "estimated_runtime": "under one minute",
                "timeout_minutes": 5,
                "rationale": "All acceptance predicates are finite.",
            },
        }
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


def _write_dataset(
    tmp_path: Path,
    *,
    case_ids: tuple[str, ...] = ("ORSB-111111111111",),
    evidence_mode: str = "frozen-evidence",
) -> Path:
    repository_root = Path(__file__).resolve().parents[1]
    dataset = tmp_path / "dataset"
    records = []
    for index, case_id in enumerate(case_ids, start=1):
        candidate_id = case_id.replace("ORSB-", "CAN-")
        case = {
            "schema_version": 9,
            "case_id": case_id,
            **_candidate(candidate_id, "mathematics"),
            "frozen_evidence": [
                {
                    "evidence_id": "gcn-open-1",
                    "kind": "source-open-question",
                    "title": "A source paper",
                    "identifier": "10.0000/source",
                    "content_level": "lkm_open_question",
                    "content": "Does the finite condition hold?",
                }
            ],
            "evidence_mode": evidence_mode,
            "task": {
                "judge_importance": True,
                "describe_expected_result": True,
                "judge_verification_difficulty": True,
                "judge_ci_buildability": True,
                "verification_difficulty_rubric": VERIFICATION_DIFFICULTY_RUBRIC,
            },
        }
        path = dataset / "cases" / case_id / "input.json"
        dump_json(path, case)
        schema = json.loads(
            (
                repository_root
                / "schemas"
                / "benchmark"
                / "input.schema.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(schema).validate(case)
        records.append(
            {
                "case_id": case_id,
                "candidate_id": candidate_id,
                "domain": "mathematics",
                "title": f"Case {index}",
                "input_path": str(path.relative_to(dataset)),
            }
        )
    dump_json(
        dataset / "manifest.json",
        {"schema_version": 9, "case_count": len(records), "cases": records},
    )
    return dataset


def _gold(case_id: str, *, positive: bool) -> dict:
    return {
        "schema_version": 9,
        "case_id": case_id,
        "label_status": "silver",
        "as_of_date": "2026-07-27",
        "current_status": "still_open",
        "surviving_core": "Determine the stated finite condition.",
        "importance": {
            "label": "medium" if positive else "low",
            "rationale": "Frozen independent adjudication.",
            "evidence_refs": ["source-open-question"],
        },
        "solution_review": {
            "verification_difficulty": 0,
            "expected_result": "A finite counterexample.",
            "rationale": "The witness itself decides the finite predicate.",
        },
        "ci": {
            "buildability": "machine",
            "verification_contract": "Parse and check the witness.",
            "pseudocode": ["assert check(candidate)"],
            "estimated_runtime": "under one minute",
            "timeout_minutes": 5,
            "rationale": "All predicates are finite.",
        },
        "adjudication": {
            "blind_reviews": ["judge-a.json", "judge-b.json"],
            "agreement": "full",
            "disagreements": [],
            "notes": "Independent labels agree.",
        },
    }


def test_evaluate_benchmark_is_offline_and_uses_only_frozen_inputs(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    dataset = _write_dataset(tmp_path)
    runner = _FakeBenchmarkRunner()
    report = evaluate_benchmark(
        dataset_dir=dataset,
        out_dir=tmp_path / "run",
        input_schema=repository_root
        / "schemas"
        / "benchmark"
        / "input.schema.json",
        prediction_schema=repository_root
        / "schemas"
        / "benchmark"
        / "prediction.schema.json",
        runner=runner,
        workers=1,
    )
    assert report["network_policy"] == "offline"
    assert report["case_count"] == 1
    assert report["predictions"][0]["reused"] is False
    assert runner.calls[0]["role"] == "benchmark-triage"
    assert "Do not search the web, call LKM" in runner.calls[0]["prompt"]
    prediction = json.loads(
        (
            tmp_path
            / "run"
            / "predictions"
            / "ORSB-111111111111"
            / "prediction.json"
        ).read_text(encoding="utf-8")
    )
    assert prediction["case_id"] == "ORSB-111111111111"
    resumed = evaluate_benchmark(
        dataset_dir=dataset,
        out_dir=tmp_path / "run",
        input_schema=repository_root
        / "schemas"
        / "benchmark"
        / "input.schema.json",
        prediction_schema=repository_root
        / "schemas"
        / "benchmark"
        / "prediction.schema.json",
        runner=runner,
        workers=1,
        resume=True,
    )
    assert len(runner.calls) == 1
    assert resumed["predictions"][0]["reused"] is True


def test_evaluate_benchmark_rejects_live_retrieval_inputs(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    dataset = _write_dataset(tmp_path, evidence_mode="live-retrieval")
    with pytest.raises(BenchmarkError, match="not frozen-evidence"):
        evaluate_benchmark(
            dataset_dir=dataset,
            out_dir=tmp_path / "run",
            input_schema=repository_root
            / "schemas"
            / "benchmark"
            / "input.schema.json",
            prediction_schema=repository_root
            / "schemas"
            / "benchmark"
            / "prediction.schema.json",
            runner=_FakeBenchmarkRunner(),
        )


def test_validate_benchmark_requires_positive_and_negative_per_domain(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    case_ids = ("ORSB-111111111111", "ORSB-222222222222")
    dataset = _write_dataset(tmp_path, case_ids=case_ids)
    for case_id, positive in zip(case_ids, (True, False), strict=True):
        dump_json(dataset / "gold" / case_id / "gold.json", _gold(case_id, positive=positive))
    report = validate_benchmark_dataset(
        dataset_dir=dataset,
        input_schema=repository_root
        / "schemas"
        / "benchmark"
        / "input.schema.json",
        gold_schema=repository_root
        / "schemas"
        / "benchmark"
        / "gold.schema.json",
    )
    assert report["domains"]["mathematics"] == {
        "case_count": 2,
        "positive": 1,
        "negative": 1,
    }
