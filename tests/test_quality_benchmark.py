from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_research_discovery.agent import AgentRun, strict_output_schema_errors
from open_research_discovery.common import dump_json
from open_research_discovery.quality import (
    EvidenceFetcher,
    QUALITY_RUBRIC,
    QualityError,
    _entry,
    build_quality_dataset,
    classify_identifier,
    evaluate_quality,
    score_quality,
    validate_quality_dataset,
)


REPO = Path(__file__).resolve().parents[1]
INPUT_SCHEMA = REPO / "schemas" / "quality" / "input.schema.json"
PREDICTION_SCHEMA = REPO / "schemas" / "quality" / "prediction.schema.json"
GOLD_SCHEMA = REPO / "schemas" / "quality" / "gold.schema.json"
PROBLEM_SCHEMA = REPO / "schemas" / "problem.schema.json"

VALID_README = """\
# A problem title

Introductory sentence.

## Background

Background text.

## Problem Statement

Statement text.

## Scientific Significance

Significance text.

## Answer Types

A proof or a counterexample.

## Verification Standard

Standard text.

## Current Progress

- Audit date: `2026-08-01`

## References

1. The source paper.
"""


def _problem(
    problem_id: str = "ORP-0001",
    *,
    statement: str = (
        "Determine whether every finite bipartite graph with maximum "
        "degree three admits a proper edge coloring with four colors."
    ),
    sources: list[dict] | None = None,
    evidence: list[dict] | None = None,
    checklist: str = "Confirm the witness satisfies the predicate.",
) -> dict:
    source_records = sources if sources is not None else [
        {
            "title": "The source paper",
            "identifier": "10.1234/source.paper",
            "url": "https://doi.org/10.1234/source.paper",
        }
    ]
    evidence_records = evidence if evidence is not None else [
        {
            "title": "A later survey",
            "identifier": "2101.00001",
            "url": "https://arxiv.org/abs/2101.00001",
        }
    ]

    def reference(record: dict) -> str:
        title = str(record.get("title") or "Untitled reference")
        identifier = str(record.get("identifier") or "")
        url = str(record.get("url") or "")
        parts = [title]
        if identifier:
            parts.append(identifier)
        if url:
            parts.append(url)
        return " — ".join(parts)

    return {
        "schema_version": "1.0",
        "problem_id": problem_id,
        "parent_problem_id": None,
        "subproblem_ids": [],
        "title": f"Problem {problem_id}",
        "abstract": "Determine a finite graph-coloring boundary case.",
        "background": "Edge coloring is a basic graph invariant.",
        "references": [
            reference(record) for record in [*source_records, *evidence_records]
        ],
        "previous_progress": [
            "Five colors are known to suffice by a greedy argument."
        ],
        "problem_statement": statement,
        "scientific_significance": {
            "graph theory": {
                "level": "high",
                "description": "Settles a recognized coloring boundary case.",
            }
        },
        "solution_difficulty": [
            "A proof must control all finite bipartite graphs in the class."
        ],
        "verification_contract": {
            "proof": {
                "contract": checklist,
                "ci_contract": None,
            },
            "counterexample graph": {
                "contract": (
                    "Accept an explicit finite graph exactly when it is "
                    "bipartite, has maximum degree three, and has no valid "
                    "four-edge-coloring."
                ),
                "ci_contract": (
                    "Parse the graph, check bipartiteness and maximum degree, "
                    "then exhaustively reject every four-edge-coloring."
                ),
            },
        },
        "verification_difficulty": {
            "score": 1,
            "rationale": (
                "After mechanical witness checking, only local proof review "
                "or specification matching remains."
            ),
        },
    }


def _found(
    kind: str,
    identifier: str,
    title: str,
    *,
    authors: list[str] | None = None,
    year: int | None = 2020,
) -> dict:
    return _entry(
        kind,
        identifier,
        status="found",
        metadata={
            "title": title,
            "authors": authors or [],
            "venue": "Journal of Testing",
            "year": year,
            "doi": identifier if kind == "doi" else "",
            "url": "",
        },
        fetched_at="2026-08-06T00:00:00+00:00",
    )


def _happy_fetch(kind: str, identifier: str) -> dict:
    data = {
        "10.1234/source.paper": ("The source paper", ["Alice Smith"], 2020),
        "2101.00001": ("A later survey", ["Bob Jones"], 2021),
    }
    title, authors, year = data.get(
        identifier, (f"Work at {identifier}", [], 2020)
    )
    return _found(kind, identifier, title, authors=authors, year=year)


def _build(
    tmp_path: Path,
    problems: list[dict],
    *,
    fetch=_happy_fetch,
) -> Path:
    manifest_dir = tmp_path / "manifests"
    for problem in problems:
        dump_json(manifest_dir / f"{problem['problem_id']}.json", problem)
    out_dir = tmp_path / "dataset"
    build_quality_dataset(
        out_dir=out_dir,
        input_schema=INPUT_SCHEMA,
        problem_schema=PROBLEM_SCHEMA,
        manifest_inputs=[manifest_dir],
        fetcher=fetch,
    )
    return out_dir


def test_quality_schemas_are_valid() -> None:
    for path in (INPUT_SCHEMA, PREDICTION_SCHEMA, GOLD_SCHEMA):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    prediction_schema = json.loads(PREDICTION_SCHEMA.read_text(encoding="utf-8"))
    assert strict_output_schema_errors(prediction_schema) == []


def test_quality_rubric_allows_motivated_generalization() -> None:
    assert "Literal equality with the source is not required" in QUALITY_RUBRIC
    assert "Difference from the source alone is never a defect" in QUALITY_RUBRIC
    assert "determinate problem" in QUALITY_RUBRIC


def test_classify_identifier() -> None:
    assert classify_identifier("10.1234/x") == ("doi", "10.1234/x")
    assert classify_identifier("doi:10.1234/x") == ("doi", "10.1234/x")
    assert classify_identifier("https://doi.org/10.1234/x") == (
        "doi",
        "10.1234/x",
    )
    assert classify_identifier("2101.00001") == ("arxiv", "2101.00001")
    assert classify_identifier("arXiv:2101.00001v2") == ("arxiv", "2101.00001v2")
    assert classify_identifier("https://arxiv.org/abs/2101.00001") == (
        "arxiv",
        "2101.00001",
    )
    assert classify_identifier("hep-th/9901001") == ("arxiv", "hep-th/9901001")
    assert classify_identifier("https://example.org/page") == (
        "url",
        "https://example.org/page",
    )
    assert classify_identifier("some opaque handle") == (
        "other",
        "some opaque handle",
    )


def test_offline_fetcher_skips_and_serves_cache(tmp_path: Path) -> None:
    fetcher = EvidenceFetcher(cache_dir=tmp_path / "cache", offline=True)
    entry = fetcher.fetch("doi", "10.1234/uncached")
    assert entry["status"] == "skipped"
    cached_entry = _found("doi", "10.9999/cached", "A cached work")
    key = hashlib.sha256(
        ("doi\0" + "10.9999/cached").encode("utf-8")
    ).hexdigest()
    dump_json(tmp_path / "cache" / f"{key}.json", cached_entry)
    assert fetcher.fetch("doi", "10.9999/cached") == cached_entry


def test_build_from_run_dir_collects_readme_and_provenance(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "CAN-ABCDEF012345"
    dump_json(
        run_dir / "candidates" / candidate_id / "problem.json",
        _problem("ORP-0007"),
    )
    repo_dir = tmp_path / "solutions" / "ORP-0007-edge-coloring"
    (repo_dir).mkdir(parents=True)
    (repo_dir / "README.md").write_text(VALID_README, encoding="utf-8")
    dump_json(
        run_dir / "state.json",
        {"candidates": {candidate_id: {"problem_repo": str(repo_dir)}}},
    )
    out_dir = tmp_path / "dataset"
    manifest = build_quality_dataset(
        out_dir=out_dir,
        input_schema=INPUT_SCHEMA,
        problem_schema=PROBLEM_SCHEMA,
        run_dir=run_dir,
        fetcher=_happy_fetch,
    )
    assert manifest["case_count"] == 1
    case = json.loads(
        (out_dir / "cases" / "ORP-0007" / "input.json").read_text(
            encoding="utf-8"
        )
    )
    assert case["case_id"] == "ORP-0007"
    assert case["contract_valid"] is True
    assert case["validation_errors"] == []
    assert case["readme_markdown"] == VALID_README
    assert case["provenance"]["origin"] == "run_dir"
    assert case["provenance"]["candidate_id"] == candidate_id
    assert {
        (entry["kind"], entry["identifier"])
        for entry in case["frozen_evidence"]
    } == {("doi", "10.1234/source.paper"), ("arxiv", "2101.00001")}


def test_build_from_pool_uses_catalog_snapshots(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    dump_json(pool / "problems" / "ORP-0001.json", _problem("ORP-0001"))
    dump_json(pool / "problems" / "ORP-0002.json", _problem("ORP-0002"))
    with (pool / "catalog.jsonl").open("w", encoding="utf-8") as handle:
        for problem_id in ("ORP-0001", "ORP-0002"):
            handle.write(json.dumps({"id": problem_id}) + "\n")
    out_dir = tmp_path / "dataset"
    manifest = build_quality_dataset(
        out_dir=out_dir,
        input_schema=INPUT_SCHEMA,
        problem_schema=PROBLEM_SCHEMA,
        pool_root=pool,
        fetcher=_happy_fetch,
    )
    assert manifest["case_count"] == 2
    case = json.loads(
        (out_dir / "cases" / "ORP-0001" / "input.json").read_text(
            encoding="utf-8"
        )
    )
    assert case["provenance"]["origin"] == "pool"
    assert case["readme_markdown"] == ""


def test_build_keeps_invalid_contract_as_flagged_case(tmp_path: Path) -> None:
    broken = _problem("ORP-0009")
    del broken["verification_contract"]
    out_dir = _build(tmp_path, [_problem("ORP-0001"), broken])
    manifest = json.loads(
        (out_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["case_count"] == 2
    record = {
        item["case_id"]: item for item in manifest["cases"]
    }["ORP-0009"]
    assert record["contract_valid"] is False
    case = json.loads(
        (out_dir / "cases" / "ORP-0009" / "input.json").read_text(
            encoding="utf-8"
        )
    )
    assert case["contract_valid"] is False
    assert any(
        "verification_contract" in error
        for error in case["validation_errors"]
    )


def _mechanical_issues(dataset: Path, tmp_path: Path) -> dict:
    report = score_quality(
        dataset_dir=dataset,
        input_schema=INPUT_SCHEMA,
        prediction_schema=PREDICTION_SCHEMA,
        gold_schema=GOLD_SCHEMA,
    )
    assert report["mode"] == "mechanical-only"
    return report


def test_mechanical_detects_hallucinated_identifier(tmp_path: Path) -> None:
    def fetch(kind: str, identifier: str) -> dict:
        if identifier == "10.1234/source.paper":
            return _entry(
                kind,
                identifier,
                status="not_found",
                detail="Crossref has no work for this DOI",
                fetched_at="2026-08-06T00:00:00+00:00",
            )
        return _happy_fetch(kind, identifier)

    dataset = _build(tmp_path, [_problem("ORP-0001")], fetch=fetch)
    report = _mechanical_issues(dataset, tmp_path)
    issues = report["cases"][0]["mechanical_issues"]
    assert any(
        issue["type"] == "hallucinated_identifier"
        and issue["severity"] == "critical"
        for issue in issues
    )
    assert report["identifiers"]["not_found"] == 1
    assert report["identifiers"]["hallucination_rate"] == pytest.approx(0.5)


def test_mechanical_detects_title_and_author_mismatch(tmp_path: Path) -> None:
    evidence = [
        {
            "title": "A later survey",
            "identifier": "2101.00001",
            "url": "https://arxiv.org/abs/2101.00001",
            "date": "2021-01-15",
            "authors": ["Bob Jones"],
            "content_level": "abstract",
            "relation": "continuing_open",
            "supports": "Lists the problem as still open.",
            "direct_support": True,
        }
    ]

    def fetch(kind: str, identifier: str) -> dict:
        if identifier == "2101.00001":
            # Frozen metadata describes a completely different work.
            return _found(
                kind,
                identifier,
                "Quantum error correction thresholds",
                authors=["Carol Doe", "Dan Roe"],
                year=2021,
            )
        return _happy_fetch(kind, identifier)

    dataset = _build(
        tmp_path, [_problem("ORP-0001", evidence=evidence)], fetch=fetch
    )
    report = _mechanical_issues(dataset, tmp_path)
    issues = report["cases"][0]["mechanical_issues"]
    types = {issue["type"] for issue in issues}
    assert "metadata_mismatch" in types
    assert report["identifiers"]["metadata_error_rate"] > 0


def test_mechanical_detects_url_mismatch_without_fetch(tmp_path: Path) -> None:
    sources = [
        {
            "source_key": "src-1",
            "kind": "paper",
            "title": "The source paper",
            "identifier": "10.1234/source.paper",
            "url": "https://unrelated.example.org/record/999",
            "locator": "Section 4",
            "date": "2020-05-01",
            "exact_excerpt": "It remains open whether four colors suffice.",
            "surrounding_context": "The authors pose the question.",
            "source_intent": "Pose the open question.",
            "relationship": "Origin of this problem.",
            "explicit_open_question": True,
        }
    ]
    dataset = _build(tmp_path, [_problem("ORP-0001", sources=sources)])
    report = _mechanical_issues(dataset, tmp_path)
    issues = report["cases"][0]["mechanical_issues"]
    assert any(issue["type"] == "url_mismatch" for issue in issues)


def test_mechanical_uses_only_contract_fields(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    candidate_id = "CAN-ABCDEF012345"
    dump_json(
        run_dir / "candidates" / candidate_id / "problem.json",
        _problem(
            "ORP-0010",
            checklist="Review the complete proof against the statement.",
        ),
    )
    dump_json(run_dir / "state.json", {"candidates": {}})
    out_dir = tmp_path / "dataset"
    build_quality_dataset(
        out_dir=out_dir,
        input_schema=INPUT_SCHEMA,
        problem_schema=PROBLEM_SCHEMA,
        run_dir=run_dir,
        fetcher=_happy_fetch,
    )
    report = _mechanical_issues(out_dir, tmp_path)
    issues = report["cases"][0]["mechanical_issues"]
    types = {issue["type"] for issue in issues}
    assert "alignment_missing" not in types
    assert "authoritative_formulation_missing" not in types


def test_duplicate_detection_hits_and_does_not_overreport(
    tmp_path: Path,
) -> None:
    near_duplicate = (
        "Determine whether every finite bipartite graph with maximum "
        "degree three admits a proper edge coloring with five colors."
    )
    distinct = (
        "Does there exist a transcendental entire function whose "
        "singular set is exactly two points?"
    )
    dataset = _build(
        tmp_path,
        [
            _problem("ORP-0001"),
            _problem("ORP-0002", statement=near_duplicate),
            _problem("ORP-0003", statement=distinct),
        ],
    )
    report = _mechanical_issues(dataset, tmp_path)
    pairs = report["duplicates"]["suspect_pairs"]
    assert len(pairs) == 1
    assert {pairs[0]["left"], pairs[0]["right"]} == {"ORP-0001", "ORP-0002"}
    flagged = {
        issue["type"]
        for case in report["cases"]
        for issue in case["mechanical_issues"]
    }
    assert "duplicate_suspect" in flagged
    by_case = {case["case_id"]: case for case in report["cases"]}
    assert not any(
        issue["type"] == "duplicate_suspect"
        for issue in by_case["ORP-0003"]["mechanical_issues"]
    )


class _FakeQualityRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs) -> AgentRun:
        self.calls.append(kwargs)
        case_id = kwargs["output_path"].parent.name
        output = {
            "schema_version": 1,
            "case_id": case_id,
            **{
                dimension: {
                    "score": 3,
                    "issues": [],
                    "rationale": "No defect found in this dimension.",
                }
                for dimension in (
                    "citation_accuracy",
                    "scientific_soundness",
                    "scope_fidelity",
                    "verification_executability",
                    "evidence_relevance",
                )
            },
            "overall": {
                "grade": "A",
                "rationale": "Publishable as-is.",
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


def test_evaluate_is_blind_offline_and_resumable(tmp_path: Path) -> None:
    dataset = _build(tmp_path, [_problem("ORP-0001")])
    runner = _FakeQualityRunner()
    report = evaluate_quality(
        dataset_dir=dataset,
        out_dir=tmp_path / "run",
        input_schema=INPUT_SCHEMA,
        prediction_schema=PREDICTION_SCHEMA,
        runner=runner,
    )
    assert report["network_policy"] == "offline"
    assert report["case_count"] == 1
    assert runner.calls[0]["role"] == "quality-review"
    prompt = runner.calls[0]["prompt"]
    assert "citation_accuracy" in prompt
    assert "frozen_evidence" in prompt
    assert "owns its scientific target" in prompt
    # No pipeline context: the reviewer must not see build-time verdicts.
    assert "contract_valid" not in prompt
    assert "validation_errors" not in prompt
    resumed = evaluate_quality(
        dataset_dir=dataset,
        out_dir=tmp_path / "run",
        input_schema=INPUT_SCHEMA,
        prediction_schema=PREDICTION_SCHEMA,
        runner=runner,
        resume=True,
    )
    assert len(runner.calls) == 1
    assert resumed["predictions"][0]["reused"] is True


def test_evaluate_rejects_live_retrieval_inputs(tmp_path: Path) -> None:
    dataset = _build(tmp_path, [_problem("ORP-0001")])
    input_path = dataset / "cases" / "ORP-0001" / "input.json"
    case = json.loads(input_path.read_text(encoding="utf-8"))
    case["evidence_mode"] = "live-retrieval"
    dump_json(input_path, case)
    with pytest.raises(QualityError, match="not frozen-evidence"):
        evaluate_quality(
            dataset_dir=dataset,
            out_dir=tmp_path / "run",
            input_schema=INPUT_SCHEMA,
            prediction_schema=PREDICTION_SCHEMA,
            runner=_FakeQualityRunner(),
        )


def _gold(case_id: str, *, citation_score: int = 3, grade: str = "A") -> dict:
    return {
        "schema_version": 1,
        "case_id": case_id,
        "label_status": "gold",
        "as_of_date": "2026-08-06",
        **{
            dimension: {
                "score": (
                    citation_score
                    if dimension == "citation_accuracy"
                    else 3
                ),
                "rationale": "Expert blind label.",
            }
            for dimension in (
                "citation_accuracy",
                "scientific_soundness",
                "scope_fidelity",
                "verification_executability",
                "evidence_relevance",
            )
        },
        "overall": {"grade": grade, "rationale": "Expert blind grade."},
        "notes": "",
    }


def _evaluate(dataset: Path, tmp_path: Path) -> Path:
    evaluate_quality(
        dataset_dir=dataset,
        out_dir=tmp_path / "run",
        input_schema=INPUT_SCHEMA,
        prediction_schema=PREDICTION_SCHEMA,
        runner=_FakeQualityRunner(),
    )
    return tmp_path / "run" / "predictions"


def test_score_with_gold_reports_per_dimension_accuracy(
    tmp_path: Path,
) -> None:
    dataset = _build(tmp_path, [_problem("ORP-0001")])
    predictions = _evaluate(dataset, tmp_path)
    gold_root = tmp_path / "gold"
    dump_json(gold_root / "ORP-0001.json", _gold("ORP-0001", citation_score=2))
    report = score_quality(
        dataset_dir=dataset,
        input_schema=INPUT_SCHEMA,
        prediction_schema=PREDICTION_SCHEMA,
        gold_schema=GOLD_SCHEMA,
        predictions_root=predictions,
        gold_root=gold_root,
    )
    assert report["mode"] == "gold"
    assert report["dimensions"]["citation_accuracy"]["exact_accuracy"] == 0.0
    assert (
        report["dimensions"]["citation_accuracy"]["mean_absolute_error"]
        == 1.0
    )
    assert report["dimensions"]["scope_fidelity"]["exact_accuracy"] == 1.0
    assert report["overall_grade_accuracy"] == 1.0


def test_score_standalone_reports_scores_and_aggregates(
    tmp_path: Path,
) -> None:
    dataset = _build(tmp_path, [_problem("ORP-0001")])
    predictions = _evaluate(dataset, tmp_path)
    report = score_quality(
        dataset_dir=dataset,
        input_schema=INPUT_SCHEMA,
        prediction_schema=PREDICTION_SCHEMA,
        gold_schema=GOLD_SCHEMA,
        predictions_root=predictions,
    )
    assert report["mode"] == "standalone"
    assert report["dimensions"]["citation_accuracy"]["mean_score"] == 3.0
    assert report["dimensions"]["citation_accuracy"]["exact_accuracy"] is None
    assert report["grade_distribution"] == {"A": 1}
    case = report["cases"][0]
    assert case["scores"]["evidence_relevance"] == 3
    assert case["grade"] == "A"
    assert case["mechanical_issues"] == [] or all(
        issue["type"] != "hallucinated_identifier"
        for issue in case["mechanical_issues"]
    )


def test_validate_dataset_inputs_only_and_gold_coverage(
    tmp_path: Path,
) -> None:
    broken = _problem("ORP-0009")
    del broken["verification_contract"]
    dataset = _build(tmp_path, [_problem("ORP-0001"), broken])
    with pytest.raises(QualityError, match="gold directory does not exist"):
        validate_quality_dataset(
            dataset_dir=dataset,
            input_schema=INPUT_SCHEMA,
            gold_schema=GOLD_SCHEMA,
        )
    report = validate_quality_dataset(
        dataset_dir=dataset,
        input_schema=INPUT_SCHEMA,
        gold_schema=GOLD_SCHEMA,
        require_gold=False,
    )
    assert report["case_count"] == 2
    assert report["invalid_count"] == 1
    assert report["gold_count"] == 0
    for problem_id in ("ORP-0001", "ORP-0009"):
        dump_json(dataset / "gold" / f"{problem_id}.json", _gold(problem_id))
    report = validate_quality_dataset(
        dataset_dir=dataset,
        input_schema=INPUT_SCHEMA,
        gold_schema=GOLD_SCHEMA,
    )
    assert report["gold_count"] == 2
