from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from open_research_discovery.agent import (
    AgentExecutionError,
    AgentOutputError,
    AgentRun,
    file_sha256,
)
from open_research_discovery.benchmark import (
    _cluster_candidate_ids as benchmark_candidate_ids,
)
from open_research_discovery.campaign import (
    CampaignError,
    CampaignPipeline,
    StageLedger,
    _campaign_run_lock,
    _candidate_id,
    _tool_version,
)
from open_research_discovery.cli import main as cli_main
from open_research_discovery.common import (
    dump_json,
    dump_yaml,
    problem_repo_paths,
    slugify,
)
from open_research_discovery.lkm import extract_paper_open_questions
from open_research_discovery.validation import validate_problem


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
                }
            elif role == "research":
                assert 'literal recent sentence saying "remains open"' in prompt
                assert (
                    "regardless of whether that check is automated or human" in prompt
                )
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

    def __init__(self, mutate: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
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
            "revision_instructions": review_round["revision_instructions"],
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
        "resolution_conclusion": "likely_open",
        "resolution_confidence": "medium",
        "literature_treatment": (
            "Later work proves a special case but continues to study the general regime."
        ),
        "status_rationale": "The citation chain leaves the general finite regime unsettled.",
        "checked_through": "2026-07-26",
        "major_progress_found": True,
        "major_progress_effect": "narrows",
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
    assert "## Background" in readme
    assert "## Problem Statement" in readme
    assert "## Verification Standard" in readme
    assert "## References" in readme
    assert "A JSON object containing the finite witness." in readme
    assert "The claim is decided by one finite object." in readme

    problem_paths = list(pipeline.run_dir.glob("candidates/*/problem.yaml"))
    assert len(problem_paths) == 1
    problem = yaml.safe_load(problem_paths[0].read_text(encoding="utf-8"))
    assert problem["status"] == "ready"
    assert problem["research_triage"]["route"] == "candidate-result"
    assert "coverage" not in problem["resolution_audit"]
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
    state = json.loads((pipeline.run_dir / "state.json").read_text(encoding="utf-8"))
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
    assert retry_state["stages"][f"candidate.{candidate_id}.research"]["attempt"] == 2
    assert retry_state["candidates"][candidate_id]["problem_id"] == "ORP-0001"

    recovered_state = json.loads(
        (pipeline.run_dir / "state.json").read_text(encoding="utf-8")
    )
    recovered_state["stages"][f"candidate.{candidate_id}.triage"]["status"] = "running"
    dump_json(pipeline.run_dir / "state.json", recovered_state)
    recovered = CampaignPipeline.resume(
        pipeline.run_dir,
        repository_root=repository_root,
        agent_runner=agents,
        paper_collector=fake_collector,
    )
    assert recovered.state["status"] == "interrupted"
    assert (
        recovered.state["stages"][f"candidate.{candidate_id}.triage"]["status"]
        == "interrupted"
    )


def test_campaign_run_lock_is_reentrant_and_blocks_other_process(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "shared-run"
    run_dir.mkdir()
    marker = tmp_path / "child-acquired"
    script = """
import sys
from pathlib import Path
from open_research_discovery.campaign import _campaign_run_lock

run_dir = Path(sys.argv[1])
marker = Path(sys.argv[2])
with _campaign_run_lock(run_dir):
    marker.write_text("acquired", encoding="utf-8")
""".strip()
    environment = dict(os.environ)
    source_path = str(repository_root / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (source_path, environment.get("PYTHONPATH", "")) if value
    )

    with _campaign_run_lock(run_dir):
        # Same-thread nesting must not attempt a second non-portable flock.
        with _campaign_run_lock(run_dir):
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(run_dir), str(marker)],
                cwd=repository_root,
                env=environment,
            )
            time.sleep(0.25)
            assert process.poll() is None
            assert not marker.exists()

    process.wait(timeout=10)
    assert process.returncode == 0
    assert marker.read_text(encoding="utf-8") == "acquired"


def test_full_campaign_triages_all_and_audits_high_difficulty_candidates(
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
            "max_verification_difficulty": 3,
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
            "canonical_title": "Important high-verification candidate",
        },
        {
            "candidate_id": "CAN-000000000002",
            "domain": "physics",
            "canonical_title": "Low-importance candidate",
        },
    ]
    for candidate in candidates:
        pipeline.state["candidates"][candidate["candidate_id"]] = {
            "status": "canonicalized"
        }
    triaged_ids: list[str] = []

    def fake_triage(
        candidate_list: list[dict[str, Any]], *, workers: int
    ) -> dict[str, dict[str, Any]]:
        assert workers == 2
        triaged_ids.extend(candidate["candidate_id"] for candidate in candidate_list)
        return {
            "CAN-000000000001": {
                "candidate_id": "CAN-000000000001",
                "importance_level": "high",
                "importance_rationale": "The result changes the field.",
                "expected_result": "A complete theorem.",
                "verification_difficulty": 9,
                "verification_difficulty_rationale": "Review is extensive.",
                "ci_status": "solution-reviewer-only",
            },
            "CAN-000000000002": {
                "candidate_id": "CAN-000000000002",
                "importance_level": "low",
                "importance_rationale": "Too narrow for the campaign.",
                "expected_result": "A finite witness.",
                "verification_difficulty": 0,
                "verification_difficulty_rationale": "The witness is directly checked.",
                "ci_status": "pseudocode",
            },
        }

    def fake_audit(
        candidate_list: list[dict[str, Any]],
        triage_by_id: dict[str, dict[str, Any]],
        **_: Any,
    ) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
        assert [item["candidate_id"] for item in candidate_list] == ["CAN-000000000001"]
        assert triage_by_id["CAN-000000000001"]["verification_difficulty"] == 9
        return {
            "CAN-000000000001": (
                {"verdict": "revise"},
                {},
            )
        }

    monkeypatch.setattr(pipeline, "_discover", lambda: {})
    monkeypatch.setattr(pipeline, "_ingest", lambda discovered: [])
    monkeypatch.setattr(pipeline, "_canonicalize", lambda questions: candidates)
    monkeypatch.setattr(pipeline, "_triage_candidates", fake_triage)
    monkeypatch.setattr(pipeline, "_audit_candidates", fake_audit)
    monkeypatch.setattr(pipeline, "_write_triage_deferred", lambda items: None)
    monkeypatch.setattr(pipeline, "_sync_and_rank", lambda accepted: [])

    summary = pipeline.run()

    assert triaged_ids == [
        "CAN-000000000001",
        "CAN-000000000002",
    ]
    assert summary["canonical_candidates"] == 2
    assert summary["triage_deferred_count"] == 1
    assert (
        pipeline.state["candidates"]["CAN-000000000001"]["status"] == "needs_revision"
    )


def test_publication_gate_excludes_resolved_or_over_limit_assessments() -> None:
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
    assert pipeline._passes_publication_gate(assessment)
    assert pipeline._passes_publication_gate(
        {**assessment, "post_progress_decision": "rewrite-core"}
    )
    assert pipeline._passes_publication_gate(
        {**assessment, "post_progress_decision": "new-derived-problem"}
    )
    assert pipeline._passes_publication_gate(
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
        assert not pipeline._passes_publication_gate({**assessment, field: value})


def test_publication_gate_requires_major_progress_for_partial_resolution() -> None:
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
    assert not pipeline._passes_publication_gate(
        {**assessment, "major_progress_found": False}
    )
    assert pipeline._passes_publication_gate(
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
        candidate["status"] for candidate in pipeline.state["candidates"].values()
    }
    assert statuses == {"audited_out"}
    assert pipeline.state["status"] == "completed"
    problems_root = tmp_path / "problems"
    reserved = list(problems_root.glob("ORP-*")) if problems_root.is_dir() else []
    assert reserved == []


def test_verification_gate_uses_configured_numeric_threshold() -> None:
    pipeline = object.__new__(CampaignPipeline)
    triage = {
        "importance_level": "high",
        "verification_difficulty": 1,
    }

    pipeline.config = {"limits": {"max_verification_difficulty": 0}}
    assert pipeline._passes_audit_gate(triage)
    assert not pipeline._passes_triage_publication_gate(triage)

    pipeline.config = {"limits": {"max_verification_difficulty": 1}}
    assert pipeline._passes_audit_gate(triage)
    assert pipeline._passes_triage_publication_gate(triage)


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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
    state = json.loads((pipeline.run_dir / "state.json").read_text(encoding="utf-8"))
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
        revision["problem_review_attempt"] for revision in history["revisions"]
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
    research_prompts = [prompt for role, prompt in agents.prompts if role == "research"]
    assert (
        "Clarify why the 2025 result is only a special case." in (research_prompts[-1])
    )
    applied = json.loads(applied_path.read_text(encoding="utf-8"))
    assert len(applied["feedback_sources"]) == 1

    calls_before_legacy_resume = list(agents.calls)
    applied_path.unlink()
    for stage_key in (research_key, review_key):
        pipeline.state["stages"][stage_key]["pipeline_version"] = 7
        pipeline.state["stages"][stage_key]["input_sha256"] = "legacy-input"
    pipeline.state["candidates"][candidate_id].pop("research_feedback_sha256")
    pipeline.ledger.save()

    pipeline.run()

    assert agents.calls == calls_before_legacy_resume + [
        "research",
        "problem-reviewer",
    ]
    assert pipeline.state["stages"][research_key]["attempt"] == 3
    assert pipeline.state["stages"][review_key]["attempt"] == 4
    research_prompts = [prompt for role, prompt in agents.prompts if role == "research"]
    assert (
        "Clarify why the 2025 result is only a special case." in (research_prompts[-1])
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
        revision["problem_review_attempt"] for revision in recovered["revisions"]
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
    first_research_hash = pipeline.state["stages"][research_stage_key]["input_sha256"]
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
    second_research_hash = pipeline.state["stages"][research_stage_key]["input_sha256"]
    calls_after_second_review = list(agents.calls)

    pipeline.run()

    assert agents.calls == calls_after_second_review
    assert pipeline.state["stages"][research_stage_key]["attempt"] == 2

    third_summary = pipeline.retry(candidate_id, "research")
    assert third_summary["accepted_problem_ids"] == ["ORP-0001"]
    third_research_hash = pipeline.state["stages"][research_stage_key]["input_sha256"]
    assert len({first_research_hash, second_research_hash, third_research_hash}) == 3

    research_prompts = [prompt for role, prompt in agents.prompts if role == "research"]
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
        revision["problem_review_attempt"] for revision in history["revisions"]
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
    assert all(revision["verdict_sha256"] for revision in history["revisions"][1:])
    final_verdict = json.loads(
        (candidate_dir / "problem-review-verdict.json").read_text(encoding="utf-8")
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
    applied_snapshot = json.loads(applied_path.read_text(encoding="utf-8"))
    tampered_snapshot = {
        **applied_snapshot,
        "concerns": [*applied_snapshot["concerns"], "Unrecorded concern."],
    }
    dump_json(applied_path, tampered_snapshot)

    with pytest.raises(
        CampaignError,
        match="snapshot does not match recorded state",
    ):
        pipeline._research_feedback_snapshot(
            candidate_id,
            candidate_dir,
            pipeline._recover_problem_review_feedback(candidate_id, candidate_dir),
            apply_pending=False,
        )

    # Through the full run the same integrity failure is quarantined to the
    # candidate instead of aborting the campaign.
    pipeline.run()
    assert agents.calls == calls_after_accept
    candidate_state = pipeline.state["candidates"][candidate_id]
    assert candidate_state["status"] == "research_failed"
    assert "snapshot does not match recorded state" in candidate_state[
        "research_error"
    ]
    assert pipeline.state["status"] == "completed"
    dump_json(applied_path, applied_snapshot)
    pipeline.state["stages"][research_stage_key]["pipeline_version"] = 7
    pipeline.ledger.save()
    applied_path.unlink()

    pipeline.run()

    assert agents.calls == calls_after_accept
    candidate_state = pipeline.state["candidates"][candidate_id]
    assert candidate_state["status"] == "research_failed"
    assert "Research is missing its recorded" in candidate_state["research_error"]
    dump_json(applied_path, applied_snapshot)
    pipeline.state["stages"][research_stage_key]["pipeline_version"] = 8
    pipeline.state["stages"][research_stage_key]["status"] = "failed"
    pipeline.ledger.save()
    applied_path.unlink()

    pipeline.run()

    assert agents.calls == calls_after_accept
    candidate_state = pipeline.state["candidates"][candidate_id]
    assert candidate_state["status"] == "research_failed"
    assert "Research is missing its recorded" in candidate_state["research_error"]


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
    assert [item["feedback_id"] for item in loaded["revisions"]] == ["manual-feedback"]
    assert loaded["accumulated_concerns"] == ["Keep this concern."]
    assert loaded["accumulated_revision_instructions"] == ["Keep this instruction."]


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


def test_candidate_audit_chains_run_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = object.__new__(CampaignPipeline)
    candidates = [{"candidate_id": f"CAN-{index:012X}"} for index in range(1, 4)]
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
    assert list(audits) == [candidate["candidate_id"] for candidate in candidates]
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

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
            candidate_match = re.search(r"CAN-[A-F0-9]{12}", kwargs["prompt"])
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
                self.roles_by_candidate.setdefault(candidate_id, []).append(role)
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
    assert list(audits) == [candidate["candidate_id"] for candidate in candidates]
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
        assert not (candidate_dir / "problem-review-feedback-history.json").exists()
        assert (
            pipeline.state["stages"][f"candidate.{candidate_id}.research"]["status"]
            == "completed"
        )
        assert (
            pipeline.state["stages"][f"candidate.{candidate_id}.problem-review"][
                "status"
            ]
            == "completed"
        )


def test_parallel_candidate_audit_errors_are_stably_quarantined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = object.__new__(CampaignPipeline)
    pipeline.state = {
        "status": "running",
        "error": "",
        "candidates": {
            candidate_id: {"status": "canonicalized"}
            for candidate_id in (
                "CAN-000000000003",
                "CAN-000000000001",
                "CAN-000000000002",
            )
        },
    }
    pipeline.ledger = StageLedger(tmp_path, pipeline.state)
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

    audits = pipeline._audit_candidates(
        candidates,
        triage_by_id,
        workers=3,
    )

    # Failures are quarantined per candidate instead of aborting the batch;
    # the surviving candidate keeps its deterministic position.
    assert list(audits) == ["CAN-000000000002"]
    assert audits["CAN-000000000002"][0]["verdict"] == "accept"
    for candidate_id in ("CAN-000000000001", "CAN-000000000003"):
        state = pipeline.state["candidates"][candidate_id]
        assert state["status"] == "research_failed"
        assert state["research_error"] == f"RuntimeError: failed {candidate_id}"
        assert state["research_error_class"] == "execution"
        assert state["research_error_refinable"] is False


def test_parallel_audit_and_compile_preserve_deterministic_problem_id_order(
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
        pipeline.state["candidates"][candidate_id] = {"status": "canonicalized"}
    completion_order: list[str] = []
    compile_barrier = threading.Barrier(3)
    compile_lock = threading.Lock()
    active_compiles = 0
    max_active_compiles = 0
    barrier = threading.Barrier(3)
    release = {candidate_id: threading.Event() for candidate_id in candidate_ids}
    completed = {candidate_id: threading.Event() for candidate_id in candidate_ids}

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
        nonlocal active_compiles, max_active_compiles
        candidate_id = candidate["candidate_id"]
        with compile_lock:
            active_compiles += 1
            max_active_compiles = max(max_active_compiles, active_compiles)
        compile_barrier.wait(timeout=5)
        with compile_lock:
            active_compiles -= 1
        problem_id = pipeline.state["candidates"][candidate_id]["problem_id"]
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
    assert max_active_compiles == 3
    assert [
        pipeline.state["candidates"][candidate_id]["problem_id"]
        for candidate_id in candidate_ids
    ] == ["ORP-0001", "ORP-0002", "ORP-0003"]
    assert summary["accepted_problem_ids"] == [
        "ORP-0001",
        "ORP-0002",
        "ORP-0003",
    ]


def test_parallel_audit_failure_quarantines_and_compiles_survivors(
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
        pipeline.state["candidates"][candidate_id] = {"status": "canonicalized"}
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

    def fake_compile(candidate: dict[str, Any], *args: Any) -> dict[str, Any]:
        compile_calls.append(candidate["candidate_id"])
        return {"problem_id": "ORP-0001"}

    monkeypatch.setattr(pipeline, "_compile", fake_compile)
    monkeypatch.setattr(
        pipeline,
        "_sync_and_rank",
        lambda accepted: ranking_calls.append(accepted) or [],
    )

    summary = pipeline.run()

    # Quarantine keeps the run alive: the healthy candidate compiles and the
    # failed ones are recorded instead of aborting the campaign.
    assert compile_calls == ["CAN-000000000002"]
    assert ranking_calls == [["ORP-0001"]]
    assert summary["accepted_problem_ids"] == ["ORP-0001"]
    assert summary["failed_candidates"] == [
        {
            "candidate_id": "CAN-000000000003",
            "error": "RuntimeError: failed CAN-000000000003",
            "refinable": False,
        },
        {
            "candidate_id": "CAN-000000000001",
            "error": "RuntimeError: failed CAN-000000000001",
            "refinable": False,
        },
    ]
    for candidate_id in ("CAN-000000000001", "CAN-000000000003"):
        state = pipeline.state["candidates"][candidate_id]
        assert state["status"] == "research_failed"
        assert state["research_error_class"] == "execution"
    saved = json.loads((pipeline.run_dir / "state.json").read_text(encoding="utf-8"))
    assert saved["status"] == "completed"
    assert saved["error"] == ""


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

    output["clusters"][0]["source_support"][0]["exact_excerpt"] = (
        "invented sharper conjecture"
    )
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
                "Does there exist a finite object satisfying A and B while violating C?"
            ),
            "paper_id": "PAPER-1",
            "paper_doi": "",
            "paper_title": "Finite witness question",
        }
    ]

    with pytest.raises(CampaignError, match="exact substring"):
        pipeline._canonicalize(questions)
    assert pipeline.state["stages"]["campaign.canonicalization"]["status"] == "failed"

    candidates = pipeline._canonicalize(questions)

    assert len(candidates) == 1
    assert runner.canonicalization_attempts == 2
    assert pipeline.state["stages"]["campaign.canonicalization"]["attempt"] == 2
    assert (
        pipeline.state["stages"]["campaign.canonicalization"]["status"] == "completed"
    )


def _excerpt_repair_pipeline(tmp_path: Path, name: str) -> CampaignPipeline:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": name,
        "domains": [
            {
                "id": "mathematics",
                "query": "Find mathematics questions.",
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
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id=name,
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
    )


def _excerpt_repair_cluster(
    source_key: str, title: str, excerpt: str
) -> dict[str, Any]:
    return {
        "canonical_title": title,
        "canonical_statement": f"Determine {title}.",
        "domain": "mathematics",
        "source_keys": [source_key],
        "source_support": [{"source_key": source_key, "exact_excerpt": excerpt}],
        "aliases": [],
        "rationale": "The source states this target explicitly.",
    }


def test_canonicalization_excerpt_repair_restores_verbatim_spans(
    tmp_path: Path,
) -> None:
    pipeline = _excerpt_repair_pipeline(tmp_path, "excerpt-repair")
    questions = [
        {
            "source_key": "global_id:GQ-CAP",
            "content": (
                "We leave open whether the impact of large-$L$ features on "
                "convergence rates can be quantified."
            ),
            "paper_id": "PAPER-CAP",
            "paper_doi": "",
            "paper_title": "Capitalization question",
        },
        {
            "source_key": "global_id:GQ-TEX",
            "content": (
                "A second target concerns large-$L features with sparse "
                "structure, which remain poorly understood."
            ),
            "paper_id": "PAPER-TEX",
            "paper_doi": "",
            "paper_title": "LaTeX delimiter question",
        },
        {
            "source_key": "global_id:GQ-EXACT",
            "content": "Finally, construct one explicit witness for the bound.",
            "paper_id": "PAPER-EXACT",
            "paper_doi": "",
            "paper_title": "Exact excerpt question",
        },
    ]
    output = {
        "clusters": [
            _excerpt_repair_cluster(
                "global_id:GQ-CAP",
                "impact of large-L features",
                "The impact of large-$L$ features on convergence rates",
            ),
            _excerpt_repair_cluster(
                "global_id:GQ-TEX",
                "sparse large-L features",
                "large-$L$ features with sparse structure",
            ),
            _excerpt_repair_cluster(
                "global_id:GQ-EXACT",
                "explicit witness",
                "construct one explicit witness",
            ),
        ]
    }
    repairs: list[dict[str, Any]] = []
    CampaignPipeline._validate_canonicalization(output, questions, repairs)

    supports = [cluster["source_support"][0] for cluster in output["clusters"]]
    assert (
        supports[0]["exact_excerpt"]
        == "the impact of large-$L$ features on convergence rates"
    )
    assert supports[1]["exact_excerpt"] == "large-$L features with sparse structure"
    assert supports[2]["exact_excerpt"] == "construct one explicit witness"
    assert [repair["source_key"] for repair in repairs] == [
        "global_id:GQ-CAP",
        "global_id:GQ-TEX",
    ]
    assert (
        repairs[0]["original_excerpt"]
        == "The impact of large-$L$ features on convergence rates"
    )
    assert (
        repairs[0]["repaired_excerpt"]
        == "the impact of large-$L$ features on convergence rates"
    )
    assert repairs[1]["original_excerpt"] == (
        "large-$L$ features with sparse structure"
    )

    candidates = pipeline._materialize_candidates(output, questions)

    for candidate in candidates:
        support = candidate["source_support"][0]
        question = candidate["source_open_questions"][0]
        assert support["exact_excerpt"] in question["content"]


def test_canonicalization_excerpt_repair_is_audited(
    tmp_path: Path,
) -> None:
    class CapitalizingRunner(FakeAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "canonicalization":
                support = result.output["clusters"][0]["source_support"][0]
                support["exact_excerpt"] = (
                    "There exists a finite object satisfying A and B"
                )
                dump_json(kwargs["output_path"], result.output)
            return result

    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "excerpt-repair-audit",
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
        run_id="excerpt-repair-audit",
        agent_runner=CapitalizingRunner(),
        paper_collector=fake_collector,
    )
    questions = [
        {
            "source_key": "global_id:GQ-1",
            "content": (
                "We ask whether there exists a finite object satisfying A "
                "and B while violating C."
            ),
            "paper_id": "PAPER-1",
            "paper_doi": "",
            "paper_title": "Finite witness question",
        }
    ]

    candidates = pipeline._canonicalize(questions)

    assert len(candidates) == 1
    support = candidates[0]["source_support"][0]
    assert support["exact_excerpt"] == "there exists a finite object satisfying A and B"
    repairs = json.loads(
        (pipeline.run_dir / "canonicalization-repairs.json").read_text(encoding="utf-8")
    )
    assert repairs["schema_version"] == 1
    assert repairs["repairs"] == [
        {
            "source_key": "global_id:GQ-1",
            "canonical_title": "Finite witness for the example bound",
            "original_excerpt": "There exists a finite object satisfying A and B",
            "repaired_excerpt": "there exists a finite object satisfying A and B",
            "similarity": 1.0,
        }
    ]
    artifact = json.loads(
        (pipeline.run_dir / "canonicalization.json").read_text(encoding="utf-8")
    )
    assert (
        artifact["clusters"][0]["source_support"][0]["exact_excerpt"]
        == "there exists a finite object satisfying A and B"
    )


def test_canonicalization_excerpt_repair_stays_fail_closed() -> None:
    cap_question = {
        "source_key": "global_id:GQ-CAP",
        "content": (
            "We leave open whether the impact of large-$L$ features on "
            "convergence rates can be quantified."
        ),
        "paper_id": "PAPER-CAP",
        "paper_doi": "",
        "paper_title": "Capitalization question",
    }
    dup_question = {
        "source_key": "global_id:GQ-DUP",
        "content": "Check the bound. Then recheck the bound carefully.",
        "paper_id": "PAPER-DUP",
        "paper_doi": "",
        "paper_title": "Repeated phrase question",
    }
    paraphrased = {
        "clusters": [
            _excerpt_repair_cluster(
                "global_id:GQ-CAP",
                "impact of large-L features",
                "The impact of large-$L$ features on convergence rated",
            )
        ]
    }
    with pytest.raises(CampaignError, match="exact substring"):
        CampaignPipeline._validate_canonicalization(paraphrased, [cap_question])

    fabricated = {
        "clusters": [
            _excerpt_repair_cluster(
                "global_id:GQ-CAP",
                "impact of large-L features",
                "an invented sharper conjecture never stated",
            )
        ]
    }
    with pytest.raises(CampaignError, match="exact substring"):
        CampaignPipeline._validate_canonicalization(fabricated, [cap_question])

    ambiguous = {
        "clusters": [
            _excerpt_repair_cluster("global_id:GQ-DUP", "the bound", "The bound")
        ]
    }
    with pytest.raises(CampaignError, match="ambiguous alignment"):
        CampaignPipeline._validate_canonicalization(ambiguous, [dup_question])


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
    assert stored["outputs"]["problem_root"] == str((tmp_path / "problems").resolve())


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
    state = json.loads((pipeline.run_dir / "state.json").read_text(encoding="utf-8"))
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
        (pipeline.run_dir / "domains/mathematics/source-open-questions.json").read_text(
            encoding="utf-8"
        )
    )
    assert extraction["papers"][0]["identifier"] == {"doi": "10.0000/example"}
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
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
            pipeline = compile_campaign(round_root, f"alloc-{round_index}-{index}")
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
            threading.Thread(target=allocate, args=(index,)) for index in range(workers)
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
    candidate, triage, research_assessment, verdict = compile_inputs(candidate_id)
    compiled = pipeline._compile(candidate, triage, research_assessment, verdict)
    repo_dir = Path(compiled["problem_repo"])
    assert compiled["problem_id"] == "ORP-0001"

    # Simulate a crash after the repository was recorded but before
    # compile.json was written, leaving a partial repository behind.
    compile_path = pipeline.run_dir / "candidates" / candidate_id / "compile.json"
    compile_path.unlink()
    (repo_dir / "README.md").unlink()
    (repo_dir / "stray.txt").write_text("partial", encoding="utf-8")

    recompiled = pipeline._compile(candidate, triage, research_assessment, verdict)
    assert recompiled["problem_id"] == "ORP-0001"
    assert recompiled["problem_repo"] == str(repo_dir)
    assert not (repo_dir / "stray.txt").exists()
    readme_path = repo_dir / "README.md"
    assert readme_path.is_file()
    assert file_sha256(readme_path) == recompiled["readme_sha256"]
    # The rebuilt English README is rendered deterministically.
    assert recompiled["readme_sha256"] == compiled["readme_sha256"]
    readme = readme_path.read_text(encoding="utf-8")
    assert "## Background" in readme
    assert "## Problem Statement" in readme
    assert "## References" in readme
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


def test_cached_compile_requires_git_integrity_and_allows_descendant_commits(
    tmp_path: Path,
) -> None:
    pipeline = compile_campaign(tmp_path, "cached-git-integrity")
    candidate_id = "CAN-AAAA00000009"
    pipeline.state["candidates"][candidate_id] = {}
    candidate, triage, research_assessment, verdict = compile_inputs(candidate_id)
    compiled = pipeline._compile(candidate, triage, research_assessment, verdict)
    repo_dir = Path(compiled["solution_repo"])
    notes = repo_dir / "research-notes.md"
    notes.write_text("preserve this user-owned work\n", encoding="utf-8")
    subprocess.run(["git", "add", "research-notes.md"], cwd=repo_dir, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Researcher",
            "-c",
            "user.email=researcher@example.test",
            "commit",
            "-m",
            "Add user research notes",
        ],
        cwd=repo_dir,
        text=True,
        capture_output=True,
        check=True,
    )

    assert pipeline._compile(candidate, triage, research_assessment, verdict) == compiled
    assert notes.read_text(encoding="utf-8") == "preserve this user-owned work\n"

    shutil.rmtree(repo_dir / ".git")
    with pytest.raises(CampaignError, match="lost its independent Git metadata"):
        pipeline._compile(candidate, triage, research_assessment, verdict)
    assert notes.read_text(encoding="utf-8") == "preserve this user-owned work\n"


def test_cached_compile_rejects_rewritten_git_history(tmp_path: Path) -> None:
    pipeline = compile_campaign(tmp_path, "cached-git-history-rewrite")
    candidate_id = "CAN-AAAA00000010"
    pipeline.state["candidates"][candidate_id] = {}
    candidate, triage, research_assessment, verdict = compile_inputs(candidate_id)
    compiled = pipeline._compile(candidate, triage, research_assessment, verdict)
    repo_dir = Path(compiled["solution_repo"])
    # Amend the only commit so the recorded compile head leaves the history.
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Researcher",
            "-c",
            "user.email=researcher@example.test",
            "commit",
            "--amend",
            "-m",
            "Rewrite the recorded compile commit",
        ],
        cwd=repo_dir,
        text=True,
        capture_output=True,
        check=True,
    )

    with pytest.raises(CampaignError, match="history no longer contains"):
        pipeline._compile(candidate, triage, research_assessment, verdict)


def test_compile_adopts_empty_reservation_from_legacy_crash(
    tmp_path: Path,
) -> None:
    pipeline = compile_campaign(tmp_path, "legacy-crash-empty")
    candidate_id = "CAN-AAAA00000006"
    # Crash between the two legacy allocation saves: the ID is in state,
    # the repository path is not, and the reserved directory is still empty.
    pipeline.state["candidates"][candidate_id] = {"problem_id": "ORP-0001"}
    candidate, triage, research_assessment, verdict = compile_inputs(candidate_id)
    repo_dir = tmp_path / "problems" / f"ORP-0001-{compile_slug(research_assessment)}"
    repo_dir.mkdir(parents=True)

    compiled = pipeline._compile(candidate, triage, research_assessment, verdict)

    assert compiled["problem_id"] == "ORP-0001"
    assert compiled["problem_repo"] == str(repo_dir)
    assert pipeline.state["candidates"][candidate_id]["problem_repo"] == str(repo_dir)
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
    candidate, triage, research_assessment, verdict = compile_inputs(candidate_id)
    repo_dir = tmp_path / "problems" / f"ORP-0001-{compile_slug(research_assessment)}"

    compiled = pipeline._compile(candidate, triage, research_assessment, verdict)

    assert compiled["problem_id"] == "ORP-0001"
    assert compiled["problem_repo"] == str(repo_dir)
    assert pipeline.state["candidates"][candidate_id]["problem_repo"] == str(repo_dir)
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
    candidate, triage, research_assessment, verdict = compile_inputs(candidate_id)
    repo_dir = tmp_path / "problems" / f"ORP-0007-{compile_slug(research_assessment)}"
    repo_dir.mkdir(parents=True)
    (repo_dir / "README.md").write_text("untracked", encoding="utf-8")

    with pytest.raises(CampaignError, match="refusing to overwrite untracked"):
        pipeline._compile(candidate, triage, research_assessment, verdict)
    assert (repo_dir / "README.md").read_text(encoding="utf-8") == "untracked"


def test_compile_cleans_partial_repository_after_produce_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = compile_campaign(tmp_path, "produce-failure")
    candidate_id = "CAN-AAAA00000003"
    pipeline.state["candidates"][candidate_id] = {}
    candidate, triage, research_assessment, verdict = compile_inputs(candidate_id)
    repo_dir = tmp_path / "problems" / f"ORP-0001-{compile_slug(research_assessment)}"

    monkeypatch.setattr(
        "open_research_discovery.campaign.validate_problem",
        lambda *args, **kwargs: ["injected validation failure"],
    )
    with pytest.raises(CampaignError, match="compiled problem ORP-0001 is invalid"):
        pipeline._compile(candidate, triage, research_assessment, verdict)

    # The partial build was removed; the empty reservation remains so no
    # other campaign can reuse the problem ID.
    assert repo_dir.is_dir()
    assert list(repo_dir.iterdir()) == []

    monkeypatch.undo()
    compiled = pipeline._compile(candidate, triage, research_assessment, verdict)
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
    next_id, _ = pipeline._reserve_problem_repo(second_candidate_id, "another-problem")
    assert next_id == "ORP-0002"
    assert repo_dir.is_dir()


def test_problem_manifest_reassessment_flags_follow_major_progress(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    pipeline = compile_campaign(tmp_path, "manifest-reassessed")
    candidate = {
        "candidate_id": "CAN-AAAA00000006",
        "domain": "mathematics",
        "source_open_questions": [
            {
                "id": "paper:1::open_question",
                "global_id": "gcn-open-1",
                "paper_id": "1",
                "paper_title": "A source paper",
                "paper_doi": "10.0000/source",
            }
        ],
    }
    triage = {
        "importance_level": "high",
        "importance_rationale": "A counterexample changes a standard bound.",
    }
    progressed = assessment("CAN-AAAA00000006")

    manifest = pipeline._problem_manifest("ORP-0001", candidate, triage, progressed)
    progress = manifest["resolution_audit"]["progress_assessment"]
    assert progress["major_progress_found"] is True
    assert progress["surviving_core_reassessed"] is True
    assert progress["importance_reassessed"] is True
    assert progress["solution_review_reassessed"] is True
    manifest_path = tmp_path / "progressed.yaml"
    dump_yaml(manifest_path, manifest)
    assert (
        validate_problem(
            manifest_path,
            repository_root / "schemas" / "problem.schema.json",
        )
        == []
    )

    quiet = {
        **assessment("CAN-AAAA00000006"),
        "major_progress_found": False,
        "major_progress_effect": "none",
        "post_progress_decision": "continue",
    }
    manifest = pipeline._problem_manifest("ORP-0002", candidate, triage, quiet)
    progress = manifest["resolution_audit"]["progress_assessment"]
    assert progress["major_progress_found"] is False
    assert progress["surviving_core_reassessed"] is False
    assert progress["importance_reassessed"] is False
    assert progress["solution_review_reassessed"] is False
    manifest_path = tmp_path / "quiet.yaml"
    dump_yaml(manifest_path, manifest)
    assert (
        validate_problem(
            manifest_path,
            repository_root / "schemas" / "problem.schema.json",
        )
        == []
    )


def start_multi_domain_campaign(
    tmp_path: Path,
    name: str,
    domain_ids: list[str],
    agents_overrides: dict[str, Any] | None = None,
    agent_runner: Any | None = None,
) -> CampaignPipeline:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": name,
        "domains": [
            {
                "id": domain_id,
                "query": f"Find finite targets in {domain_id}.",
                "seed_papers": [],
            }
            for domain_id in domain_ids
        ],
        "limits": {
            "papers_per_domain": 2,
            "questions_per_domain": 3,
            "lkm_timeout_seconds": 30,
        },
        "agents": {
            "model": "",
            "codex_executable": "codex",
            "sandbox": "read-only",
            "timeout_seconds": 3600,
            **(agents_overrides or {}),
        },
        "outputs": {
            "runs_root": str(tmp_path / "runs"),
            "problem_root": str(tmp_path / "problems"),
            "pool_root": "",
        },
    }
    config_path = tmp_path / f"{name}.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id=name,
        agent_runner=agent_runner or FakeAgentRunner(),
        paper_collector=fake_collector,
    )


def test_campaign_defaults_to_32_workers(tmp_path: Path) -> None:
    pipeline = start_multi_domain_campaign(
        tmp_path,
        "default-32-workers",
        ["alpha"],
    )

    assert pipeline.workers == 32
    assert pipeline.networked_workers == 32


def discovery_output(domain_id: str) -> dict[str, Any]:
    return {
        "domain_id": domain_id,
        "papers": [
            {
                "paper_id": f"PAPER-{domain_id}",
                "doi": "",
                "title": f"A {domain_id} paper with an explicit open question",
                "evidence": [],
            }
        ],
    }


def triage_output(candidate_id: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "importance_level": "medium",
        "importance_rationale": "Concrete consequence.",
        "expected_result": "A JSON witness.",
        "verification_difficulty": 0,
        "verification_difficulty_rationale": (
            "The JSON witness answers the finite target and is directly recomputable."
        ),
        "ci_status": "pseudocode",
    }


class ParallelDiscoveryRunner:
    """Discovery-only runner that proves real cross-domain concurrency."""

    def __init__(self, parties: int, slow_domain: str | None = None) -> None:
        self.barrier = threading.Barrier(parties)
        self.slow_domain = slow_domain
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.completed: list[str] = []

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> AgentRun:
        assert role == "discovery"
        match = re.search(r"Domain id: (\S+)", prompt)
        assert match is not None
        domain_id = match.group(1)
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.barrier.wait(timeout=5)
        if domain_id == self.slow_domain:
            time.sleep(0.1)
        with self.lock:
            self.active -= 1
            self.completed.append(domain_id)
        return AgentRun(
            output=discovery_output(domain_id),
            metadata={"exit_code": 0, "role": role},
        )


def test_discovery_runs_domains_in_parallel_and_merges_in_config_order(
    tmp_path: Path,
) -> None:
    runner = ParallelDiscoveryRunner(3, slow_domain="alpha")
    pipeline = start_multi_domain_campaign(
        tmp_path,
        "parallel-discovery",
        ["alpha", "beta", "gamma"],
        {"workers": 3},
        agent_runner=runner,
    )

    outputs = pipeline._discover()

    assert runner.max_active == 3
    # alpha finished last, but the merge follows the configured domain order.
    assert runner.completed[-1] == "alpha"
    assert list(outputs) == ["alpha", "beta", "gamma"]
    for domain_id in ("alpha", "beta", "gamma"):
        source = outputs[domain_id]
        assert source["domain_id"] == domain_id
        assert source["papers"][0]["paper_id"] == f"PAPER-{domain_id}"
        artifact = json.loads(
            (pipeline.run_dir / "domains" / domain_id / "source-papers.json").read_text(
                encoding="utf-8"
            )
        )
        assert artifact == source
        assert (
            pipeline.state["stages"][f"campaign.discovery.{domain_id}"]["status"]
            == "completed"
        )


def test_discovery_workers_one_keeps_serial_domain_order(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    lock = threading.Lock()
    active = 0
    max_active = 0

    class SerialDiscoveryRunner:
        def run(
            self,
            *,
            role: str,
            prompt: str,
            schema_path: Path,
            output_path: Path,
            events_path: Path,
        ) -> AgentRun:
            nonlocal active, max_active
            assert role == "discovery"
            match = re.search(r"Domain id: (\S+)", prompt)
            assert match is not None
            domain_id = match.group(1)
            with lock:
                active += 1
                max_active = max(max_active, active)
                events.append(f"start:{domain_id}")
            time.sleep(0.01)
            with lock:
                active -= 1
                events.append(f"end:{domain_id}")
            return AgentRun(
                output=discovery_output(domain_id),
                metadata={"exit_code": 0, "role": role},
            )

    pipeline = start_multi_domain_campaign(
        tmp_path,
        "serial-discovery",
        ["alpha", "beta", "gamma"],
        {"workers": 1},
        agent_runner=SerialDiscoveryRunner(),
    )

    outputs = pipeline._discover()

    assert max_active == 1
    assert events == [
        "start:alpha",
        "end:alpha",
        "start:beta",
        "end:beta",
        "start:gamma",
        "end:gamma",
    ]
    assert list(outputs) == ["alpha", "beta", "gamma"]


class GoverningRunner:
    """Tracks concurrent networked and non-networked agent invocations."""

    def __init__(self, triage_parties: int) -> None:
        self.triage_barrier = threading.Barrier(triage_parties)
        self.lock = threading.Lock()
        self.networked_active = 0
        self.max_networked_active = 0
        self.plain_active = 0
        self.max_plain_active = 0

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> AgentRun:
        if role == "discovery":
            match = re.search(r"Domain id: (\S+)", prompt)
            assert match is not None
            domain_id = match.group(1)
            with self.lock:
                self.networked_active += 1
                self.max_networked_active = max(
                    self.max_networked_active, self.networked_active
                )
            time.sleep(0.05)
            with self.lock:
                self.networked_active -= 1
            output = discovery_output(domain_id)
        elif role == "triage":
            match = re.search(r"CAN-[A-F0-9]{12}", prompt)
            assert match is not None
            with self.lock:
                self.plain_active += 1
                self.max_plain_active = max(self.max_plain_active, self.plain_active)
            self.triage_barrier.wait(timeout=5)
            with self.lock:
                self.plain_active -= 1
            output = triage_output(match.group(0))
        else:
            raise AssertionError(role)
        return AgentRun(output=output, metadata={"exit_code": 0, "role": role})


def test_networked_workers_bound_only_networked_roles(tmp_path: Path) -> None:
    runner = GoverningRunner(3)
    pipeline = start_multi_domain_campaign(
        tmp_path,
        "networked-governance",
        ["alpha", "beta", "gamma"],
        {"workers": 3, "networked_workers": 1, "retries": 0},
        agent_runner=runner,
    )

    outputs = pipeline._discover()
    assert list(outputs) == ["alpha", "beta", "gamma"]
    # workers=3 allows three discovery threads, but the shared semaphore
    # serializes the networked role.
    assert runner.max_networked_active == 1

    candidates = [
        {
            "candidate_id": f"CAN-{index:012X}",
            "canonical_title": f"Candidate {index}",
        }
        for index in range(1, 4)
    ]
    triage_by_id = pipeline._triage_candidates(candidates, workers=3)
    assert len(triage_by_id) == 3
    # Non-networked roles are not throttled by networked_workers.
    assert runner.max_plain_active == 3


class FlakyTriageRunner:
    """Fails the first ``failures`` invocations, then returns valid triage."""

    def __init__(self, failures: int) -> None:
        self.remaining = failures
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
        assert role == "triage"
        self.calls += 1
        if self.remaining:
            self.remaining -= 1
            raise RuntimeError("transport unavailable")
        match = re.search(r"CAN-[A-F0-9]{12}", prompt)
        assert match is not None
        return AgentRun(
            output=triage_output(match.group(0)),
            metadata={"exit_code": 0, "role": role},
        )


def triage_candidate() -> dict[str, Any]:
    return {
        "candidate_id": "CAN-000000000001",
        "canonical_title": "Finite witness candidate",
    }


def test_failed_agent_invocations_retry_then_succeed(tmp_path: Path) -> None:
    runner = FlakyTriageRunner(2)
    pipeline = start_multi_domain_campaign(
        tmp_path,
        "retry-success",
        ["alpha"],
        {"retries": 2, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    output = pipeline._triage(triage_candidate())

    assert output["candidate_id"] == "CAN-000000000001"
    assert runner.calls == 3
    assert (
        pipeline.state["stages"]["candidate.CAN-000000000001.triage"]["status"]
        == "completed"
    )


def test_agent_invocation_retry_exhaustion_fails(tmp_path: Path) -> None:
    runner = FlakyTriageRunner(5)
    pipeline = start_multi_domain_campaign(
        tmp_path,
        "retry-exhaustion",
        ["alpha"],
        {"retries": 1, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    with pytest.raises(RuntimeError, match="transport unavailable"):
        pipeline._triage(triage_candidate())

    assert runner.calls == 2
    assert (
        pipeline.state["stages"]["candidate.CAN-000000000001.triage"]["status"]
        == "failed"
    )


def test_agent_timeout_retries_then_fails(tmp_path: Path) -> None:
    class TimeoutRunner:
        """Always fails the way CodexRunner does on an enforced timeout."""

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
            del prompt, schema_path, output_path, events_path
            self.calls += 1
            raise AgentExecutionError(
                f"{role} timed out after 2s; killed process group"
            )

    runner = TimeoutRunner()
    pipeline = start_multi_domain_campaign(
        tmp_path,
        "retry-timeout",
        ["alpha"],
        {"retries": 1, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    with pytest.raises(AgentExecutionError, match="timed out after 2s"):
        pipeline._triage(triage_candidate())

    assert runner.calls == 2
    assert (
        pipeline.state["stages"]["candidate.CAN-000000000001.triage"]["status"]
        == "failed"
    )


def test_agent_output_contract_failures_are_not_retried(tmp_path: Path) -> None:
    class ContractFailureRunner:
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
            del prompt, schema_path, output_path, events_path
            self.calls += 1
            raise AgentOutputError(
                f"{role} output failed schema validation: missing field"
            )

    runner = ContractFailureRunner()
    pipeline = start_multi_domain_campaign(
        tmp_path,
        "retry-contract-failure",
        ["alpha"],
        {"retries": 2, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    with pytest.raises(AgentOutputError):
        pipeline._triage(triage_candidate())
    assert runner.calls == 1


def test_agent_validator_failures_are_not_retried(tmp_path: Path) -> None:
    class WrongCandidateRunner:
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
            del prompt, schema_path, output_path, events_path
            self.calls += 1
            return AgentRun(
                output=triage_output("CAN-FFFFFFFFFFFF"),
                metadata={"exit_code": 0, "role": role},
            )

    runner = WrongCandidateRunner()
    pipeline = start_multi_domain_campaign(
        tmp_path,
        "retry-validator-failure",
        ["alpha"],
        {"retries": 2, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    with pytest.raises(CampaignError, match="wrong candidate_id"):
        pipeline._triage(triage_candidate())
    assert runner.calls == 1


@pytest.mark.parametrize(
    "override",
    [
        {"workers": 0},
        {"workers": 129},
        {"networked_workers": 0},
        {"networked_workers": 129},
        {"retries": -1},
        {"retries": 6},
        {"retry_backoff_seconds": -1},
    ],
)
def test_invalid_agent_governance_config_is_rejected(
    tmp_path: Path, override: dict[str, Any]
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config = {
        "schema_version": 1,
        "name": "invalid-governance",
        "domains": [
            {"id": "alpha", "query": "Find finite targets.", "seed_papers": []}
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
            **override,
        },
        "outputs": {
            "runs_root": str(tmp_path / "runs"),
            "problem_root": str(tmp_path / "problems"),
            "pool_root": "",
        },
    }
    config_path = tmp_path / "invalid-governance.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    with pytest.raises(CampaignError, match="invalid campaign config"):
        CampaignPipeline.start(
            config_path,
            repository_root=repository_root,
            run_id="invalid-governance",
            agent_runner=FakeAgentRunner(),
            paper_collector=fake_collector,
        )


def test_agent_governance_bounds_are_enforced_on_construction(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    pipeline = start_multi_domain_campaign(tmp_path, "governance-bounds", ["alpha"])
    for key, value, message in (
        ("workers", 0, "agents.workers"),
        ("networked_workers", 0, "agents.networked_workers"),
        ("retries", 6, "agents.retries"),
        ("retry_backoff_seconds", -1, "agents.retry_backoff_seconds"),
    ):
        config = json.loads(json.dumps(pipeline.config))
        config["agents"][key] = value
        with pytest.raises(CampaignError, match=message):
            CampaignPipeline(
                repository_root=repository_root,
                run_dir=pipeline.run_dir,
                config=config,
                agent_runner=FakeAgentRunner(),
                paper_collector=fake_collector,
            )


class MultiCandidateAgentRunner(FakeAgentRunner):
    """Splits the single source question into three atomic candidates.

    Supports per-candidate Problem Review verdicts, per-candidate Research
    output mutations, and an optional barrier around Research calls to prove
    that deferred retries resume through the parallel audit path.
    """

    def __init__(self, review_verdict: str = "accept") -> None:
        super().__init__(review_verdict)
        self.verdicts_by_candidate: dict[str, str] = {}
        self.research_mutations: dict[str, dict[str, Any]] = {}
        self.research_barrier: threading.Barrier | None = None
        self.lock = threading.Lock()
        self.active_research = 0
        self.max_active_research = 0

    def run(self, **kwargs: Any) -> AgentRun:
        role = kwargs["role"]
        if role == "canonicalization":
            return self._run_canonicalization(**kwargs)
        candidate_id = ""
        if role in {"triage", "research", "problem-reviewer"}:
            candidate_match = re.search(r"CAN-[A-F0-9]{12}", kwargs["prompt"])
            assert candidate_match is not None
            candidate_id = candidate_match.group(0)
        if role == "problem-reviewer" and candidate_id in self.verdicts_by_candidate:
            self.review_verdict = self.verdicts_by_candidate[candidate_id]
        if role == "research" and self.research_barrier is not None:
            with self.lock:
                self.active_research += 1
                self.max_active_research = max(
                    self.max_active_research, self.active_research
                )
            self.research_barrier.wait(timeout=10)
        try:
            result = super().run(**kwargs)
        finally:
            if role == "research" and self.research_barrier is not None:
                with self.lock:
                    self.active_research -= 1
        if role == "research":
            mutation = self.research_mutations.get(candidate_id)
            if mutation:
                output = {**result.output, **mutation}
                dump_json(kwargs["output_path"], output)
                return AgentRun(output=output, metadata=result.metadata)
        return result

    def _run_canonicalization(self, **kwargs: Any) -> AgentRun:
        role = kwargs["role"]
        self.calls.append(role)
        self.prompts.append((role, kwargs["prompt"]))
        events_path = kwargs["events_path"]
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(
            json.dumps({"type": "fake", "role": role}) + "\n",
            encoding="utf-8",
        )
        source_key = "global_id:GQ-1"
        titles_and_excerpts = [
            (
                "Finite witness for the example bound",
                "Does there exist a finite object satisfying A and B while "
                "violating C?",
            ),
            (
                "Bounded witness sizes for the example bound",
                "a finite object satisfying A and B while violating C",
            ),
            (
                "Structure of example-bound witnesses",
                "satisfying A and B while violating C",
            ),
        ]
        output = {
            "clusters": [
                {
                    "canonical_title": title,
                    "canonical_statement": f"Determine the following: {title}.",
                    "domain": "mathematics",
                    "source_keys": [source_key],
                    "source_support": [
                        {
                            "source_key": source_key,
                            "exact_excerpt": excerpt,
                        }
                    ],
                    "aliases": [],
                    "rationale": "The source states this target explicitly.",
                }
                for title, excerpt in titles_and_excerpts
            ]
        }
        output_path = kwargs["output_path"]
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


def _deferred_retry_campaign(
    tmp_path: Path,
    name: str,
    agents: FakeAgentRunner,
    *,
    workers: int,
) -> CampaignPipeline:
    repository_root = Path(__file__).resolve().parents[1]
    limits: dict[str, Any] = {
        "papers_per_domain": 1,
        "questions_per_domain": 1,
        "lkm_timeout_seconds": 30,
    }
    config = {
        "schema_version": 1,
        "name": name,
        "domains": [
            {
                "id": "mathematics",
                "query": "Find finite targets.",
                "seed_papers": [],
            }
        ],
        "limits": limits,
        "agents": {
            "model": "",
            "codex_executable": "codex",
            "workers": workers,
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
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id=name,
        agent_runner=agents,
        paper_collector=fake_collector,
    )


def test_deferred_case_retry_invalidates_research_without_executing(
    tmp_path: Path,
) -> None:
    agents = FakeAgentRunner(review_verdict="revise")
    pipeline = _deferred_retry_campaign(tmp_path, "deferred-retry", agents, workers=1)

    first_summary = pipeline.run()
    assert first_summary["accepted_problem_ids"] == []
    candidate_id = next(iter(pipeline.state["candidates"]))
    candidate_state = pipeline.state["candidates"][candidate_id]
    assert candidate_state["status"] == "needs_revision"
    calls_before = list(agents.calls)

    result = pipeline.retry(candidate_id, "research", defer=True)

    assert result == {
        "candidate_id": candidate_id,
        "stage": "research",
        "deferred": True,
        "status": "retry_requested",
    }
    # Deferral must not invoke any agent; it only invalidates stages.
    assert agents.calls == calls_before
    assert candidate_state["status"] == "retry_requested"
    stages = pipeline.state["stages"]
    assert stages[f"candidate.{candidate_id}.triage"]["status"] == "completed"
    assert stages[f"candidate.{candidate_id}.research"]["status"] == "invalidated"
    assert stages[f"candidate.{candidate_id}.problem-review"]["status"] == "invalidated"
    # The applied-feedback snapshot already reflects the pending reviewer
    # feedback so the deferred execution addresses it.
    snapshot_path = (
        pipeline.run_dir
        / "candidates"
        / candidate_id
        / "research-feedback-applied.json"
    )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["concerns"] == [
        "Clarify why the 2025 result is only a special case."
    ]
    assert snapshot["revision_instructions"] == [
        "State the missing hypothesis in the surviving core."
    ]


def test_case_retry_cli_passes_defer_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = FakeAgentRunner(review_verdict="revise")
    pipeline = _deferred_retry_campaign(
        tmp_path, "deferred-retry-cli", agents, workers=1
    )
    pipeline.run()
    candidate_id = next(iter(pipeline.state["candidates"]))
    calls_before = list(agents.calls)
    # The CLI constructs its own runner; inject the fake so the test does
    # not depend on a local codex executable.
    real_resume = CampaignPipeline.resume

    def resume_with_fake(run_dir: Path, **kwargs: Any) -> CampaignPipeline:
        return real_resume(
            run_dir,
            agent_runner=agents,
            paper_collector=fake_collector,
            **kwargs,
        )

    monkeypatch.setattr(CampaignPipeline, "resume", resume_with_fake)

    exit_code = cli_main(
        [
            "case",
            "retry",
            str(pipeline.run_dir),
            candidate_id,
            "research",
            "--defer",
        ]
    )

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["summary"] == {
        "candidate_id": candidate_id,
        "stage": "research",
        "deferred": True,
        "status": "retry_requested",
    }
    assert agents.calls == calls_before
    state = json.loads((pipeline.run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["candidates"][candidate_id]["status"] == "retry_requested"


def test_deferred_research_retries_run_in_parallel_on_resume(
    tmp_path: Path,
) -> None:
    agents = MultiCandidateAgentRunner(review_verdict="revise")
    pipeline = _deferred_retry_campaign(
        tmp_path, "deferred-parallel", agents, workers=3
    )

    first_summary = pipeline.run()
    assert first_summary["accepted_problem_ids"] == []
    candidate_ids = sorted(pipeline.state["candidates"])
    assert len(candidate_ids) == 3
    assert all(
        pipeline.state["candidates"][candidate_id]["status"] == "needs_revision"
        for candidate_id in candidate_ids
    )

    # Deferring each retry is agent-free and seconds-fast.
    for candidate_id in candidate_ids:
        result = pipeline.retry(candidate_id, "research", defer=True)
        assert result["deferred"] is True
    calls_before_resume = list(agents.calls)

    agents.review_verdict = "accept"
    agents.research_barrier = threading.Barrier(3)
    second_summary = pipeline.run()

    # All three deferred candidates were audited by concurrent workers.
    assert agents.max_active_research == 3
    resume_calls = agents.calls[len(calls_before_resume) :]
    assert resume_calls.count("research") == 3
    assert resume_calls.count("problem-reviewer") == 3
    assert "triage" not in resume_calls
    assert "discovery" not in resume_calls
    assert all(
        pipeline.state["candidates"][candidate_id]["status"] == "accepted"
        for candidate_id in candidate_ids
    )
    assert len(second_summary["accepted_problem_ids"]) == 3

    # Every deferred retry addressed the accumulated reviewer feedback.
    research_prompts = [prompt for role, prompt in agents.prompts if role == "research"]
    assert len(research_prompts) == 6
    for prompt in research_prompts[:3]:
        assert "Accumulated Problem Reviewer feedback" not in prompt
    for prompt in research_prompts[3:]:
        assert "Clarify why the 2025 result is only a special case." in prompt

    # A further resume is a no-op: completed candidates are not re-audited.
    agents.research_barrier = None
    calls_after_resume = list(agents.calls)
    third_summary = pipeline.run()
    assert agents.calls == calls_after_resume
    assert (
        third_summary["accepted_problem_ids"] == second_summary["accepted_problem_ids"]
    )


def test_deferred_research_retry_status_transitions_on_resume(
    tmp_path: Path,
) -> None:
    agents = MultiCandidateAgentRunner(review_verdict="revise")
    pipeline = _deferred_retry_campaign(
        tmp_path, "deferred-transitions", agents, workers=1
    )

    pipeline.run()
    candidate_ids = sorted(pipeline.state["candidates"])
    assert len(candidate_ids) == 3
    accepted_id, audited_out_id, revise_id = candidate_ids
    for candidate_id in candidate_ids:
        pipeline.retry(candidate_id, "research", defer=True)

    agents.verdicts_by_candidate = {
        accepted_id: "accept",
        audited_out_id: "accept",
        revise_id: "revise",
    }
    agents.research_mutations = {audited_out_id: {"evidence": []}}
    summary = pipeline.run()

    accepted_state = pipeline.state["candidates"][accepted_id]
    audited_out_state = pipeline.state["candidates"][audited_out_id]
    revise_state = pipeline.state["candidates"][revise_id]
    assert accepted_state["status"] == "accepted"
    assert accepted_state["problem_id"]
    assert audited_out_state["status"] == "audited_out"
    assert not audited_out_state.get("problem_id")
    assert revise_state["status"] == "needs_revision"
    assert not revise_state.get("problem_id")
    assert summary["accepted_problem_ids"] == [accepted_state["problem_id"]]
    assert accepted_state["problem_review_verdict"] == "accept"
    assert audited_out_state["problem_review_verdict"] == "accept"
    assert revise_state["problem_review_verdict"] == "revise"


def test_deferred_research_retry_with_low_importance_is_skipped_on_resume(
    tmp_path: Path,
) -> None:
    agents = FakeAgentRunner(review_verdict="revise")
    pipeline = _deferred_retry_campaign(tmp_path, "deferred-gate", agents, workers=1)

    pipeline.run()
    candidate_id = next(iter(pipeline.state["candidates"]))

    # The candidate is no longer important enough for status Research.
    triage_path = pipeline.run_dir / "candidates" / candidate_id / "triage.json"
    triage = json.loads(triage_path.read_text(encoding="utf-8"))
    triage["importance_level"] = "low"
    dump_json(triage_path, triage)
    pipeline.state["stages"][f"candidate.{candidate_id}.triage"]["output_sha256"] = (
        file_sha256(triage_path)
    )
    pipeline.ledger.save()

    # Deferral does not re-check importance; execution does.
    result = pipeline.retry(candidate_id, "research", defer=True)
    assert result["deferred"] is True
    calls_before = list(agents.calls)

    summary = pipeline.run()

    assert agents.calls == calls_before
    assert pipeline.state["candidates"][candidate_id]["status"] == "triage_deferred"
    assert summary["triage_deferred_count"] == 1
    deferred = json.loads(
        (pipeline.run_dir / "triage-deferred.json").read_text(encoding="utf-8")
    )
    assert [record["candidate_id"] for record in deferred["candidates"]] == [
        candidate_id
    ]


def test_deferred_retry_audit_order_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = MultiCandidateAgentRunner(review_verdict="revise")
    pipeline = _deferred_retry_campaign(
        tmp_path,
        "deferred-audit-order",
        agents,
        workers=1,
    )

    pipeline.run()
    candidate_ids = sorted(pipeline.state["candidates"])
    for candidate_id in candidate_ids:
        pipeline.retry(candidate_id, "research", defer=True)

    agents.review_verdict = "accept"
    audit_orders: list[list[str]] = []
    real_audit = pipeline._audit_candidates

    def spy_audit(
        candidates: list[dict[str, Any]],
        triage_by_id: dict[str, dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
        audit_orders.append([candidate["candidate_id"] for candidate in candidates])
        return real_audit(candidates, triage_by_id, **kwargs)

    monkeypatch.setattr(pipeline, "_audit_candidates", spy_audit)
    pipeline.run()

    assert audit_orders == [candidate_ids]
