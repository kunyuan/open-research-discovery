from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from open_research_discovery.agent import AgentRun
from open_research_discovery.benchmark import (
    _cluster_candidate_ids as benchmark_candidate_ids,
)
from open_research_discovery.campaign import (
    CampaignError,
    CampaignPipeline,
    _candidate_id,
    _tool_version,
)
from open_research_discovery.common import dump_json
from open_research_discovery.lkm import extract_paper_open_questions


class FakeAgentRunner:
    def __init__(self, review_verdict: str = "accept") -> None:
        self.calls: list[str] = []
        self.review_verdict = review_verdict

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
                        "source_support": [
                            {
                                "source_key": "global_id:GQ-1",
                                "exact_excerpt": (
                                    "Does there exist a finite object satisfying A "
                                    "and B while violating C?"
                                ),
                            }
                        ],
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
                assert "Lean/Coq/Isabelle" in prompt
                assert "without reviewing the solver's reasoning process" in prompt
                output = {
                    "candidate_id": candidate,
                    "importance_level": "high",
                    "importance_rationale": "A counterexample changes a standard bound.",
                    "expected_result": "A finite machine-readable witness.",
                    "solution_review_scope": "result-only",
                    "solution_review_rationale": (
                        "The witness refutes the bound, and every condition can "
                        "be recomputed from the result."
                    ),
                    "ci_status": "pseudocode",
                    "ci_pseudocode": [
                        "candidate = parse_submission()",
                        "assert assumptions(candidate)",
                        "assert violates_bound(candidate)",
                    ],
                    "estimated_ci_runtime": "under 2 minutes",
                    "ci_timeout_minutes": 5,
                }
            elif role == "research":
                assert 'literal recent sentence saying "remains open"' in prompt
                assert "without reviewing the solver's reasoning process" in prompt
                assert "Preserve the Triage expected-result" in prompt
                output = assessment(candidate)
            elif role == "problem-reviewer":
                assert 'literal recent "remains open" sentence' in prompt
                assert "without reviewing the solver's reasoning process" in prompt
                assert "Reject any upgrade to result-only" in prompt
                revise = self.review_verdict == "revise"
                output = {
                    "candidate_id": candidate,
                    "verdict": self.review_verdict,
                    "checks": {
                        "status_supported": not revise,
                        "major_progress_supported": True,
                        "surviving_core_precise": True,
                        "importance_supported": True,
                        "solution_review_contract_bounded": True,
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
                        else "The evidence and contracts are sufficient."
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
        "expected_result": "A JSON object containing the finite witness.",
        "solution_review_scope": "result-only",
        "solution_review_rationale": (
            "The claim is decided by one finite object."
        ),
        "solution_review_checklist": [
            "Parse the submitted object.",
            "Check assumptions A and B.",
            "Recompute and confirm the strict violation of C.",
        ],
        "estimated_solution_review_time": "20 minutes",
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
    prepare_summary = pipeline.prepare_benchmark()
    assert prepare_summary == {
        "schema_version": 2,
        "source_open_questions": 1,
        "atomic_candidates": 1,
        "prescreened_candidates": 1,
        "candidate_count": 1,
        "pass_count": 1,
        "fail_count": 0,
    }
    assert agents.calls == ["discovery", "canonicalization", "triage"]

    summary = pipeline.run()
    assert summary["source_open_questions"] == 1
    assert summary["canonical_candidates"] == 1
    assert summary["accepted_problem_ids"] == ["ORP-0001"]
    assert agents.calls == [
        "discovery",
        "canonicalization",
        "triage",
        "research",
        "problem-reviewer",
    ]

    repo_paths = list((tmp_path / "problems").glob("ORP-0001-*"))
    assert len(repo_paths) == 1
    assert sorted(path.name for path in repo_paths[0].iterdir()) == ["README.md"]
    readme = (repo_paths[0] / "README.md").read_text(encoding="utf-8")
    assert "## 问题是什么" in readme
    assert "## Review Scope" in readme
    assert "## LKM 与引用文献" in readme
    assert "A JSON object containing the finite witness." in readme

    problem_paths = list(pipeline.run_dir.glob("candidates/*/problem.yaml"))
    assert len(problem_paths) == 1
    problem = yaml.safe_load(problem_paths[0].read_text(encoding="utf-8"))
    assert problem["status"] == "ready"
    assert problem["research_triage"]["route"] == "candidate-result"
    assert problem["resolution_audit"]["coverage"] == "systematic_literature"
    assert problem["resolution_audit"]["checked_at"] == "2026-07-26"
    assert problem["resolution_audit"]["checked_through"] == "2026-07-26"
    assert problem["resolution_audit"]["surviving_open_core"].endswith(
        "greater than ten."
    )
    assert problem["ci_contract"]["status"] == "pseudocode"
    assert problem["discovery_contract"] == {
        "expected_result": "A JSON object containing the finite witness."
    }
    assert problem["solution_review_contract"]["rationale"].startswith(
        "The claim is decided"
    )
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

    pool_root = tmp_path / "pool-repo/pool"
    catalog_path = pool_root / "catalog.jsonl"
    current_record = json.loads(
        catalog_path.read_text(encoding="utf-8").splitlines()[0]
    )
    legacy_record = {
        **current_record,
        "id": "OMP-0001",
        "local_repo": "OMP-0001-legacy",
        "snapshot": "problems/OMP-0001.yaml",
        "route": "candidate-machine",
    }
    catalog_path.write_text(
        "\n".join(
            json.dumps(record, sort_keys=True)
            for record in (legacy_record, current_record)
        )
        + "\n",
        encoding="utf-8",
    )
    legacy_snapshot = pool_root / "problems/OMP-0001.yaml"
    legacy_snapshot.write_text(
        "id: OMP-0001\nlegacy_only_field: true\n", encoding="utf-8"
    )

    candidate_id = next(iter(state["candidates"]))
    retry_summary = pipeline.retry(candidate_id, "research")
    assert retry_summary == {
        **summary,
        "ranked_problem_count": 2,
    }
    assert agents.calls[-2:] == ["research", "problem-reviewer"]
    assert legacy_snapshot.is_file()
    catalog_ids = {
        json.loads(line)["id"]
        for line in catalog_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert catalog_ids == {"OMP-0001", "ORP-0001"}
    retry_state = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    assert (
        retry_state["stages"][f"candidate.{candidate_id}.research"]["attempt"]
        == 2
    )
    assert retry_state["candidates"][candidate_id]["problem_id"] == "ORP-0001"

    retry_state["stages"][f"candidate.{candidate_id}.triage"]["status"] = (
        "running"
    )
    dump_json(pipeline.run_dir / "state.json", retry_state)
    pipeline.state = retry_state
    pipeline.ledger.state = retry_state
    calls_before_stale_triage = len(agents.calls)
    pipeline.triage_all_for_benchmark()
    assert len(agents.calls) == calls_before_stale_triage + 1
    assert agents.calls[-1] == "triage"

    recovered_state = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    recovered_state["stages"][
        f"candidate.{candidate_id}.triage"
    ]["status"] = "running"
    dump_json(pipeline.run_dir / "state.json", recovered_state)
    recovered = CampaignPipeline.resume(
        pipeline.run_dir,
        repository_root=repository_root,
        agent_runner=agents,
        paper_collector=fake_collector,
    )
    assert recovered.state["status"] == "interrupted"
    assert (
        recovered.state["stages"][
            f"candidate.{candidate_id}.triage"
        ]["status"]
        == "interrupted"
    )


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


def test_revise_writes_report_and_stops_without_research_loop(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "single-review",
        "domains": [
            {
                "id": "mathematics",
                "query": "Find one finite target.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 1,
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
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    agents = FakeAgentRunner(review_verdict="revise")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="single-review",
        agent_runner=agents,
        paper_collector=fake_collector,
    )

    summary = pipeline.run()

    assert summary["accepted_problem_ids"] == []
    assert agents.calls == [
        "discovery",
        "canonicalization",
        "triage",
        "research",
        "problem-reviewer",
    ]
    state = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    candidate_id = next(iter(state["candidates"]))
    assert state["candidates"][candidate_id]["status"] == "needs_revision"
    report = json.loads(
        (
            pipeline.run_dir
            / "candidates"
            / candidate_id
            / "problem-review-verdict.json"
        ).read_text(encoding="utf-8")
    )
    assert report["verdict"] == "revise"
    assert report["revision_instructions"] == [
        "State the missing hypothesis in the surviving core."
    ]
    assert not list(
        (pipeline.run_dir / "candidates" / candidate_id).glob("assessment-r*.json")
    )


def test_benchmark_triage_uses_bounded_parallel_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "parallel-triage",
        "domains": [
            {
                "id": "mathematics",
                "query": "Find finite targets.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 3,
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
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    barrier = threading.Barrier(3)
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    class ParallelRunner:
        def run(
            self,
            *,
            role: str,
            prompt: str,
            schema_path: Path,
            output_path: Path,
            events_path: Path,
        ) -> AgentRun:
            del schema_path, output_path, events_path
            assert role == "triage"
            match = re.search(r"CAN-[A-F0-9]{12}", prompt)
            assert match is not None
            candidate_id = match.group(0)
            nonlocal active, max_active
            with counter_lock:
                active += 1
                max_active = max(max_active, active)
            barrier.wait(timeout=5)
            with counter_lock:
                active -= 1
            return AgentRun(
                output={
                    "candidate_id": candidate_id,
                    "importance_level": "medium",
                    "importance_rationale": "Concrete consequence.",
                    "expected_result": "A JSON witness.",
                    "solution_review_scope": "result-only",
                    "solution_review_rationale": (
                        "The JSON witness answers the finite target and is "
                        "directly recomputable."
                    ),
                    "ci_status": "pseudocode",
                    "ci_pseudocode": ["assert verify(candidate)"],
                    "estimated_ci_runtime": "under one minute",
                    "ci_timeout_minutes": 5,
                },
                metadata={"exit_code": 0, "role": role},
            )

    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="parallel-triage",
        agent_runner=ParallelRunner(),
        paper_collector=fake_collector,
    )
    candidates = [
        {
            "candidate_id": f"CAN-{index:012X}",
            "domain": "mathematics",
            "canonical_title": f"Candidate {index}",
            "source_support": [
                {
                    "source_key": f"source:CAN-{index:012X}",
                    "exact_excerpt": "Find one checked finite witness.",
                }
            ],
        }
        for index in range(1, 4)
    ]
    dump_json(
        pipeline.run_dir / "source-open-questions.json",
        {"schema_version": 1, "open_questions": []},
    )
    dump_json(
        pipeline.run_dir / "canonicalization.json",
        {"schema_version": 1, "clusters": []},
    )
    for candidate in candidates:
        pipeline.state["candidates"][candidate["candidate_id"]] = {
            "status": "canonicalized"
        }
    monkeypatch.setattr(
        pipeline,
        "_materialize_candidates",
        lambda output, questions: candidates,
    )

    summary = pipeline.triage_all_for_benchmark(workers=3)

    assert summary["candidate_count"] == 3
    assert max_active == 3
    saved = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    assert all(
        saved["stages"][f"candidate.{candidate['candidate_id']}.triage"][
            "status"
        ]
        == "completed"
        for candidate in candidates
    )


def test_materialize_can_split_one_source_into_atomic_candidates(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "atomic-split",
        "domains": [
            {
                "id": "mathematics",
                "query": "Find atomic questions.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 2,
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
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="atomic-split",
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
    )
    source_key = "global_id:GQ-SPLIT"
    questions = [
        {
            "source_key": source_key,
            "content": "First, determine exact value A. Second, construct object B.",
            "paper_id": "PAPER-SPLIT",
            "paper_doi": "10.0000/split",
            "paper_title": "Two explicit open questions",
        }
    ]
    output = {
        "clusters": [
            {
                "canonical_title": "Determine exact value A",
                "canonical_statement": "Determine the exact value of A.",
                "domain": "mathematics",
                "source_keys": [source_key],
                "source_support": [
                    {
                        "source_key": source_key,
                        "exact_excerpt": "determine exact value A",
                    }
                ],
                "aliases": [],
                "rationale": "The source states this target explicitly.",
            },
            {
                "canonical_title": "Construct object B",
                "canonical_statement": "Construct an object satisfying B.",
                "domain": "mathematics",
                "source_keys": [source_key],
                "source_support": [
                    {
                        "source_key": source_key,
                        "exact_excerpt": "construct object B",
                    }
                ],
                "aliases": [],
                "rationale": "The source states this target explicitly.",
            },
        ]
    }
    candidates = pipeline._materialize_candidates(output, questions)
    assert len(candidates) == 2
    assert len(pipeline.state["active_candidate_ids"]) == 2

    duplicate_output = {
        "clusters": [
            json.loads(json.dumps(output["clusters"][0])),
            json.loads(json.dumps(output["clusters"][0])),
        ]
    }
    with pytest.raises(CampaignError, match="duplicate candidate_id"):
        pipeline._materialize_candidates(duplicate_output, questions)

    output["clusters"][0]["source_support"][0][
        "exact_excerpt"
    ] = "invented sharper conjecture"
    with pytest.raises(CampaignError, match="exact substring"):
        pipeline._materialize_candidates(output, questions)


def test_candidate_id_collision_fallback_preserves_mathematical_case(
    tmp_path: Path,
) -> None:
    upper = {
        "canonical_title": "Upper-case functions",
        "canonical_statement": "Is F_k ≤ c H_k?",
        "domain": "mathematics",
        "source_keys": ["global_id:GQ-CASE"],
        "source_support": [
            {
                "source_key": "global_id:GQ-CASE",
                "exact_excerpt": "F_k and f_k",
            }
        ],
        "aliases": [],
        "rationale": "The source distinguishes upper-case functions.",
    }
    lower = {
        "canonical_title": "Lower-case functions",
        "canonical_statement": "Is f_k ≤ c h_k?",
        "domain": "mathematics",
        "source_keys": ["global_id:GQ-CASE"],
        "source_support": [
            {
                "source_key": "global_id:GQ-CASE",
                "exact_excerpt": "F_k and f_k",
            }
        ],
        "aliases": [],
        "rationale": "The source distinguishes lower-case functions.",
    }
    assert _candidate_id(upper) == _candidate_id(lower)

    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "candidate-id-collision",
        "domains": [
            {
                "id": "mathematics",
                "query": "Find mathematics questions.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 1,
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
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="candidate-id-collision",
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
    )
    questions = [
        {
            "source_key": "global_id:GQ-CASE",
            "content": "Compare F_k and f_k, and H_k and h_k.",
            "paper_id": "PAPER-CASE",
            "paper_doi": "",
            "paper_title": "Case-sensitive functions",
        }
    ]
    candidates = pipeline._materialize_candidates(
        {"clusters": [upper, lower]}, questions
    )

    assert len({candidate["candidate_id"] for candidate in candidates}) == 2
    assert benchmark_candidate_ids([upper, lower]) == {
        candidate["candidate_id"] for candidate in candidates
    }


def test_invalid_canonicalization_is_retried_by_stage_ledger(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "canonicalization-retry",
        "domains": [
            {
                "id": "mathematics",
                "query": "Find mathematics questions.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 1,
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
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    class InvalidThenValidRunner(FakeAgentRunner):
        def __init__(self) -> None:
            super().__init__()
            self.canonicalization_attempts = 0

        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "canonicalization":
                self.canonicalization_attempts += 1
                if self.canonicalization_attempts == 1:
                    result.output["clusters"][0]["source_support"][0][
                        "exact_excerpt"
                    ] = "invented non-exact excerpt"
                    dump_json(kwargs["output_path"], result.output)
            return result

    runner = InvalidThenValidRunner()
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="canonicalization-retry",
        agent_runner=runner,
        paper_collector=fake_collector,
    )
    questions = [
        {
            "source_key": "global_id:GQ-1",
            "content": (
                "Does there exist a finite object satisfying A and B while "
                "violating C?"
            ),
            "paper_id": "PAPER-1",
            "paper_doi": "",
            "paper_title": "Finite witness question",
        }
    ]

    with pytest.raises(CampaignError, match="exact substring"):
        pipeline._canonicalize(questions)
    assert pipeline.state["stages"]["campaign.canonicalization"][
        "status"
    ] == "failed"

    candidates = pipeline._canonicalize(questions)

    assert len(candidates) == 1
    assert runner.canonicalization_attempts == 2
    assert pipeline.state["stages"]["campaign.canonicalization"][
        "attempt"
    ] == 2
    assert pipeline.state["stages"]["campaign.canonicalization"][
        "status"
    ] == "completed"


def test_prescreen_limit_uses_campaign_domain_not_semantic_subdomain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "campaign-domain-prescreen",
        "domains": [
            {
                "id": "physics",
                "query": "Find physics questions.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 2,
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
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="campaign-domain-prescreen",
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
    )
    candidates = [
        {
            "candidate_id": f"CAN-{index:012X}",
            "domain": semantic_domain,
            "canonical_title": f"Candidate {index}",
            "canonical_statement": f"Determine candidate {index}.",
            "aliases": [],
            "source_support": [
                {
                    "source_key": f"source-{index}",
                    "exact_excerpt": f"Determine candidate {index}.",
                }
            ],
            "source_open_questions": [
                {
                    "source_key": f"source-{index}",
                    "domain_id": "physics",
                    "domain_ids": ["physics"],
                    "paper_id": f"paper-{index}",
                    "paper_title": f"Paper {index}",
                    "paper_doi": "",
                }
            ],
        }
        for index, semantic_domain in enumerate(
            [
                "quantum-information",
                "quantum-many-body",
                "quantum-dynamics",
            ],
            start=1,
        )
    ]
    agent_calls = 0

    def fake_agent(**kwargs: Any) -> dict[str, Any]:
        nonlocal agent_calls
        agent_calls += 1
        inputs = kwargs["inputs"]
        output = {
            "domain_id": inputs["domain_id"],
            "selected": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "rationale": "Select one candidate for the configured domain.",
                }
                for candidate in inputs["candidates"][: inputs["limit"]]
            ],
            "rationale": "One candidate selected.",
        }
        kwargs["output_validator"](output)
        dump_json(kwargs["output_path"], output)
        return output

    monkeypatch.setattr(pipeline, "_agent", fake_agent)
    selected = pipeline._prescreen_candidates(candidates, per_domain=1)

    assert len(selected) == 1
    prescreen = json.loads(
        (pipeline.run_dir / "prescreen.json").read_text(encoding="utf-8")
    )
    assert prescreen["selected_count"] == 1
    assert [item["domain_id"] for item in prescreen["domains"]] == ["physics"]

    domain_output_path = (
        pipeline.run_dir / "domains" / "physics" / "prescreen.json"
    )
    invalid_cached = json.loads(domain_output_path.read_text(encoding="utf-8"))
    invalid_cached["selected"][0]["candidate_id"] = "CAN-FFFFFFFFFFFF"
    dump_json(domain_output_path, invalid_cached)

    retried = pipeline._prescreen_candidates(candidates, per_domain=1)

    assert len(retried) == 1
    assert agent_calls == 2

    expanded = pipeline._prescreen_candidates(candidates, per_domain=2)

    assert len(expanded) == 2
    assert agent_calls == 3
    prescreen = json.loads(
        (pipeline.run_dir / "prescreen.json").read_text(encoding="utf-8")
    )
    assert prescreen["selected_count"] == 2


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
