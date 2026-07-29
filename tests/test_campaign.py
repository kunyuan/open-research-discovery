from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from open_research_discovery.agent import AgentRun, file_sha256
from open_research_discovery.benchmark import (
    _cluster_candidate_ids as benchmark_candidate_ids,
)
from open_research_discovery.campaign import (
    CampaignError,
    CampaignPipeline,
    _candidate_id,
    _tool_version,
)
from open_research_discovery.common import (
    dump_json,
    problem_repo_paths,
    slugify,
)
from open_research_discovery.lkm import extract_paper_open_questions


class FakeAgentRunner:
    def __init__(self, review_verdict: str = "accept") -> None:
        self.calls: list[str] = []
        self.prompts: list[tuple[str, str]] = []
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
        self.prompts.append((role, prompt))
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
                assert "Do not require machine CI for 0" in prompt
                output = {
                    "candidate_id": candidate,
                    "importance_level": "high",
                    "importance_rationale": "A counterexample changes a standard bound.",
                    "expected_result": "A finite machine-readable witness.",
                    "verification_difficulty": 0,
                    "verification_difficulty_rationale": (
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
                assert "regardless of whether that check is automated or human" in prompt
                assert "Preserve the Triage expected-result" in prompt
                output = assessment(candidate)
            elif role == "problem-reviewer":
                assert 'literal recent "remains open" sentence' in prompt
                assert "Score 0 means every load-bearing claim is discharged" in prompt
                assert "Reject an unexplained score decrease" in prompt
                revise = self.review_verdict == "revise"
                output = {
                    "candidate_id": candidate,
                    "verdict": self.review_verdict,
                    "checks": {
                        "status_supported": not revise,
                        "major_progress_supported": True,
                        "surviving_core_precise": True,
                        "importance_supported": True,
                        "verification_difficulty_supported": True,
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


class MutatedResearchAgentRunner(FakeAgentRunner):
    """Applies a mutation to the Research Agent's structured output."""

    def __init__(
        self, mutate: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        super().__init__()
        self._mutate = mutate

    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        if kwargs["role"] != "research":
            return result
        output = {**result.output, **self._mutate(result.output)}
        dump_json(kwargs["output_path"], output)
        return AgentRun(output=output, metadata=result.metadata)


class SequencedReviewAgentRunner(FakeAgentRunner):
    def __init__(self) -> None:
        super().__init__()
        self.review_rounds = [
            {
                "verdict": "revise",
                "concerns": ["Round one concern.", "Shared concern."],
                "revision_instructions": ["Round one instruction."],
                "rationale": "The first revision round found two issues.",
            },
            {
                "verdict": "revise",
                "concerns": ["Shared concern.", "Round two concern."],
                "revision_instructions": [
                    "Round one instruction.",
                    "Round two instruction.",
                ],
                "rationale": "The second revision round retained and added issues.",
            },
            {
                "verdict": "accept",
                "concerns": [],
                "revision_instructions": [],
                "rationale": "Both revision rounds were addressed.",
            },
        ]

    def run(self, **kwargs: Any) -> AgentRun:
        role = kwargs["role"]
        if role != "problem-reviewer":
            return super().run(**kwargs)

        review_index = sum(
            previous_role == "problem-reviewer" for previous_role in self.calls
        )
        review_round = self.review_rounds[review_index]
        self.review_verdict = review_round["verdict"]
        result = super().run(**kwargs)
        output = {
            **result.output,
            "concerns": review_round["concerns"],
            "revision_instructions": review_round[
                "revision_instructions"
            ],
            "rationale": review_round["rationale"],
        }
        dump_json(kwargs["output_path"], output)
        return AgentRun(output=output, metadata=result.metadata)


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
        "verification_difficulty": 0,
        "verification_difficulty_rationale": (
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
    assert sorted(path.name for path in repo_paths[0].iterdir()) == [
        ".git",
        "README.md",
    ]
    assert (
        subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_paths[0],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        == "1"
    )
    readme = (repo_paths[0] / "README.md").read_text(encoding="utf-8")
    assert "## The Research Problem" in readme
    assert "## Verification Difficulty" in readme
    assert "## LKM and References" in readme
    assert "A JSON object containing the finite witness." in readme
    assert "The claim is decided by one finite object." in readme

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


def test_full_campaign_applies_configured_prescreen_before_triage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "bounded-full-campaign",
        "domains": [
            {
                "id": "physics",
                "query": "Find finite targets.",
                "seed_papers": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 3,
            "lkm_timeout_seconds": 30,
            "triage_candidates_per_domain": 1,
        },
        "agents": {
            "model": "",
            "codex_executable": "codex",
            "workers": 2,
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
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="bounded-full-campaign",
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
    )
    candidates = [
        {
            "candidate_id": "CAN-000000000001",
            "domain": "physics",
            "canonical_title": "Selected candidate",
        },
        {
            "candidate_id": "CAN-000000000002",
            "domain": "physics",
            "canonical_title": "Unselected candidate",
        },
    ]
    for candidate in candidates:
        pipeline.state["candidates"][candidate["candidate_id"]] = {
            "status": "canonicalized"
        }
    triaged_ids: list[str] = []

    def fake_prescreen(
        candidate_list: list[dict[str, Any]], *, per_domain: int | None
    ) -> list[dict[str, Any]]:
        assert candidate_list == candidates
        assert per_domain == 1
        return candidate_list[:1]

    def fake_triage(
        candidate_list: list[dict[str, Any]], *, workers: int
    ) -> dict[str, dict[str, Any]]:
        assert workers == 2
        triaged_ids.extend(
            candidate["candidate_id"] for candidate in candidate_list
        )
        candidate_id = candidate_list[0]["candidate_id"]
        return {
            candidate_id: {
                "candidate_id": candidate_id,
                "importance_level": "low",
                "importance_rationale": "Too narrow for the campaign.",
                "expected_result": "A finite witness.",
                "verification_difficulty": 0,
                "verification_difficulty_rationale": "The witness is directly checked.",
                "ci_status": "pseudocode",
                "ci_pseudocode": ["assert verify(submission)"],
                "estimated_ci_runtime": "under one minute",
                "ci_timeout_minutes": 5,
            }
        }

    monkeypatch.setattr(pipeline, "_discover", lambda: {})
    monkeypatch.setattr(pipeline, "_ingest", lambda discovered: [])
    monkeypatch.setattr(pipeline, "_canonicalize", lambda questions: candidates)
    monkeypatch.setattr(pipeline, "_prescreen_candidates", fake_prescreen)
    monkeypatch.setattr(pipeline, "_triage_candidates", fake_triage)
    monkeypatch.setattr(pipeline, "_write_triage_deferred", lambda items: None)
    monkeypatch.setattr(pipeline, "_sync_and_rank", lambda accepted: [])

    summary = pipeline.run()

    assert triaged_ids == ["CAN-000000000001"]
    assert summary["canonical_candidates"] == 2
    assert summary["triage_deferred_count"] == 1


def test_research_gate_excludes_resolved_or_over_limit_assessments() -> None:
    pipeline = object.__new__(CampaignPipeline)
    pipeline.config = {"limits": {"max_verification_difficulty": 3}}
    assessment = {
        "resolution_status": "still_open",
        "resolution_conclusion": "likely_open",
        "post_progress_decision": "continue",
        "importance_level": "high",
        "verification_difficulty": 0,
        "surviving_open_core": "Find a finite counterexample.",
        "checked_through": "2026-07-26",
        "major_progress_found": False,
        "importance_motivation": "The bound is used by later constructions.",
        "consequences_of_progress": "A witness invalidates the bound.",
        "current_best_result": "The bound holds for size at most ten.",
        "evidence": [{"source": "lkm", "relation": "continuing_open"}],
    }
    assert pipeline._passes_research_gate(assessment)
    assert pipeline._passes_research_gate(
        {**assessment, "post_progress_decision": "rewrite-core"}
    )
    assert pipeline._passes_research_gate(
        {**assessment, "post_progress_decision": "new-derived-problem"}
    )
    assert pipeline._passes_research_gate(
        {
            **assessment,
            "resolution_status": "partially_resolved",
            "major_progress_found": True,
        }
    )

    for field, value in (
        ("resolution_status", "resolved"),
        ("resolution_conclusion", "resolved"),
        ("post_progress_decision", "stop"),
        ("importance_level", "low"),
        ("verification_difficulty", 4),
        ("surviving_open_core", ""),
        ("checked_through", ""),
        ("evidence", []),
        ("importance_motivation", "  "),
        ("consequences_of_progress", ""),
        ("current_best_result", ""),
    ):
        assert not pipeline._passes_research_gate(
            {**assessment, field: value}
        )


def test_research_gate_requires_major_progress_for_partial_resolution() -> None:
    pipeline = object.__new__(CampaignPipeline)
    pipeline.config = {"limits": {"max_verification_difficulty": 3}}
    assessment = {
        "resolution_status": "partially_resolved",
        "resolution_conclusion": "likely_open",
        "post_progress_decision": "rewrite-core",
        "importance_level": "high",
        "verification_difficulty": 0,
        "surviving_open_core": "Find a witness of size greater than ten.",
        "checked_through": "2026-07-26",
        "importance_motivation": "The bound is used by later constructions.",
        "consequences_of_progress": "A witness invalidates the bound.",
        "current_best_result": "The bound holds for size at most ten.",
        "evidence": [{"source": "lkm", "relation": "special_case"}],
    }
    assert not pipeline._passes_research_gate(
        {**assessment, "major_progress_found": False}
    )
    assert pipeline._passes_research_gate(
        {**assessment, "major_progress_found": True}
    )


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda assessment: {"evidence": []}, id="empty-evidence"),
        pytest.param(
            lambda assessment: {"checked_through": ""},
            id="empty-checked-through",
        ),
        pytest.param(
            lambda assessment: {
                "resolution_status": "partially_resolved",
                "major_progress_found": False,
            },
            id="partial-without-major-progress",
        ),
    ],
)
def test_incomplete_assessment_audits_out_instead_of_compiling(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "gated-out-campaign",
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
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="gated-out",
        agent_runner=MutatedResearchAgentRunner(mutation),
        paper_collector=fake_collector,
    )

    summary = pipeline.run()

    assert summary["accepted_problem_ids"] == []
    statuses = {
        candidate["status"]
        for candidate in pipeline.state["candidates"].values()
    }
    assert statuses == {"audited_out"}
    assert pipeline.state["status"] == "completed"
    problems_root = tmp_path / "problems"
    reserved = (
        list(problems_root.glob("ORP-*")) if problems_root.is_dir() else []
    )
    assert reserved == []


def test_verification_gate_uses_configured_numeric_threshold() -> None:
    pipeline = object.__new__(CampaignPipeline)
    triage = {
        "importance_level": "high",
        "verification_difficulty": 1,
    }

    pipeline.config = {"limits": {"max_verification_difficulty": 0}}
    assert not pipeline._passes_gate(triage)

    pipeline.config = {"limits": {"max_verification_difficulty": 1}}
    assert pipeline._passes_gate(triage)


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
    research_key = f"candidate.{candidate_id}.research"
    review_key = f"candidate.{candidate_id}.problem-review"
    calls_after_first_run = list(agents.calls)

    pipeline.run()

    assert agents.calls == calls_after_first_run
    assert pipeline.state["stages"][research_key]["attempt"] == 1
    assert pipeline.state["stages"][review_key]["attempt"] == 1

    pipeline.retry(candidate_id, "problem-review")

    assert agents.calls == calls_after_first_run + ["problem-reviewer"]
    assert pipeline.state["stages"][research_key]["attempt"] == 1
    assert pipeline.state["stages"][review_key]["attempt"] == 2
    applied_path = (
        pipeline.run_dir
        / "candidates"
        / candidate_id
        / "research-feedback-applied.json"
    )
    applied = json.loads(applied_path.read_text(encoding="utf-8"))
    assert applied["feedback_sources"] == []
    history = json.loads(
        (
            pipeline.run_dir
            / "candidates"
            / candidate_id
            / "problem-review-feedback-history.json"
        ).read_text(encoding="utf-8")
    )
    assert [
        revision["problem_review_attempt"]
        for revision in history["revisions"]
    ] == [1]
    calls_before_triage_retry = list(agents.calls)

    pipeline.retry(candidate_id, "triage")

    assert agents.calls == calls_before_triage_retry + [
        "triage",
        "research",
        "problem-reviewer",
    ]
    assert pipeline.state["stages"][research_key]["attempt"] == 2
    assert pipeline.state["stages"][review_key]["attempt"] == 3
    research_prompts = [
        prompt for role, prompt in agents.prompts if role == "research"
    ]
    assert "Clarify why the 2025 result is only a special case." in (
        research_prompts[-1]
    )
    applied = json.loads(applied_path.read_text(encoding="utf-8"))
    assert len(applied["feedback_sources"]) == 1

    calls_before_legacy_resume = list(agents.calls)
    applied_path.unlink()
    for stage_key in (research_key, review_key):
        pipeline.state["stages"][stage_key]["pipeline_version"] = 7
        pipeline.state["stages"][stage_key]["input_sha256"] = "legacy-input"
    pipeline.state["candidates"][candidate_id].pop(
        "research_feedback_sha256"
    )
    pipeline.ledger.save()

    pipeline.run()

    assert agents.calls == calls_before_legacy_resume + [
        "research",
        "problem-reviewer",
    ]
    assert pipeline.state["stages"][research_key]["attempt"] == 3
    assert pipeline.state["stages"][review_key]["attempt"] == 4
    research_prompts = [
        prompt for role, prompt in agents.prompts if role == "research"
    ]
    assert "Clarify why the 2025 result is only a special case." in (
        research_prompts[-1]
    )
    applied = json.loads(applied_path.read_text(encoding="utf-8"))
    assert len(applied["feedback_sources"]) == 1

    history_path = (
        pipeline.run_dir
        / "candidates"
        / candidate_id
        / "problem-review-feedback-history.json"
    )
    history_before_failed_attempt = history_path.read_bytes()
    pipeline.state["stages"][review_key]["status"] = "failed"
    pipeline.state["stages"][review_key]["attempt"] = 5
    pipeline.ledger.save()

    recovered = pipeline._recover_problem_review_feedback(
        candidate_id,
        pipeline.run_dir / "candidates" / candidate_id,
    )

    assert history_path.read_bytes() == history_before_failed_attempt
    assert [
        revision["problem_review_attempt"]
        for revision in recovered["revisions"]
    ] == [1]


def test_research_retry_accumulates_all_prior_reviewer_feedback(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "review-feedback-history",
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
    agents = SequencedReviewAgentRunner()
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="review-feedback-history",
        agent_runner=agents,
        paper_collector=fake_collector,
    )

    first_summary = pipeline.run()
    assert first_summary["accepted_problem_ids"] == []
    candidate_id = next(iter(pipeline.state["candidates"]))
    research_stage_key = f"candidate.{candidate_id}.research"
    first_research_hash = pipeline.state["stages"][research_stage_key][
        "input_sha256"
    ]
    candidate_dir = pipeline.run_dir / "candidates" / candidate_id
    history_path = candidate_dir / "problem-review-feedback-history.json"
    seeded_history = json.loads(history_path.read_text(encoding="utf-8"))
    seeded_history["revisions"].insert(
        0,
        {
            "feedback_id": "problem-review-attempt-2",
            "source": "manual-seed",
            "concerns": ["Recovered concern."],
            "revision_instructions": ["Recovered instruction."],
            "rationale": "Recovered from an external audit note.",
        },
    )
    dump_json(history_path, seeded_history)

    second_summary = pipeline.retry(candidate_id, "research")
    assert second_summary["accepted_problem_ids"] == []
    second_research_hash = pipeline.state["stages"][research_stage_key][
        "input_sha256"
    ]
    calls_after_second_review = list(agents.calls)

    pipeline.run()

    assert agents.calls == calls_after_second_review
    assert pipeline.state["stages"][research_stage_key]["attempt"] == 2

    third_summary = pipeline.retry(candidate_id, "research")
    assert third_summary["accepted_problem_ids"] == ["ORP-0001"]
    third_research_hash = pipeline.state["stages"][research_stage_key][
        "input_sha256"
    ]
    assert len(
        {first_research_hash, second_research_hash, third_research_hash}
    ) == 3

    research_prompts = [
        prompt for role, prompt in agents.prompts if role == "research"
    ]
    assert len(research_prompts) == 3
    assert "Round one concern." not in research_prompts[0]
    assert "Recovered concern." in research_prompts[1]
    assert "Round one concern." in research_prompts[1]
    assert "Round two concern." not in research_prompts[1]
    assert "Recovered concern." in research_prompts[2]
    assert "Round one concern." in research_prompts[2]
    assert "Round two concern." in research_prompts[2]
    assert "Round one instruction." in research_prompts[2]
    assert "Round two instruction." in research_prompts[2]
    assert research_prompts[2].count('"Shared concern."') == 1
    assert research_prompts[2].count('"Round one instruction."') == 1

    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert [
        revision["problem_review_attempt"]
        for revision in history["revisions"]
    ] == [0, 1, 2]
    assert history["accumulated_concerns"] == [
        "Recovered concern.",
        "Round one concern.",
        "Shared concern.",
        "Round two concern.",
    ]
    assert history["accumulated_revision_instructions"] == [
        "Recovered instruction.",
        "Round one instruction.",
        "Round two instruction.",
    ]
    assert history["revisions"][0]["source"] == "manual-seed"
    assert all(
        revision["verdict_sha256"]
        for revision in history["revisions"][1:]
    )
    final_verdict = json.loads(
        (candidate_dir / "problem-review-verdict.json").read_text(
            encoding="utf-8"
        )
    )
    assert final_verdict["verdict"] == "accept"
    assert len(history["revisions"]) == 3

    research_stage = pipeline.state["stages"][research_stage_key]
    assert research_stage["attempt"] == 3
    assert research_stage["input_sha256"]
    calls_after_accept = list(agents.calls)

    pipeline.run()

    assert agents.calls == calls_after_accept
    assert pipeline.state["stages"][research_stage_key]["attempt"] == 3
    applied_path = candidate_dir / "research-feedback-applied.json"
    applied_snapshot = json.loads(
        applied_path.read_text(encoding="utf-8")
    )
    tampered_snapshot = {
        **applied_snapshot,
        "concerns": [*applied_snapshot["concerns"], "Unrecorded concern."],
    }
    dump_json(applied_path, tampered_snapshot)

    with pytest.raises(
        CampaignError,
        match="snapshot does not match recorded state",
    ):
        pipeline.run()

    assert agents.calls == calls_after_accept
    dump_json(applied_path, applied_snapshot)
    pipeline.state["stages"][research_stage_key]["pipeline_version"] = 7
    pipeline.ledger.save()
    applied_path.unlink()

    with pytest.raises(
        CampaignError,
        match="Research is missing its recorded",
    ):
        pipeline.run()

    assert agents.calls == calls_after_accept
    dump_json(applied_path, applied_snapshot)
    pipeline.state["stages"][research_stage_key]["pipeline_version"] = 8
    pipeline.state["stages"][research_stage_key]["status"] = "failed"
    pipeline.ledger.save()
    applied_path.unlink()

    with pytest.raises(
        CampaignError,
        match="Research is missing its recorded",
    ):
        pipeline.run()

    assert agents.calls == calls_after_accept


@pytest.mark.parametrize("verdict", ["accept", "reject"])
def test_non_revision_verdict_does_not_pollute_feedback_history(
    tmp_path: Path, verdict: str
) -> None:
    candidate_id = "CAN-000000000001"
    candidate_dir = tmp_path / candidate_id
    candidate_dir.mkdir()
    history_path = candidate_dir / "problem-review-feedback-history.json"
    history = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "revisions": [
            {
                "feedback_id": "manual-feedback",
                "source": "manual-seed",
                "concerns": ["Keep this concern."],
                "revision_instructions": ["Keep this instruction."],
                "rationale": "Recovered before retry.",
            }
        ],
        "accumulated_concerns": ["Keep this concern."],
        "accumulated_revision_instructions": ["Keep this instruction."],
    }
    dump_json(history_path, history)
    before = history_path.read_bytes()
    pipeline = object.__new__(CampaignPipeline)

    loaded = pipeline._record_problem_review_feedback(
        candidate_id,
        candidate_dir,
        {
            "candidate_id": candidate_id,
            "verdict": verdict,
            "concerns": ["Must not be recorded."],
            "revision_instructions": ["Must not be recorded."],
        },
    )

    assert history_path.read_bytes() == before
    assert [item["feedback_id"] for item in loaded["revisions"]] == [
        "manual-feedback"
    ]
    assert loaded["accumulated_concerns"] == ["Keep this concern."]
    assert loaded["accumulated_revision_instructions"] == [
        "Keep this instruction."
    ]


def test_feedback_history_rejects_forged_problem_review_provenance(
    tmp_path: Path,
) -> None:
    candidate_id = "CAN-000000000001"
    candidate_dir = tmp_path / candidate_id
    history_path = candidate_dir / "problem-review-feedback-history.json"
    dump_json(
        history_path,
        {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "revisions": [
                {
                    "feedback_id": "looks-manual-but-claims-review",
                    "source": "problem-review",
                    "problem_review_attempt": 999,
                    "verdict_sha256": "0" * 64,
                    "recorded_at": "",
                    "concerns": ["Forged concern."],
                    "revision_instructions": ["Forged instruction."],
                    "rationale": "",
                }
            ],
        },
    )
    pipeline = object.__new__(CampaignPipeline)

    with pytest.raises(
        CampaignError,
        match="feedback_id does not match its attempt and verdict_sha256",
    ):
        pipeline._load_problem_review_feedback(candidate_id, candidate_dir)


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
                    "verification_difficulty": 0,
                    "verification_difficulty_rationale": (
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


def test_candidate_audit_chains_run_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = object.__new__(CampaignPipeline)
    candidates = [
        {"candidate_id": f"CAN-{index:012X}"} for index in range(1, 4)
    ]
    triage_by_id = {
        candidate["candidate_id"]: {"candidate_id": candidate["candidate_id"]}
        for candidate in candidates
    }
    barrier = threading.Barrier(3)
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_audit(
        candidate: dict[str, Any], triage: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        nonlocal active, max_active
        candidate_id = candidate["candidate_id"]
        assert triage["candidate_id"] == candidate_id
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        barrier.wait(timeout=5)
        with counter_lock:
            active -= 1
        return (
            {"candidate_id": candidate_id, "verdict": "accept"},
            {"candidate_id": candidate_id},
        )

    monkeypatch.setattr(pipeline, "_research_and_problem_review", fake_audit)

    audits = pipeline._audit_candidates(
        candidates,
        triage_by_id,
        workers=3,
    )

    assert max_active == 3
    assert list(audits) == [
        candidate["candidate_id"] for candidate in candidates
    ]
    assert all(
        audits[candidate["candidate_id"]][0]["candidate_id"]
        == candidate["candidate_id"]
        for candidate in candidates
    )


def test_real_candidate_audit_chains_are_parallel_and_isolated(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "parallel-real-audit",
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
            "workers": 3,
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

    class ParallelAuditRunner(FakeAgentRunner):
        def __init__(self) -> None:
            super().__init__()
            self.barrier = threading.Barrier(3)
            self.lock = threading.Lock()
            self.active_research = 0
            self.max_active_research = 0
            self.roles_by_candidate: dict[str, list[str]] = {}

        def run(self, **kwargs: Any) -> AgentRun:
            role = kwargs["role"]
            candidate_match = re.search(
                r"CAN-[A-F0-9]{12}", kwargs["prompt"]
            )
            assert candidate_match is not None
            candidate_id = candidate_match.group(0)
            if role == "research":
                with self.lock:
                    self.active_research += 1
                    self.max_active_research = max(
                        self.max_active_research,
                        self.active_research,
                    )
                self.barrier.wait(timeout=5)
            result = super().run(**kwargs)
            with self.lock:
                self.roles_by_candidate.setdefault(candidate_id, []).append(
                    role
                )
                if role == "research":
                    self.active_research -= 1
            return result

    agents = ParallelAuditRunner()
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="parallel-real-audit",
        agent_runner=agents,
        paper_collector=fake_collector,
    )
    candidates = [
        {
            "candidate_id": f"CAN-{index:012X}",
            "canonical_title": f"Candidate {index}",
        }
        for index in range(1, 4)
    ]
    triage_by_id = {
        candidate["candidate_id"]: {
            "candidate_id": candidate["candidate_id"],
            "importance_level": "medium",
            "expected_result": "A finite witness.",
            "verification_difficulty": 0,
            "ci_status": "pseudocode",
        }
        for candidate in candidates
    }

    audits = pipeline._audit_candidates(
        candidates,
        triage_by_id,
        workers=3,
    )

    assert agents.max_active_research == 3
    assert list(audits) == [
        candidate["candidate_id"] for candidate in candidates
    ]
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        assert agents.roles_by_candidate[candidate_id] == [
            "research",
            "problem-reviewer",
        ]
        candidate_dir = pipeline.run_dir / "candidates" / candidate_id
        assert (candidate_dir / "assessment.json").is_file()
        assert (candidate_dir / "problem-review-verdict.json").is_file()
        assert (candidate_dir / "research-feedback-applied.json").is_file()
        assert not (
            candidate_dir / "problem-review-feedback-history.json"
        ).exists()
        assert (
            pipeline.state["stages"][
                f"candidate.{candidate_id}.research"
            ]["status"]
            == "completed"
        )
        assert (
            pipeline.state["stages"][
                f"candidate.{candidate_id}.problem-review"
            ]["status"]
            == "completed"
        )


def test_parallel_candidate_audit_errors_are_stably_aggregated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = object.__new__(CampaignPipeline)
    candidates = [
        {"candidate_id": candidate_id}
        for candidate_id in (
            "CAN-000000000003",
            "CAN-000000000001",
            "CAN-000000000002",
        )
    ]
    triage_by_id = {
        candidate["candidate_id"]: {"candidate_id": candidate["candidate_id"]}
        for candidate in candidates
    }

    def fake_audit(
        candidate: dict[str, Any], triage: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del triage
        candidate_id = candidate["candidate_id"]
        if candidate_id != "CAN-000000000002":
            raise RuntimeError(f"failed {candidate_id}")
        return (
            {"candidate_id": candidate_id, "verdict": "accept"},
            {"candidate_id": candidate_id},
        )

    monkeypatch.setattr(pipeline, "_research_and_problem_review", fake_audit)

    with pytest.raises(CampaignError) as caught:
        pipeline._audit_candidates(
            candidates,
            triage_by_id,
            workers=3,
        )

    assert str(caught.value) == (
        "2 parallel candidate audit worker(s) failed: "
        "CAN-000000000001: RuntimeError: failed CAN-000000000001; "
        "CAN-000000000003: RuntimeError: failed CAN-000000000003"
    )


def test_parallel_audit_completion_order_does_not_change_compile_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "parallel-audit-order",
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
            "workers": 3,
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
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="parallel-audit-order",
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
    )
    candidate_ids = [
        "CAN-000000000003",
        "CAN-000000000001",
        "CAN-000000000002",
    ]
    candidates = [
        {
            "candidate_id": candidate_id,
            "canonical_title": f"Candidate {candidate_id}",
        }
        for candidate_id in candidate_ids
    ]
    triage = {
        candidate_id: {
            "candidate_id": candidate_id,
            "importance_level": "medium",
            "expected_result": "A finite witness.",
            "verification_difficulty": 0,
            "ci_status": "pseudocode",
        }
        for candidate_id in candidate_ids
    }
    for candidate_id in candidate_ids:
        pipeline.state["candidates"][candidate_id] = {
            "status": "canonicalized"
        }
    completion_order: list[str] = []
    compile_order: list[str] = []
    barrier = threading.Barrier(3)
    release = {
        candidate_id: threading.Event() for candidate_id in candidate_ids
    }
    completed = {
        candidate_id: threading.Event() for candidate_id in candidate_ids
    }

    def fake_audit(
        candidate: dict[str, Any], candidate_triage: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        candidate_id = candidate["candidate_id"]
        assert candidate_triage["candidate_id"] == candidate_id
        barrier.wait(timeout=5)
        assert release[candidate_id].wait(timeout=5)
        completion_order.append(candidate_id)
        completed[candidate_id].set()
        return (
            {"candidate_id": candidate_id, "verdict": "accept"},
            assessment(candidate_id),
        )

    def release_in_reverse_order() -> None:
        for candidate_id in (
            "CAN-000000000003",
            "CAN-000000000002",
            "CAN-000000000001",
        ):
            release[candidate_id].set()
            assert completed[candidate_id].wait(timeout=5)

    def fake_compile(
        candidate: dict[str, Any],
        candidate_triage: dict[str, Any],
        candidate_assessment: dict[str, Any],
        verdict: dict[str, Any],
    ) -> dict[str, Any]:
        del candidate_triage, candidate_assessment, verdict
        candidate_id = candidate["candidate_id"]
        compile_order.append(candidate_id)
        problem_id = f"ORP-{len(compile_order):04d}"
        pipeline.state["candidates"][candidate_id][
            "problem_id"
        ] = problem_id
        return {"problem_id": problem_id}

    monkeypatch.setattr(pipeline, "_discover", lambda: {})
    monkeypatch.setattr(pipeline, "_ingest", lambda discovered: [])
    monkeypatch.setattr(pipeline, "_canonicalize", lambda questions: candidates)
    monkeypatch.setattr(
        pipeline,
        "_triage_candidates",
        lambda candidate_list, workers: triage,
    )
    monkeypatch.setattr(pipeline, "_research_and_problem_review", fake_audit)
    monkeypatch.setattr(pipeline, "_compile", fake_compile)
    monkeypatch.setattr(pipeline, "_write_triage_deferred", lambda items: None)
    monkeypatch.setattr(
        pipeline,
        "_sync_and_rank",
        lambda accepted: [{"id": problem_id} for problem_id in accepted],
    )
    releaser = threading.Thread(target=release_in_reverse_order)
    releaser.start()

    summary = pipeline.run()
    releaser.join(timeout=5)

    assert not releaser.is_alive()
    assert completion_order == [
        "CAN-000000000003",
        "CAN-000000000002",
        "CAN-000000000001",
    ]
    assert compile_order == candidate_ids
    assert summary["accepted_problem_ids"] == [
        "ORP-0001",
        "ORP-0002",
        "ORP-0003",
    ]


def test_parallel_audit_failure_prevents_compile_and_persists_aggregate_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "parallel-audit-failure",
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
            "workers": 3,
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
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="parallel-audit-failure",
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
    )
    candidate_ids = [
        "CAN-000000000003",
        "CAN-000000000001",
        "CAN-000000000002",
    ]
    candidates = [
        {
            "candidate_id": candidate_id,
            "canonical_title": f"Candidate {candidate_id}",
        }
        for candidate_id in candidate_ids
    ]
    triage = {
        candidate_id: {
            "candidate_id": candidate_id,
            "importance_level": "medium",
            "expected_result": "A finite witness.",
            "verification_difficulty": 0,
            "ci_status": "pseudocode",
        }
        for candidate_id in candidate_ids
    }
    for candidate_id in candidate_ids:
        pipeline.state["candidates"][candidate_id] = {
            "status": "canonicalized"
        }
    compile_calls: list[str] = []
    ranking_calls: list[list[str]] = []

    def fake_audit(
        candidate: dict[str, Any], candidate_triage: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del candidate_triage
        candidate_id = candidate["candidate_id"]
        if candidate_id != "CAN-000000000002":
            raise RuntimeError(f"failed {candidate_id}")
        return (
            {"candidate_id": candidate_id, "verdict": "accept"},
            assessment(candidate_id),
        )

    monkeypatch.setattr(pipeline, "_discover", lambda: {})
    monkeypatch.setattr(pipeline, "_ingest", lambda discovered: [])
    monkeypatch.setattr(pipeline, "_canonicalize", lambda questions: candidates)
    monkeypatch.setattr(
        pipeline,
        "_triage_candidates",
        lambda candidate_list, workers: triage,
    )
    monkeypatch.setattr(pipeline, "_research_and_problem_review", fake_audit)
    monkeypatch.setattr(
        pipeline,
        "_compile",
        lambda candidate, *args: compile_calls.append(
            candidate["candidate_id"]
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_sync_and_rank",
        lambda accepted: ranking_calls.append(accepted),
    )

    with pytest.raises(CampaignError) as caught:
        pipeline.run()

    expected = (
        "2 parallel candidate audit worker(s) failed: "
        "CAN-000000000001: RuntimeError: failed CAN-000000000001; "
        "CAN-000000000003: RuntimeError: failed CAN-000000000003"
    )
    assert str(caught.value) == expected
    assert compile_calls == []
    assert ranking_calls == []
    saved = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    assert saved["status"] == "failed"
    assert saved["error"] == f"CampaignError: {expected}"


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


def compile_campaign(tmp_path: Path, name: str) -> CampaignPipeline:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": name,
        "domains": [
            {
                "id": "mathematics",
                "query": "Find important finite-witness open questions.",
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
            "pool_root": str(tmp_path / "pool-repo"),
        },
    }
    config_path = tmp_path / f"{name}.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    return CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id=name,
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
    )


def compile_inputs(
    candidate_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = {
        "candidate_id": candidate_id,
        "canonical_title": "Finite witness for the example bound",
        "canonical_statement": (
            "Does there exist a finite object satisfying assumptions "
            "A and B while violating bound C?"
        ),
        "domain": "mathematics",
        "source_keys": ["global_id:GQ-1"],
        "aliases": ["Example finite-bound question"],
        "source_open_questions": [
            {
                "id": "source::open_question",
                "global_id": "GQ-1",
                "paper_id": "PAPER-1",
                "paper_title": "A paper with an explicit open question",
                "paper_doi": "10.0000/example",
                "content": (
                    "Does there exist a finite object satisfying A and B "
                    "while violating C?"
                ),
                "source_key": "global_id:GQ-1",
            }
        ],
    }
    triage = {
        "candidate_id": candidate_id,
        "importance_level": "high",
        "importance_rationale": "A counterexample changes a standard bound.",
        "expected_result": "A finite machine-readable witness.",
        "verification_difficulty": 0,
        "verification_difficulty_rationale": (
            "Checking the finite witness decides whether the problem is solved."
        ),
    }
    verdict = {"candidate_id": candidate_id, "verdict": "accept"}
    return candidate, triage, assessment(candidate_id), verdict


def compile_slug(research_assessment: dict[str, Any]) -> str:
    return slugify(research_assessment["canonical_title"])[:72].strip("-")


def test_concurrent_problem_id_allocation_stays_unique_and_contiguous(
    tmp_path: Path,
) -> None:
    workers = 8
    for round_index in range(3):
        round_root = tmp_path / f"round-{round_index}"
        barrier = threading.Barrier(workers)
        results: list[tuple[str, Path]] = []
        errors: list[BaseException] = []
        results_lock = threading.Lock()

        def allocate(index: int) -> None:
            pipeline = compile_campaign(
                round_root, f"alloc-{round_index}-{index}"
            )
            candidate_id = f"CAN-{index + 1:012X}"
            pipeline.state["candidates"][candidate_id] = {}
            try:
                barrier.wait(timeout=30)
                outcome = pipeline._reserve_problem_repo(
                    candidate_id, f"reserved-problem-{index}"
                )
                with results_lock:
                    results.append(outcome)
            except BaseException as error:
                with results_lock:
                    errors.append(error)

        threads = [
            threading.Thread(target=allocate, args=(index,))
            for index in range(workers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not any(thread.is_alive() for thread in threads)
        assert errors == []
        assert sorted(problem_id for problem_id, _ in results) == [
            f"ORP-{number:04d}" for number in range(1, workers + 1)
        ]
        assert all(repo_dir.is_dir() for _, repo_dir in results)


def test_compile_rebuilds_tracked_orphan_repository(tmp_path: Path) -> None:
    pipeline = compile_campaign(tmp_path, "orphan-recovery")
    candidate_id = "CAN-AAAA00000001"
    pipeline.state["candidates"][candidate_id] = {}
    candidate, triage, research_assessment, verdict = compile_inputs(
        candidate_id
    )
    compiled = pipeline._compile(
        candidate, triage, research_assessment, verdict
    )
    repo_dir = Path(compiled["problem_repo"])
    assert compiled["problem_id"] == "ORP-0001"

    # Simulate a crash after the repository was recorded but before
    # compile.json was written, leaving a partial repository behind.
    compile_path = (
        pipeline.run_dir / "candidates" / candidate_id / "compile.json"
    )
    compile_path.unlink()
    (repo_dir / "README.md").unlink()
    (repo_dir / "stray.txt").write_text("partial", encoding="utf-8")

    recompiled = pipeline._compile(
        candidate, triage, research_assessment, verdict
    )
    assert recompiled["problem_id"] == "ORP-0001"
    assert recompiled["problem_repo"] == str(repo_dir)
    assert not (repo_dir / "stray.txt").exists()
    readme_path = repo_dir / "README.md"
    assert readme_path.is_file()
    assert file_sha256(readme_path) == recompiled["readme_sha256"]
    # The rebuilt English README is rendered deterministically.
    assert recompiled["readme_sha256"] == compiled["readme_sha256"]
    readme = readme_path.read_text(encoding="utf-8")
    assert "## The Research Problem" in readme
    assert "## LKM and References" in readme
    assert sorted(path.name for path in repo_dir.iterdir()) == [
        ".git",
        "README.md",
    ]
    assert (
        subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_dir,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        == "1"
    )


def test_compile_adopts_empty_reservation_from_legacy_crash(
    tmp_path: Path,
) -> None:
    pipeline = compile_campaign(tmp_path, "legacy-crash-empty")
    candidate_id = "CAN-AAAA00000006"
    # Crash between the two legacy allocation saves: the ID is in state,
    # the repository path is not, and the reserved directory is still empty.
    pipeline.state["candidates"][candidate_id] = {"problem_id": "ORP-0001"}
    candidate, triage, research_assessment, verdict = compile_inputs(
        candidate_id
    )
    repo_dir = (
        tmp_path / "problems" / f"ORP-0001-{compile_slug(research_assessment)}"
    )
    repo_dir.mkdir(parents=True)

    compiled = pipeline._compile(
        candidate, triage, research_assessment, verdict
    )

    assert compiled["problem_id"] == "ORP-0001"
    assert compiled["problem_repo"] == str(repo_dir)
    assert pipeline.state["candidates"][candidate_id]["problem_repo"] == str(
        repo_dir
    )
    assert sorted(path.name for path in repo_dir.iterdir()) == [
        ".git",
        "README.md",
    ]


def test_compile_rebuilds_missing_reservation_from_legacy_crash(
    tmp_path: Path,
) -> None:
    pipeline = compile_campaign(tmp_path, "legacy-crash-missing")
    candidate_id = "CAN-AAAA00000007"
    # Same half-recorded legacy state, but the crash happened before the
    # reserving mkdir, so the derived directory does not exist at all.
    pipeline.state["candidates"][candidate_id] = {"problem_id": "ORP-0001"}
    candidate, triage, research_assessment, verdict = compile_inputs(
        candidate_id
    )
    repo_dir = (
        tmp_path / "problems" / f"ORP-0001-{compile_slug(research_assessment)}"
    )

    compiled = pipeline._compile(
        candidate, triage, research_assessment, verdict
    )

    assert compiled["problem_id"] == "ORP-0001"
    assert compiled["problem_repo"] == str(repo_dir)
    assert pipeline.state["candidates"][candidate_id]["problem_repo"] == str(
        repo_dir
    )
    assert sorted(path.name for path in repo_dir.iterdir()) == [
        ".git",
        "README.md",
    ]


def test_compile_refuses_untracked_existing_repository(tmp_path: Path) -> None:
    pipeline = compile_campaign(tmp_path, "untracked-repo")
    candidate_id = "CAN-AAAA00000002"
    # Legacy state recorded the problem ID without the repository path, so
    # the pre-existing directory cannot be identified as ours.
    pipeline.state["candidates"][candidate_id] = {"problem_id": "ORP-0007"}
    candidate, triage, research_assessment, verdict = compile_inputs(
        candidate_id
    )
    repo_dir = (
        tmp_path / "problems" / f"ORP-0007-{compile_slug(research_assessment)}"
    )
    repo_dir.mkdir(parents=True)
    (repo_dir / "README.md").write_text("untracked", encoding="utf-8")

    with pytest.raises(
        CampaignError, match="refusing to overwrite untracked"
    ):
        pipeline._compile(candidate, triage, research_assessment, verdict)
    assert (repo_dir / "README.md").read_text(encoding="utf-8") == "untracked"


def test_compile_cleans_partial_repository_after_produce_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = compile_campaign(tmp_path, "produce-failure")
    candidate_id = "CAN-AAAA00000003"
    pipeline.state["candidates"][candidate_id] = {}
    candidate, triage, research_assessment, verdict = compile_inputs(
        candidate_id
    )
    repo_dir = (
        tmp_path / "problems" / f"ORP-0001-{compile_slug(research_assessment)}"
    )

    monkeypatch.setattr(
        "open_research_discovery.campaign.validate_problem",
        lambda *args, **kwargs: ["injected validation failure"],
    )
    with pytest.raises(
        CampaignError, match="compiled problem ORP-0001 is invalid"
    ):
        pipeline._compile(candidate, triage, research_assessment, verdict)

    # The partial build was removed; the empty reservation remains so no
    # other campaign can reuse the problem ID.
    assert repo_dir.is_dir()
    assert list(repo_dir.iterdir()) == []

    monkeypatch.undo()
    compiled = pipeline._compile(
        candidate, triage, research_assessment, verdict
    )
    assert compiled["problem_id"] == "ORP-0001"
    assert compiled["problem_repo"] == str(repo_dir)
    assert sorted(path.name for path in repo_dir.iterdir()) == [
        ".git",
        "README.md",
    ]


def test_id_allocation_lock_file_is_not_scanned_as_problem_repo(
    tmp_path: Path,
) -> None:
    pipeline = compile_campaign(tmp_path, "lock-file-scan")
    candidate_id = "CAN-AAAA00000004"
    pipeline.state["candidates"][candidate_id] = {}
    problem_id, repo_dir = pipeline._reserve_problem_repo(
        candidate_id, "reserved-problem"
    )
    assert problem_id == "ORP-0001"
    lock_path = tmp_path / "problems" / ".id-allocation.lock"
    assert lock_path.is_file()
    assert problem_repo_paths(tmp_path / "problems") == []
    assert not re.match(r"ORP-(\d+)", lock_path.name)

    # The empty reserved directory still counts as a used problem ID.
    second_candidate_id = "CAN-AAAA00000005"
    pipeline.state["candidates"][second_candidate_id] = {}
    next_id, _ = pipeline._reserve_problem_repo(
        second_candidate_id, "another-problem"
    )
    assert next_id == "ORP-0002"
    assert repo_dir.is_dir()

class PrescreenRunner:
    """Runs only the prescreen role, selecting from the prompt's candidates."""

    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> AgentRun:
        assert role == "prescreen"
        self.calls += 1
        domain_id = re.search(r"from domain (\S+) for detailed", prompt)
        limit = re.search(r"Select exactly (\d+) atomic candidates", prompt)
        assert domain_id is not None and limit is not None
        candidates = json.loads(prompt.split("Candidates:\n", 1)[1])
        output = {
            "domain_id": domain_id.group(1),
            "selected": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "rationale": "Recall-prioritized selection.",
                }
                for candidate in candidates[: int(limit.group(1))]
            ],
            "rationale": "Bounded prescreen selection.",
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dump_json(output_path, output)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text("", encoding="utf-8")
        return AgentRun(
            output=output, metadata={"exit_code": 0, "role": role}
        )


def test_prescreen_cache_reuse_requires_matching_inputs(tmp_path: Path) -> None:
    pipeline = compile_campaign(tmp_path, "prescreen-cache-contract")
    runner = PrescreenRunner()
    pipeline.agent_runner = runner
    candidates = [
        {
            "candidate_id": f"CAN-{index:012X}",
            "domain": "mathematics",
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
                    "domain_id": "mathematics",
                    "domain_ids": ["mathematics"],
                    "paper_id": f"paper-{index}",
                    "paper_title": f"Paper {index}",
                    "paper_doi": "",
                }
            ],
        }
        for index in range(1, 4)
    ]

    selected = pipeline._prescreen_candidates(candidates, per_domain=1)
    assert len(selected) == 1
    assert runner.calls == 1

    # Identical candidate set, prompt, and limit: the StageLedger replays
    # the recorded output without invoking the agent again.
    replayed = pipeline._prescreen_candidates(candidates, per_domain=1)
    assert [item["candidate_id"] for item in replayed] == [
        item["candidate_id"] for item in selected
    ]
    assert runner.calls == 1

    # A different limit changes the input hash and must rerun the agent.
    expanded = pipeline._prescreen_candidates(candidates, per_domain=2)
    assert len(expanded) == 2
    assert runner.calls == 2

    # A changed candidate set also changes the input hash and must rerun.
    changed = [
        {
            **candidate,
            "canonical_statement": candidate["canonical_statement"] + " Revised.",
        }
        for candidate in candidates
    ]
    pipeline._prescreen_candidates(changed, per_domain=1)
    assert runner.calls == 3
