from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from open_research_discovery.agent import AgentRun
from open_research_discovery.campaign import (
    CampaignError,
    CampaignPipeline,
    _tool_version,
)
from open_research_discovery.common import dump_json
from open_research_discovery.lkm import extract_paper_open_questions


class FakeAgentRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.review_count = 0

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> AgentRun:
        self.calls.append(role)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(
            json.dumps({"type": "fake", "role": role}) + "\n",
            encoding="utf-8",
        )
        if role == "discovery":
            output = {
                "domain_id": "mathematics",
                "papers": [
                    {
                        "paper_id": "PAPER-1",
                        "doi": "10.0000/example",
                        "title": "A paper with an explicit open question",
                        "why_relevant": "It studies the target combinatorial invariant.",
                        "evidence": [
                            {
                                "source": "lkm",
                                "identifier": "PAPER-1",
                                "url": "",
                                "content_level": "metadata",
                                "supports": "Paper identity and topic.",
                            }
                        ],
                    }
                ],
                "search_summary": "One source paper was identified.",
            }
        elif role == "canonicalization":
            output = {
                "clusters": [
                    {
                        "canonical_title": "Finite witness for the example bound",
                        "canonical_statement": (
                            "Does there exist a finite object satisfying assumptions "
                            "A and B while violating bound C?"
                        ),
                        "domain": "mathematics",
                        "source_keys": ["global_id:GQ-1"],
                        "aliases": ["Example finite-bound question"],
                        "rationale": "The single source statement forms one problem.",
                    }
                ]
            }
        else:
            candidate_id = re.search(r"CAN-[A-F0-9]{12}", prompt)
            assert candidate_id is not None
            candidate = candidate_id.group(0)
            if role == "triage":
                output = {
                    "candidate_id": candidate,
                    "gate": "pass",
                    "importance_level": "high",
                    "importance_rationale": "A counterexample changes a standard bound.",
                    "consequences_of_progress": "It removes a shared combinatorial bottleneck.",
                    "expected_artifact": "A finite machine-readable witness.",
                    "artifact_type": "counterexample",
                    "verification_mode": "machine-checkable",
                    "verification_ease": "easy",
                    "review_scope": "result-only",
                    "verification_protocol": "Parse and check every assumption and violation.",
                    "ci_feasibility": "pseudocode",
                    "ci_pseudocode": [
                        "candidate = parse_submission()",
                        "assert assumptions(candidate)",
                        "assert violates_bound(candidate)",
                    ],
                    "estimated_review_time": "20 minutes",
                    "estimated_ci_runtime": "under 2 minutes",
                    "ci_timeout_minutes": 5,
                    "rationale": "Important and decidable from a finite result.",
                }
            elif role == "research":
                output = assessment(candidate)
            elif role == "reviewer":
                self.review_count += 1
                revise = self.review_count == 1
                output = {
                    "candidate_id": candidate,
                    "verdict": "revise" if revise else "accept",
                    "checks": {
                        "status_supported": not revise,
                        "major_progress_supported": True,
                        "surviving_core_precise": True,
                        "importance_supported": True,
                        "verification_contract_bounded": True,
                        "ci_contract_specific": True,
                        "evidence_levels_honest": True,
                    },
                    "concerns": (
                        ["Clarify why the 2025 result is only a special case."]
                        if revise
                        else []
                    ),
                    "revision_instructions": (
                        ["State the missing hypothesis in the surviving core."]
                        if revise
                        else []
                    ),
                    "rationale": (
                        "One status relation needs clarification."
                        if revise
                        else "The revised evidence and contracts are sufficient."
                    ),
                }
            else:
                raise AssertionError(role)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dump_json(output_path, output)
        return AgentRun(
            output=output,
            metadata={
                "exit_code": 0,
                "role": role,
                "codex_version": "fake-codex 1.0",
                "model": "fake",
                "prompt_sha256": "fake",
                "schema_sha256": "fake",
                "events": str(events_path),
            },
        )


def assessment(candidate_id: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "canonical_title": "Finite witness for the example bound",
        "canonical_statement": (
            "Find a finite object satisfying assumptions A and B while violating bound C."
        ),
        "definitions": ["A, B, and C are defined in the source record."],
        "scope": "Finite objects under the source paper's conventions.",
        "aliases": ["Example finite-bound question"],
        "resolution_status": "still_open",
        "coverage": "systematic_literature",
        "resolution_conclusion": "likely_open",
        "resolution_confidence": "medium",
        "literature_treatment": (
            "Later work proves a special case but continues to study the general regime."
        ),
        "status_rationale": "The citation chain leaves the general finite regime unsettled.",
        "checked_through": "2026-07-26",
        "major_progress_found": True,
        "major_progress_effect": "narrows",
        "major_progress_summary": "A 2025 paper settles objects of size at most ten.",
        "surviving_open_core": "Find a witness of size greater than ten.",
        "post_progress_decision": "rewrite-core",
        "importance_level": "high",
        "importance_motivation": "The bound is used by several later constructions.",
        "consequences_of_progress": "A witness would invalidate the general bound.",
        "current_best_result": "The bound is proved only for size at most ten.",
        "artifact_type": "counterexample",
        "candidate_format": "JSON object containing the finite witness.",
        "success_condition": "All assumptions hold and exact recomputation violates C.",
        "partial_progress_metrics": ["Largest independently checked near-witness."],
        "verification_mode": "machine-checkable",
        "verification_ease": "easy",
        "verification_protocol": "Exact parsing and deterministic recomputation.",
        "verification_rationale": "The claim is decided by one finite object.",
        "review_scope": "result-only",
        "review_difficulty": "easy",
        "review_checklist": [
            "Parse the submitted object.",
            "Check assumptions A and B.",
            "Recompute and confirm the strict violation of C.",
        ],
        "estimated_review_time": "20 minutes",
        "acceptance_boundary": "Accept only the finite witness under the stated conventions.",
        "ci_status": "pseudocode",
        "ci_pseudocode": [
            "candidate = parse_submission()",
            "assert assumptions(candidate)",
            "assert exact_violation(candidate)",
        ],
        "ci_runner": "ubuntu-latest with exact integer arithmetic",
        "ci_estimated_runtime": "under 2 minutes",
        "ci_timeout_minutes": 5,
        "compute": {
            "expected_scale": "one finite witness",
            "cpu": "1 core",
            "gpu": "none",
            "notes": "Verification is exact and deterministic.",
        },
        "evidence": [
            {
                "source": "lkm",
                "title": "A later special-case result",
                "identifier": "LKM-CLAIM-1",
                "url": "",
                "date": "2025",
                "content_level": "compressed_claim",
                "relation": "special_case",
                "supports": "The bounded-size case is settled.",
                "direct_support": True,
            },
            {
                "source": "web",
                "title": "Author manuscript of the later result",
                "identifier": "10.0000/later",
                "url": "https://example.test/later",
                "date": "2025",
                "content_level": "partial_full_text",
                "relation": "continuing_open",
                "supports": "The general regime remains outside the theorem.",
                "direct_support": True,
            },
        ],
    }


def fake_collector(
    *,
    paper_id: str | None = None,
    doi: str | None = None,
    title: str | None = None,
    raw_out: Path,
    out: Path,
    timeout: float,
) -> dict[str, Any]:
    assert paper_id == "PAPER-1"
    assert timeout == 30
    payload = {
        "code": 0,
        "trace_id": "trace-test",
        "data": {
            "papers": [
                {
                    "paper": {
                        "id": "PAPER-1",
                        "en_title": "A paper with an explicit open question",
                        "doi": "10.0000/example",
                    },
                    "open_questions": [
                        {
                            "content": (
                                "Does there exist a finite object satisfying A and B "
                                "while violating C?"
                            ),
                            "id": "source::open_question",
                            "global_id": "GQ-1",
                        }
                    ],
                    "question": [
                        {
                            "content": "This ordinary question must be ignored.",
                            "id": "ordinary-question",
                        }
                    ],
                }
            ]
        },
    }
    dump_json(raw_out, payload)
    questions = extract_paper_open_questions(payload)
    result = {
        "schema_version": 1,
        "executed_at": "2026-07-26T00:00:00+00:00",
        "endpoint": "https://open.bohrium.com/openapi/v1/lkm/papers/graph",
        "identifier": {"paper_id": paper_id},
        "trace_id": "trace-test",
        "count": len(questions),
        "open_questions": questions,
    }
    dump_json(out, result)
    return result


def test_campaign_runs_end_to_end_and_resumes_without_repeating_agents(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "test-campaign",
        "domains": [
            {
                "id": "mathematics",
                "query": "Find important finite-witness open questions.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 3,
            "questions_per_domain": 10,
            "revision_rounds": 1,
            "lkm_timeout_seconds": 30,
        },
        "agents": {
            "model": "",
            "codex_executable": "codex",
            "sandbox": "read-only",
            "timeout_seconds": 3600,
        },
        "outputs": {
            "runs_root": str(tmp_path / "runs"),
            "problem_root": str(tmp_path / "problems"),
            "pool_root": str(tmp_path / "pool-repo"),
        },
    }
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    agents = FakeAgentRunner()
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="test-run",
        agent_runner=agents,
        paper_collector=fake_collector,
    )
    summary = pipeline.run()
    assert summary["source_open_questions"] == 1
    assert summary["canonical_candidates"] == 1
    assert summary["accepted_problem_ids"] == ["ORP-0001"]
    assert agents.calls == [
        "discovery",
        "canonicalization",
        "triage",
        "research",
        "reviewer",
        "research",
        "reviewer",
    ]

    problem_paths = list((tmp_path / "problems").glob("ORP-0001-*/problem.yaml"))
    assert len(problem_paths) == 1
    problem = yaml.safe_load(problem_paths[0].read_text(encoding="utf-8"))
    assert problem["status"] == "needs-verifier"
    assert problem["resolution_audit"]["coverage"] == "systematic_literature"
    assert problem["resolution_audit"]["surviving_open_core"].endswith(
        "greater than ten."
    )
    assert problem["ci_contract"]["status"] == "pseudocode"
    assert problem["source_open_questions"][0]["source_path"] == (
        "data.papers[].open_questions"
    )
    assert "ordinary question" not in json.dumps(problem)

    raw = pipeline.run_dir / "domains/mathematics/evidence/lkm/paper-001-graph.json"
    assert raw.is_file()
    assert json.loads(raw.read_text(encoding="utf-8"))["trace_id"] == "trace-test"
    state = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    assert state["status"] == "completed"
    assert state["active_candidate_ids"] == [next(iter(state["candidates"]))]
    assert all(
        candidate["canonicalization_active"]
        for candidate in state["candidates"].values()
    )
    assert state["stages"]["campaign.ingest.mathematics"]["tool"] == (
        "direct-lkm-papers-graph-api"
    )
    ranking = json.loads(
        (pipeline.run_dir / "ranking.json").read_text(encoding="utf-8")
    )["ranking"]
    ranked = next(row for row in ranking if row["id"] == "ORP-0001")
    assert ranked["ranking_lane"] == "research-ready"
    assert ranked["ci_feasibility"] == "specified"
    assert (tmp_path / "pool-repo/pool/catalog.jsonl").is_file()

    call_count = len(agents.calls)
    resumed_summary = pipeline.run()
    assert resumed_summary == summary
    assert len(agents.calls) == call_count

    benchmark_summary = pipeline.triage_all_for_benchmark()
    assert benchmark_summary["candidate_count"] == 1
    assert benchmark_summary["pass_count"] == 1
    assert benchmark_summary["fail_count"] == 0
    assert len(agents.calls) == call_count
    benchmark_state = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    assert benchmark_state["status"] == "benchmark_triaged"

    candidate_id = next(iter(state["candidates"]))
    retry_summary = pipeline.retry(candidate_id, "research")
    assert retry_summary == summary
    assert agents.calls[-2:] == ["research", "reviewer"]
    retry_state = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    assert (
        retry_state["stages"][f"candidate.{candidate_id}.research.0"]["attempt"]
        == 2
    )
    assert retry_state["candidates"][candidate_id]["problem_id"] == "ORP-0001"


def test_tool_version_can_run_from_neutral_directory(tmp_path: Path) -> None:
    rendered = _tool_version(
        [
            sys.executable,
            "-c",
            "import os; print(os.getcwd())",
        ],
        cwd=tmp_path,
    )
    assert rendered == str(tmp_path)


def test_campaign_config_paths_are_resolved_relative_to_config(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "relative-paths",
        "domains": [
            {
                "id": "mathematics",
                "query": "Find one paper.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 1,
            "revision_rounds": 0,
            "lkm_timeout_seconds": 30,
        },
        "agents": {
            "model": "",
            "codex_executable": "codex",
            "sandbox": "read-only",
            "timeout_seconds": 3600,
        },
        "outputs": {
            "runs_root": "runs",
            "problem_root": "problems",
            "pool_root": "",
        },
    }
    config_path = tmp_path / "relative.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="relative",
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
    )
    stored = yaml.safe_load(
        (pipeline.run_dir / "campaign.yaml").read_text(encoding="utf-8")
    )
    assert stored["outputs"]["runs_root"] == str((tmp_path / "runs").resolve())
    assert stored["outputs"]["problem_root"] == str(
        (tmp_path / "problems").resolve()
    )


def test_campaign_does_not_treat_total_lkm_failure_as_zero_questions(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "failed-lkm",
        "domains": [
            {
                "id": "mathematics",
                "query": "Find one paper.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 1,
            "revision_rounds": 0,
            "lkm_timeout_seconds": 30,
        },
        "agents": {
            "model": "",
            "codex_executable": "codex",
            "sandbox": "read-only",
            "timeout_seconds": 3600,
        },
        "outputs": {
            "runs_root": str(tmp_path / "runs"),
            "problem_root": str(tmp_path / "problems"),
            "pool_root": "",
        },
    }
    config_path = tmp_path / "failed.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    def failing_collector(**_: Any) -> dict[str, Any]:
        raise RuntimeError("transport unavailable")

    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="failed",
        agent_runner=FakeAgentRunner(),
        paper_collector=failing_collector,
    )
    with pytest.raises(CampaignError, match="all direct LKM"):
        pipeline.run()
    state = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    assert state["status"] == "failed"


def test_ingest_retries_paper_id_then_doi_then_title(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "identifier-fallback",
        "domains": [
            {
                "id": "mathematics",
                "query": "Find one paper.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 1,
            "revision_rounds": 0,
            "lkm_timeout_seconds": 30,
        },
        "agents": {
            "model": "",
            "codex_executable": "codex",
            "sandbox": "read-only",
            "timeout_seconds": 3600,
        },
        "outputs": {
            "runs_root": str(tmp_path / "runs"),
            "problem_root": str(tmp_path / "problems"),
            "pool_root": "",
        },
    }
    config_path = tmp_path / "fallback.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    calls: list[dict[str, str]] = []

    def fallback_collector(
        *,
        paper_id: str | None = None,
        doi: str | None = None,
        title: str | None = None,
        raw_out: Path,
        out: Path,
        timeout: float,
    ) -> dict[str, Any]:
        identifier = {
            key: value
            for key, value in {
                "paper_id": paper_id,
                "doi": doi,
                "title": title,
            }.items()
            if value
        }
        calls.append(identifier)
        if paper_id:
            dump_json(
                raw_out,
                {"code": 290011, "msg": "paper not found", "data": {"papers": []}},
            )
            raise RuntimeError("paper ID lookup failed")
        assert doi == "10.0000/example"
        payload = {
            "code": 0,
            "trace_id": "trace-doi",
            "data": {
                "papers": [
                    {
                        "paper": {
                            "id": "resolved-paper",
                            "en_title": "Resolved by DOI",
                            "doi": doi,
                        },
                        "open_questions": [
                            {
                                "content": "Is the exact bound attainable?",
                                "id": "resolved-paper::open_question",
                                "global_id": "GQ-DOI",
                            }
                        ],
                    }
                ]
            },
        }
        dump_json(raw_out, payload)
        result = {
            "trace_id": "trace-doi",
            "count": 1,
            "open_questions": extract_paper_open_questions(payload),
        }
        dump_json(out, result)
        return result

    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="fallback",
        agent_runner=FakeAgentRunner(),
        paper_collector=fallback_collector,
    )
    questions = pipeline._ingest(
        {
            "mathematics": {
                "domain_id": "mathematics",
                "papers": [
                    {
                        "paper_id": "stale-paper-id",
                        "doi": "10.0000/example",
                        "title": "Resolved by DOI",
                    }
                ],
                "search_summary": "Known paper with multiple handles.",
            }
        }
    )
    assert calls == [
        {"paper_id": "stale-paper-id"},
        {"doi": "10.0000/example"},
    ]
    assert [item["global_id"] for item in questions] == ["GQ-DOI"]
    extraction = json.loads(
        (
            pipeline.run_dir
            / "domains/mathematics/source-open-questions.json"
        ).read_text(encoding="utf-8")
    )
    assert extraction["papers"][0]["identifier"] == {
        "doi": "10.0000/example"
    }
    assert len(extraction["papers"][0]["identifier_attempts"]) == 2
