from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
import pytest

from open_research_discovery import campaign as campaign_mod
from open_research_discovery.agent import (
    AgentExecutionError,
    AgentOutputError,
    AgentRun,
)
from open_research_discovery.campaign import (
    CONTRACT_EVIDENCE,
    CONTRACT_STRUCTURE,
    CampaignError,
    CampaignPipeline,
)
from open_research_discovery.cli import main as cli_main
from open_research_discovery.common import dump_json
from open_research_discovery.problem_repo import README_SECTIONS, validate_problem_readme
from open_research_discovery.validation import validate_problem


def _unresolvable_fetch(kind: str, identifier: str) -> dict[str, Any]:
    """Offline citation fetcher for tests: everything is unresolvable."""

    return {
        "identifier": identifier,
        "kind": kind,
        "fetched_at": "",
        "status": "error",
        "metadata": {
            "title": "",
            "authors": [],
            "venue": "",
            "year": None,
            "doi": "",
            "url": "",
        },
        "detail": "test offline fetch",
    }


def _start_pipeline(*args: Any, **kwargs: Any) -> CampaignPipeline:
    kwargs.setdefault("citation_fetcher", _unresolvable_fetch)
    return CampaignPipeline.start(*args, **kwargs)


def _summary(
    lead_id: str,
    identifier: str,
    summary: str,
    kind: str,
) -> dict[str, Any]:
    return {
        "lead_id": lead_id,
        "summary": summary,
        "source_refs": [
            {
                "identifier": identifier,
                "kind": kind,
                "note": "LKM summary node backing this lead.",
            }
        ],
    }


def _selected_candidate(
    title: str,
    statement: str,
    source_key: str,
    importance: str,
) -> dict[str, Any]:
    return {
        "canonical_title": title,
        "canonical_statement": statement,
        "domain": "physics",
        "source_keys": [source_key],
        "importance_level": importance,
        "assessment": (
            "It tests a concrete boundary of the model; a resolution would separate a "
            "genuine finite-size mechanism from an artifact. The acceptance condition is "
            "an independently replayable check of every stated assumption and decisive step."
        ),
    }


class TopicAgentRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.prompts: dict[str, list[str]] = {}
        self.cwds: dict[str, list[Path | None]] = {}
        self.research_outputs: dict[str, dict[str, Any]] = {}
        self.write_notes = True
        self.write_review_notes = True

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
        cwd: Path | None = None,
    ) -> AgentRun:
        self.calls.append(role)
        self.prompts.setdefault(role, []).append(prompt)
        self.cwds.setdefault(role, []).append(cwd)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(json.dumps({"role": role}) + "\n", encoding="utf-8")
        if role == "discovery":
            output = {
                "domain_id": "hubbard",
                "selected_open_questions": [],
                "problem_summaries": [
                    _summary(
                        "book-target",
                        "《10000个科学难题》物理学卷",
                        "Determine whether the finite lattice admits the stated "
                        "witness; LKM marks the finite-regime target as open.",
                        "book",
                    ),
                    _summary(
                        "web-target",
                        "Finite-size transition bounds",
                        "Establish or refute the stated critical-coupling "
                        "interval; LKM shows no resolved later treatment.",
                        "lkm",
                    ),
                ],
            }
        elif role == "selection":
            output = {
                "candidates": [
                    _selected_candidate(
                        "Finite-lattice witness",
                        "Determine whether the finite lattice admits the stated witness.",
                        "lead:hubbard:book-target",
                        "high",
                    ),
                    _selected_candidate(
                        "Critical-coupling interval",
                        "Establish or refute the stated critical-coupling interval.",
                        "lead:hubbard:web-target",
                        "medium",
                    ),
                ]
            }
        else:
            # Candidate stages run with cwd=<candidate dir> (research) or
            # cwd=<candidate dir>/review-workdir (review); the fake agent
            # genuinely reads ./memory.md like the real instruction demands.
            assert cwd is not None
            memory = (cwd / "memory.md").read_text(encoding="utf-8")
            candidate_id = output_path.parent.name
            finite = "Determine whether the finite lattice admits the stated witness" in memory
            if role == "research":
                output = _assessment(candidate_id, finite=finite)
                self.research_outputs[candidate_id] = output
                # The real agent also leaves its audit notes in the workdir.
                if self.write_notes:
                    (cwd / "research-memory.md").write_text(
                        "# audit notes\n", encoding="utf-8"
                    )
            elif role == "problem-reviewer":
                research = self.research_outputs[candidate_id]
                output = {
                    "candidate_id": candidate_id,
                    "verdict": "accept",
                    "concerns": [],
                    "problem": {
                        key: value
                        for key, value in research.items()
                        if key != "audit_outcome"
                    },
                }
                # The real reviewer also leaves its review notes in the
                # review-workdir.
                if self.write_review_notes:
                    (cwd / "review-memory.md").write_text(
                        "# review notes\n", encoding="utf-8"
                    )
            else:
                raise AssertionError(role)
        dump_json(output_path, output)
        return AgentRun(
            output=output,
            metadata={"exit_code": 0, "role": role, "schema": str(schema_path)},
        )


def _assessment(candidate_id: str, *, finite: bool) -> dict[str, Any]:
    """Problem Schema v1.0 record content plus the audit outcome.

    The pipeline injects the mechanical fields (problem_id, status, domain,
    topic_id, repository, schema_version) during validation; they do not
    appear here.
    """

    del candidate_id  # the research stage is keyed by candidate already
    title = "Finite-lattice witness" if finite else "Critical-coupling interval"
    statement = (
        "Determine whether the finite lattice admits the stated witness."
        if finite
        else "Establish or refute the stated critical-coupling interval."
    )
    answer_types = ["proof", "counterexample"] if finite else [
        "proof",
        "certified numerical bound",
    ]
    contract = {
        answer_type: {
            "contract": (
                "Accept only after an independent reviewer checks the fixed "
                "assumptions, replays the decisive calculation, and confirms "
                "the claimed conclusion."
            ),
            "ci_contract": None,
        }
        for answer_type in answer_types
    }
    return {
        "audit_outcome": "open",
        "title": title,
        "abstract": "The audited scoped target remains unresolved.",
        "background": (
            "The source fixes the finite model, observable, and parameter "
            "regime. Adjacent parameter regimes are known, but this target "
            "is not."
        ),
        "references": [
            "Later status review. "
            "https://example.test/later-status-review, 2025."
        ],
        "previous_progress": [
            "Later work treats adjacent regimes but not this exact target; "
            "the audited literature leaves this scoped target unresolved."
        ],
        "problem_statement": statement,
        "scientific_significance": {
            "affected_field": {
                "level": "high" if finite else "medium",
                "description": (
                    "It would directly distinguish a physical mechanism from a "
                    "finite-size artifact."
                ),
            }
        },
        "solution_difficulty": [
            "The finite search space grows combinatorially.",
        ],
        "verification_contract": contract,
        "verification_difficulty": {
            "score": 10 if finite else 4,
            "rationale": "The score measures residual reviewer burden.",
        },
    }


def _config(tmp_path: Path) -> Path:
    config = {
        "schema_version": 2,
        "name": "hubbard-topic-campaign",
        "topics": [
            {
                "id": "hubbard",
                "title": "Hubbard Model",
                "query": "Find scoped, independently verifiable open problems.",
                "sources": ["topic_search"],
                "seed_papers": [],
                "seed_references": [],
            }
        ],
        "limits": {
            "questions_per_domain": 10,
            "lkm_timeout_seconds": 30,
        },
        "agents": {
            "model": "",
            "codex_executable": "codex",
            "sandbox": "read-only",
            "timeout_seconds": 3600,
            "workers": 1,
        },
        "outputs": {
            "runs_root": str(tmp_path / "runs"),
            "problem_root": str(tmp_path / "problems"),
            "pool_root": "",
        },
    }
    path = tmp_path / "campaign.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _review_pipeline() -> CampaignPipeline:
    pipeline = object.__new__(CampaignPipeline)
    pipeline._problem_schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "schemas" / "problem.schema.json"
        ).read_text(encoding="utf-8")
    )
    return pipeline


def test_review_status_override_requires_cited_evidence() -> None:
    candidate = {
        "candidate_id": "CAN-ABCDEF012345",
        "domain": "physics",
        "topic_id": "hubbard",
    }
    pipeline = _review_pipeline()
    research = _assessment(candidate["candidate_id"], finite=True)
    pipeline._validate_research_output(research, candidate)
    problem = {key: value for key, value in research.items()}

    def verdict(**overrides: Any) -> dict[str, Any]:
        return {
            "candidate_id": candidate["candidate_id"],
            "verdict": "accept",
            "concerns": [],
            "problem": dict(problem),
            **overrides,
        }

    # An untouched status passes and keeps the research status.
    accepted = verdict()
    pipeline._validate_review_output(accepted, candidate, research)
    assert accepted["problem"]["status"] == "open"

    # A status override with evidence in concerns is adopted.
    accepted = verdict(
        concerns=["Resolved externally: DOI 10.0000/proof."],
        problem={**problem, "status": "resolved-externally"},
    )
    pipeline._validate_review_output(accepted, candidate, research)
    assert accepted["problem"]["status"] == "resolved-externally"

    # A nonempty previous_progress also counts as cited evidence.
    accepted = verdict(problem={**problem, "status": "uncertain"})
    pipeline._validate_review_output(accepted, candidate, research)
    assert accepted["problem"]["status"] == "uncertain"

    # Without any cited evidence the override is a contract failure.
    with pytest.raises(CampaignError, match="without citing evidence"):
        pipeline._validate_review_output(
            verdict(
                problem={
                    **problem,
                    "status": "resolved-externally",
                    "previous_progress": [],
                }
            ),
            candidate,
            research,
        )

    # An unknown status value is rejected outright.
    with pytest.raises(CampaignError, match="invalid status"):
        pipeline._validate_review_output(
            verdict(concerns=["evidence"], problem={**problem, "status": "bogus"}),
            candidate,
            research,
        )

    # Every other mechanical field still cannot drift.
    with pytest.raises(CampaignError, match="changed mechanical fields"):
        pipeline._validate_review_output(
            verdict(problem={**problem, "domain": "tampered"}),
            candidate,
            research,
        )


def test_reviewer_reject_is_terminal(tmp_path: Path) -> None:
    class RejectRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "problem-reviewer":
                memory = (kwargs["cwd"] / "memory.md").read_text(
                    encoding="utf-8"
                )
                if "Determine whether the finite lattice admits the stated witness" in memory:
                    output = {
                        **result.output,
                        "verdict": "reject",
                        "concerns": ["The status evidence is insufficient."],
                    }
                    dump_json(kwargs["output_path"], output)
                    return AgentRun(output=output, metadata=result.metadata)
            return result

    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="reviewer-reject-terminal",
        agent_runner=RejectRunner(),
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 1
    rejected_state = next(
        state
        for state in pipeline.state["candidates"].values()
        if state["status"] == "rejected"
    )
    assert rejected_state["problem_review_verdict"] == "reject"
    assert not rejected_state.get("problem_id")
    verdict = json.loads(
        (
            Path(pipeline.run_dir)
            / "candidates"
            / next(
                candidate_id
                for candidate_id, state in pipeline.state["candidates"].items()
                if state["status"] == "rejected"
            )
            / "problem-review-verdict.json"
        ).read_text(encoding="utf-8")
    )
    assert verdict["concerns"] == ["The status evidence is insufficient."]


def test_review_edits_are_adopted_for_compilation(tmp_path: Path) -> None:
    class PolishingRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "problem-reviewer":
                output = result.output
                if output["problem"]["title"] == "Finite-lattice witness":
                    output["problem"]["title"] = (
                        "Finite-lattice witness (reviewed)"
                    )
                    dump_json(kwargs["output_path"], output)
                    return AgentRun(output=output, metadata=result.metadata)
            return result

    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="review-edits-adopted",
        agent_runner=PolishingRunner(),
    )

    summary = pipeline.run()

    reviewed = next(
        item
        for item in summary["solution_repositories"]
        if "reviewed" in Path(item["solution_repo"]).name
    )
    readme = (Path(reviewed["solution_repo"]) / "README.md").read_text(
        encoding="utf-8"
    )
    assert readme.startswith("# Finite-lattice witness (reviewed)\n")
    # The unedited sibling keeps its research-stage title.
    other = next(
        item
        for item in summary["solution_repositories"]
        if "reviewed" not in Path(item["solution_repo"]).name
    )
    other_readme = (Path(other["solution_repo"]) / "README.md").read_text(
        encoding="utf-8"
    )
    assert other_readme.startswith("# Critical-coupling interval\n")


def test_review_mechanical_field_drift_quarantines_candidate(
    tmp_path: Path,
) -> None:
    class TamperingRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "problem-reviewer":
                output = result.output
                if output["problem"]["title"] == "Finite-lattice witness":
                    output["problem"]["domain"] = "tampered-domain"
                    dump_json(kwargs["output_path"], output)
                    return AgentRun(output=output, metadata=result.metadata)
            return result

    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="review-mechanical-drift",
        agent_runner=TamperingRunner(),
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 1
    assert len(summary["failed_candidates"]) == 1
    failure = summary["failed_candidates"][0]
    assert "changed mechanical fields" in failure["error"]
    assert (
        pipeline.state["candidates"][failure["candidate_id"]]["status"]
        == "research_failed"
    )


def test_review_resolved_status_compiles_into_pool_resolved(
    tmp_path: Path,
) -> None:
    class ResolvingRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "problem-reviewer":
                output = result.output
                if output["problem"]["title"] == "Finite-lattice witness":
                    output["problem"]["status"] = "resolved-externally"
                    output["concerns"] = [
                        "Resolved externally: the witness construction was "
                        "published at https://example.test/proof "
                        "(DOI 10.0000/proof)."
                    ]
                    dump_json(kwargs["output_path"], output)
                    return AgentRun(output=output, metadata=result.metadata)
            return result

    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["outputs"]["pool_root"] = str(tmp_path / "pool-repo")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    pipeline = _start_pipeline(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="review-resolved-compile",
        agent_runner=ResolvingRunner(),
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 2
    pool = tmp_path / "pool-repo" / "pool"
    resolved_snapshots = sorted((pool / "resolved").glob("ORP-*.yaml"))
    active_snapshots = sorted((pool / "problems").glob("ORP-*.yaml"))
    assert len(resolved_snapshots) == 1
    assert len(active_snapshots) == 1
    snapshot = yaml.safe_load(resolved_snapshots[0].read_text(encoding="utf-8"))
    assert snapshot["status"] == "resolved-externally"
    assert snapshot["title"] == "Finite-lattice witness"
    catalog = [
        json.loads(line)
        for line in (pool / "catalog.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    resolved_record = next(
        record for record in catalog if record["status"] == "resolved-externally"
    )
    assert resolved_record["snapshot"] == f"resolved/{snapshot['problem_id']}.yaml"
    active_record = next(
        record for record in catalog if record["status"] != "resolved-externally"
    )
    assert active_record["snapshot"].startswith("problems/")
    stats = yaml.safe_load((pool / "stats.yaml").read_text(encoding="utf-8"))
    assert stats["resolved"] == 1
    assert stats["total"] == 2
    # The compiled README reflects the resolved status verbatim.
    resolved_repo = next(
        Path(item["solution_repo"])
        for item in summary["solution_repositories"]
        if item["problem_id"] == snapshot["problem_id"]
    )
    readme = (resolved_repo / "README.md").read_text(encoding="utf-8")
    assert "- Status: `resolved-externally`" in readme
    # Resolved records sort last and are annotated out of the active lane.
    ranking = json.loads(
        (pipeline.run_dir / "ranking.json").read_text(encoding="utf-8")
    )["ranking"]
    assert ranking[-1]["id"] == snapshot["problem_id"]
    assert ranking[-1]["ranking_lane"] == "resolved"
    assert ranking[0]["ranking_lane"] == "active"


def test_review_status_change_without_evidence_quarantines(
    tmp_path: Path,
) -> None:
    class SilentStatusRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "problem-reviewer":
                output = result.output
                if output["problem"]["title"] == "Finite-lattice witness":
                    output["problem"]["status"] = "resolved-externally"
                    output["problem"]["previous_progress"] = []
                    dump_json(kwargs["output_path"], output)
                    return AgentRun(output=output, metadata=result.metadata)
            return result

    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="review-status-no-evidence",
        agent_runner=SilentStatusRunner(),
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 1
    assert len(summary["failed_candidates"]) == 1
    failure = summary["failed_candidates"][0]
    assert "without citing evidence" in failure["error"]
    assert (
        pipeline.state["candidates"][failure["candidate_id"]]["status"]
        == "research_failed"
    )


def test_possible_bugs_precheck_reaches_review_workdir(tmp_path: Path) -> None:
    def fetch(kind: str, identifier: str) -> dict[str, Any]:
        if "later-status-review" in identifier:
            return {
                "identifier": identifier,
                "kind": kind,
                "fetched_at": "2026-08-17T00:00:00+00:00",
                "status": "found",
                "metadata": {
                    "title": "Completely unrelated work",
                    "authors": ["A. Writer"],
                    "venue": "",
                    "year": 2025,
                    "doi": "",
                    "url": identifier,
                },
                "detail": "",
            }
        return _unresolvable_fetch(kind, identifier)

    runner = TopicAgentRunner()
    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="possible-bugs-precheck",
        agent_runner=runner,
        citation_fetcher=fetch,
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 2
    for review_workdir in pipeline.run_dir.glob("candidates/*/review-workdir"):
        possible_bugs = review_workdir / "possible-bugs.md"
        assert possible_bugs.is_file()
        text = possible_bugs.read_text(encoding="utf-8")
        # The fetched title does not match the citation text.
        assert "`mismatch`" in text
        assert "Completely unrelated work" in text
        # previous_progress prose carries no identifier.
        assert "`no-identifier`" in text
        # The file stays in the review workdir and is not archived back.
        assert not (review_workdir.parent / "possible-bugs.md").exists()
    for prompt in runner.prompts["problem-reviewer"]:
        assert "possible-bugs.md" in prompt
        assert "deterministic pre-check" in prompt


def test_missing_research_notes_warns_without_failing(tmp_path: Path) -> None:
    runner = TopicAgentRunner()
    runner.write_notes = False
    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="missing-research-notes",
        agent_runner=runner,
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 2
    for events_path in pipeline.run_dir.glob("candidates/*/events/research.jsonl"):
        events = events_path.read_text(encoding="utf-8")
        assert "research-memory.md" in events
        assert '"warning"' in events


def test_missing_review_notes_warns_without_failing(tmp_path: Path) -> None:
    runner = TopicAgentRunner()
    runner.write_review_notes = False
    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="missing-review-notes",
        agent_runner=runner,
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 2
    for events_path in pipeline.run_dir.glob(
        "candidates/*/events/problem-review.jsonl"
    ):
        events = events_path.read_text(encoding="utf-8")
        assert "review-memory.md" in events
        assert '"warning"' in events
    # Nothing is archived back when the reviewer left no notes.
    assert not list(pipeline.run_dir.glob("candidates/*/review-memory.md"))


def test_topic_campaign_builds_one_solution_repo_per_problem_and_ignores_difficulty_cutoff(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    runner = TopicAgentRunner()
    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=repository_root,
        run_id="topic-run",
        agent_runner=runner,
    )

    summary = pipeline.run()

    assert summary["source_records"] == 2
    assert len(summary["accepted_problem_ids"]) == 2
    assert len(summary["solution_repositories"]) == 2
    assert summary["topic_groups"] == [
        {
            "topic_id": "hubbard",
            "problem_ids": summary["accepted_problem_ids"],
        }
    ]
    texts = []
    for item in summary["solution_repositories"]:
        assert item["topic_id"] == "hubbard"
        assert item["problem_id"] in summary["accepted_problem_ids"]
        repo = Path(item["solution_repo"])
        readme = repo / "README.md"
        assert validate_problem_readme(readme) == []
        assert sorted(path.name for path in repo.iterdir()) == [".git", "README.md"]
        text = readme.read_text(encoding="utf-8")
        texts.append(text)
        assert [
            line[3:] for line in text.splitlines() if line.startswith("## ")
        ] == list(README_SECTIONS)
        assert "The verification contract below evaluates answers" in text
        assert "Affected-field significance:" in text
    combined = "\n".join(texts)
    assert "finite-size artifact" in combined
    assert "Adjacent parameter regimes are known" in combined
    assert "Verification difficulty is `10/10`" in combined

    manifests = sorted(pipeline.run_dir.glob("candidates/*/problem.yaml"))
    assert len(manifests) == 2
    for manifest in manifests:
        assert (
            validate_problem(manifest, repository_root / "schemas/problem.schema.json")
            == []
        )
        problem = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        assert problem["repository"]["kind"] == "solution"
        matching = next(
            item
            for item in summary["solution_repositories"]
            if item["problem_id"] == problem["problem_id"]
        )
        assert problem["repository"]["slug"] == Path(
            matching["solution_repo"]
        ).name
    invalid_problem = yaml.safe_load(manifests[0].read_text(encoding="utf-8"))
    del invalid_problem["verification_contract"]
    invalid_manifest = tmp_path / "invalid-problem.yaml"
    invalid_manifest.write_text(
        yaml.safe_dump(invalid_problem, sort_keys=False), encoding="utf-8"
    )
    assert any(
        "verification_contract" in error
        for error in validate_problem(
            invalid_manifest, repository_root / "schemas/problem.schema.json"
        )
    )
    hardest = max(
        yaml.safe_load(path.read_text(encoding="utf-8"))["verification_difficulty"][
            "score"
        ]
        for path in manifests
    )
    assert hardest == 10
    ranking = json.loads(
        (pipeline.run_dir / "ranking.json").read_text(encoding="utf-8")
    )["ranking"]
    assert ranking[0]["significance_level"] == "high"
    assert ranking[0]["verification_difficulty"] == 10
    # Memory mechanism: the pipeline writes topic/candidate memory.md files,
    # every agent prompt opens with the read instruction (conditional for
    # Discovery, whose memory.md does not exist on a fresh run), and each
    # agent runs with its stage directory as cwd.
    for role, prompt_list in runner.prompts.items():
        for prompt in prompt_list:
            if role == "discovery":
                assert prompt.startswith("If ./memory.md exists, first read it")
            else:
                assert prompt.startswith(
                    "First read ./memory.md for full context."
                )
    domain_dir = pipeline.run_dir / "domains" / "hubbard"
    assert runner.cwds["discovery"][0] == domain_dir
    domain_memory = (domain_dir / "memory.md").read_text(encoding="utf-8")
    assert "## Discovery: source records" in domain_memory
    assert "lead:hubbard:book-target" in domain_memory
    for manifest in manifests:
        candidate_dir = manifest.parent
        memory = (candidate_dir / "memory.md").read_text(encoding="utf-8")
        assert [
            line for line in memory.splitlines() if line.startswith("## ")
        ] == [
            "## Source records",
            "## Discovery summary",
            "## Research audit",
            "## Problem review",
        ]
        assert (candidate_dir / "discovery.json").is_file()
        assert (candidate_dir / "lkm.json").is_file()
        assert "- Verdict: `accept`" in memory
        assert "lead:hubbard:" in memory
        assert "- Outcome: reviewed record adopted for compilation" in memory
        # The reviewer edits a copy of the candidate directory, not the
        # research originals.
        review_workdir = candidate_dir / "review-workdir"
        assert (review_workdir / "research.json").is_file()
        assert (review_workdir / "memory.md").is_file()
        assert (review_workdir / "research-memory.md").is_file()
        assert (review_workdir / "review-memory.md").is_file()
        assert not (review_workdir / "events").exists()
        assert not (review_workdir / "review-workdir").exists()
        assert (candidate_dir / "research-memory.md").is_file()
        # The reviewer's notes are archived back next to the research
        # originals.
        assert (candidate_dir / "review-memory.md").is_file()
    assert {path.name for path in runner.cwds["problem-reviewer"]} == {
        "review-workdir"
    }
    # The canonical memory chain (topic + candidate files); the workdir
    # copies are scratch and legitimately differ between a fresh run and a
    # cached resume, so they stay out of the identity check.
    memory_before = {
        path: path.read_text(encoding="utf-8")
        for path in pipeline.run_dir.glob("**/memory.md")
        if "workdir" not in str(path)
    }
    calls = list(runner.calls)
    assert pipeline.run() == summary
    assert runner.calls == calls
    # A cached resume rewrites every memory section idempotently.
    assert {
        path: path.read_text(encoding="utf-8")
        for path in pipeline.run_dir.glob("**/memory.md")
        if "workdir" not in str(path)
    } == memory_before
    assert "never add finite-size" in runner.prompts["discovery"][0].lower()
    assert "paper graph" in runner.prompts["discovery"][0].lower()
    assert "at most 10 selected items" in runner.prompts["discovery"][0].lower()
    assert "famous or named problem" in runner.prompts["research"][0].lower()
    assert "authoritative formulation" in runner.prompts["problem-reviewer"][
        0
    ].lower()
    # Jargon self-containment guidance
    research_prompt = runner.prompts["research"][0].lower()
    assert "neighboring subfield" in research_prompt
    assert "one-sentence definition" in research_prompt
    assert "undergraduate-level" in research_prompt
    # Citation format guidance
    assert "externally verifiable identifier" in research_prompt
    assert "never put an lkm internal node id" in research_prompt
    assert "every work cited by author name or paper title" in research_prompt


def test_campaign_init_writes_valid_multi_topic_config(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "multi-topic.yaml"

    assert (
        cli_main(
            [
                "campaign",
                "init",
                "--topic",
                "Hubbard Model",
                "--topic",
                "Quantum Hall Effect",
                "--source",
                "topic_search",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    config = yaml.safe_load(output.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(
            json.loads(
                (repository_root / "schemas/campaign.schema.json").read_text(
                    encoding="utf-8"
                )
            )
        ).iter_errors(config)
    )
    assert errors == []
    assert config["schema_version"] == 2
    assert [topic["id"] for topic in config["topics"]] == [
        "hubbard-model",
        "quantum-hall-effect",
    ]
    assert all(topic["sources"] == ["topic_search"] for topic in config["topics"])
    assert config["agents"]["workers"] == 32
    assert config["agents"]["networked_workers"] == 32
    assert "max_verification_difficulty" not in config["limits"]


def test_campaign_init_supports_chinese_only_topics(tmp_path: Path) -> None:
    output = tmp_path / "chinese-topics.yaml"
    titles = ["量子蒙特卡罗模拟中的负符号问题", "声逆散射问题"]

    assert (
        cli_main(
            [
                "campaign",
                "init",
                "--topic",
                titles[0],
                "--topic",
                titles[1],
                "--out",
                str(output),
            ]
        )
        == 0
    )
    config = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert [topic["id"] for topic in config["topics"]] == [
        "topic-" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
        for title in titles
    ]
    # Audit budget is unlimited by default; users opt in explicitly.
    assert "max_audited_candidates_per_topic" not in config["limits"]


def test_direct_lkm_records_keep_context_and_remain_topic_scoped(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["topics"] = [
        {
            "id": topic_id,
            "title": topic_id.title(),
            "query": f"Find scoped targets for {topic_id}.",
            "sources": ["lkm_open_questions"],
            "seed_papers": [],
            "seed_references": [],
        }
        for topic_id in ("alpha", "beta")
    ]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    def collector(
        *,
        paper_id: str | None = None,
        doi: str | None = None,
        title: str | None = None,
        raw_out: Path,
        out: Path,
        timeout: float,
    ) -> dict[str, Any]:
        assert paper_id in {"paper-alpha", "paper-beta"}
        assert doi is None and title is None and timeout == 30
        raw_out.parent.mkdir(parents=True, exist_ok=True)
        dump_json(raw_out, {"code": 0, "trace_id": "shared-trace"})
        payload = {
            "trace_id": "shared-trace",
            "count": 1,
            "open_questions": [
                {
                    "id": "shared::open_question",
                    "global_id": "shared-global-question",
                    "content": "Does the fixed model admit the requested exact construction?",
                    "paper_id": paper_id,
                    "paper_title": "A shared source paper",
                    "paper_doi": "10.0000/shared",
                }
            ],
        }
        dump_json(out, payload)
        return payload

    pipeline = _start_pipeline(
        config_path,
        repository_root=repository_root,
        run_id="topic-scoped-lkm",
        agent_runner=TopicAgentRunner(),
        paper_collector=collector,
    )
    discovered = {
        topic_id: {
            "schema_version": 2,
            "domain_id": topic_id,
            "topic_title": topic_id.title(),
            "source_modes": ["lkm_open_questions"],
            "papers": [
                    {
                        "paper_id": f"paper-{topic_id}",
                        "doi": "",
                        "title": "A shared source paper",
                        "selected_open_questions": [
                            {
                                "global_id": "shared-global-question",
                                "summary": "This exact construction question is a useful Research lead.",
                            }
                        ],
                    }
            ],
            "problem_summaries": [],
        }
        for topic_id in ("alpha", "beta")
    }

    all_records: list[dict[str, Any]] = []
    for topic_id, source in discovered.items():
        domain_dir = pipeline.run_dir / "domains" / topic_id
        output = pipeline._ingest_domain(
            source, topic_id, domain_dir, ["lkm_open_questions"]
        )
        all_records.extend(output.get("source_records") or output["open_questions"])
    records = CampaignPipeline._deduplicate_source_records(all_records)

    # The same LKM open question hit by two topics collapses into a single
    # question-level record keyed by lkm:<global_id>; the record keeps the
    # first configured topic as its owner and lists every topic that hit it.
    assert len(records) == 1
    record = records[0]
    assert record["source_key"] == "lkm:shared-global-question"
    assert record["topic_id"] == "alpha"
    assert record["topic_ids"] == ["alpha", "beta"]
    assert record["domain_ids"] == ["alpha", "beta"]
    assert "Paper context:" in record["surrounding_context"]
    assert record["exact_excerpt"] in record["surrounding_context"]
    assert not record["author_attribution_verified"]

    # The post-selection pass keeps the candidate from the earliest
    # configured topic and marks cross-topic duplicates without deleting them.
    def candidate(candidate_id: str, topic_id: str) -> dict[str, Any]:
        return {
            "candidate_id": candidate_id,
            "topic_id": topic_id,
            "canonical_title": candidate_id,
            "source_keys": ["lkm:shared-global-question"],
        }

    alpha_candidate = candidate("CAN-AAAAAAAAAAAA", "alpha")
    beta_candidate = candidate("CAN-BBBBBBBBBBBB", "beta")
    for item in (alpha_candidate, beta_candidate):
        pipeline.state.setdefault("candidates", {})[item["candidate_id"]] = {
            "status": "canonicalized"
        }

    kept = pipeline._deduplicate_cross_topic_lkm([beta_candidate, alpha_candidate])

    assert kept == [alpha_candidate]
    beta_state = pipeline.state["candidates"][beta_candidate["candidate_id"]]
    assert beta_state["status"] == "duplicate_cross_topic"
    assert beta_state["duplicate_of"] == alpha_candidate["candidate_id"]


def test_discovery_materialization_uses_source_topic_id(tmp_path: Path) -> None:
    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="discovery-topic-id",
        agent_runner=TopicAgentRunner(),
    )
    candidates = pipeline._materialize_discovery_candidates(pipeline._discover())

    # The pipeline takes topic ownership from the materialized source record,
    # not from a separate Selection agent.
    assert {candidate["topic_id"] for candidate in candidates} == {"hubbard"}


def test_campaign_init_defaults_to_twenty_discovery_candidates(tmp_path: Path) -> None:
    out = tmp_path / "campaign.yaml"
    assert cli_main(["campaign", "init", "--topic", "Hubbard model", "--out", str(out)]) == 0
    config = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert config["limits"] == {
        "questions_per_domain": 20,
        "lkm_timeout_seconds": 60,
    }


def test_discovery_rejects_summaries_for_disabled_source_mode(
    tmp_path: Path,
) -> None:
    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["topics"][0]["sources"] = ["lkm_open_questions"]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    pipeline = _start_pipeline(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="disabled-topic-search",
        agent_runner=TopicAgentRunner(),
    )

    with pytest.raises(CampaignError, match="disabled source mode"):
        pipeline._discover()


def test_topic_campaign_workers_four_stays_parallel_and_deterministic(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]

    def parallel_config(root: Path) -> Path:
        root.mkdir(parents=True)
        config_path = _config(root)
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["agents"]["workers"] = 4
        config_path.write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        return config_path

    class ParallelTopicAgentRunner(TopicAgentRunner):
        def __init__(self) -> None:
            super().__init__()
            self.research_barrier = threading.Barrier(2)
            self.research_lock = threading.Lock()
            self.active_research = 0
            self.max_active_research = 0

        def run(self, **kwargs: Any) -> AgentRun:
            if kwargs["role"] != "research":
                return super().run(**kwargs)
            with self.research_lock:
                self.active_research += 1
                self.max_active_research = max(
                    self.max_active_research, self.active_research
                )
            try:
                # Both candidate audits must be in flight at the same time.
                self.research_barrier.wait(timeout=10)
                return super().run(**kwargs)
            finally:
                with self.research_lock:
                    self.active_research -= 1

    def run_campaign(
        root: Path, runner: TopicAgentRunner
    ) -> tuple[dict[str, Any], dict[str, str]]:
        pipeline = _start_pipeline(
            parallel_config(root),
            repository_root=repository_root,
            run_id="topic-parallel",
            agent_runner=runner,
        )
        summary = pipeline.run()
        ids_by_title = {}
        for manifest in pipeline.run_dir.glob("candidates/*/problem.yaml"):
            problem = yaml.safe_load(manifest.read_text(encoding="utf-8"))
            ids_by_title[problem["title"]] = problem["problem_id"]
        return summary, ids_by_title

    first_runner = ParallelTopicAgentRunner()
    first_summary, first_ids = run_campaign(tmp_path / "first", first_runner)
    second_summary, second_ids = run_campaign(
        tmp_path / "second", ParallelTopicAgentRunner()
    )

    assert first_runner.max_active_research == 2
    assert first_summary["accepted_problem_ids"] == ["ORP-0001", "ORP-0002"]
    # problem_id assignment follows the canonical candidate order, not the
    # completion order of the parallel workers.
    assert first_ids == second_ids
    first_rendered = json.dumps(first_summary, sort_keys=True).replace(
        str(tmp_path / "first"), "<ROOT>"
    )
    second_rendered = json.dumps(second_summary, sort_keys=True).replace(
        str(tmp_path / "second"), "<ROOT>"
    )
    assert first_rendered == second_rendered


def _lkm_config(
    tmp_path: Path, seed_papers: dict[str, list[dict[str, Any]]] | None = None
) -> Path:
    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["topics"] = [
        {
            "id": topic_id,
            "title": topic_id.title(),
            "query": f"Find scoped targets for {topic_id}.",
            "sources": ["lkm_open_questions"],
            "seed_papers": list((seed_papers or {}).get(topic_id, [])),
            "seed_references": [],
        }
        for topic_id in ("alpha", "beta")
    ]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def _lkm_paper(paper_id: str) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "doi": "",
        "title": f"Paper {paper_id}",
    }


class LkmDiscoveryRunner:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
        cwd: Path | None = None,
    ) -> AgentRun:
        assert role == "discovery"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(json.dumps({"role": role}) + "\n", encoding="utf-8")
        self.prompts.append(prompt)
        domain_id = "alpha" if "Domain id: alpha" in prompt else "beta"
        output = {
            "domain_id": domain_id,
            "selected_open_questions": [
                {
                    **_lkm_paper(f"agent-{domain_id}"),
                    "global_id": f"agent-question-{domain_id}",
                    "summary": "The LKM record is a bounded research lead worth a status audit.",
                }
            ],
            "problem_summaries": [],
        }
        dump_json(output_path, output)
        return AgentRun(output=output, metadata={"exit_code": 0, "role": role})


def test_discovery_has_no_second_programmatic_lkm_sweep(tmp_path: Path) -> None:
    runner = LkmDiscoveryRunner()
    pipeline = _start_pipeline(
        _lkm_config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="one-discovery-call",
        agent_runner=runner,
        paper_collector=None,
    )
    pipeline._ingest_domain = lambda *a, **k: {  # type: ignore[method-assign]
        "source_records": [],
        "open_questions": [],
    }

    assert pipeline._discover() == []
    assert len(runner.prompts) == 2


def test_cross_topic_lkm_dedup_marks_duplicates_and_writes_artifact(
    tmp_path: Path,
) -> None:
    pipeline = _start_pipeline(
        _lkm_config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="cross-topic-dedup",
        agent_runner=LkmDiscoveryRunner(),
        paper_collector=None,
    )

    def candidate(candidate_id: str, topic_id: str) -> dict[str, Any]:
        return {
            "candidate_id": candidate_id,
            "topic_id": topic_id,
            "canonical_title": candidate_id,
            "source_keys": ["lkm:shared-global-question"],
        }

    alpha_first = candidate("CAN-AAAAAAAAAAAA", "alpha")
    alpha_second = candidate("CAN-BBBBBBBBBBBB", "alpha")
    beta_dup = candidate("CAN-CCCCCCCCCCCC", "beta")
    for item in (alpha_first, alpha_second, beta_dup):
        pipeline.state.setdefault("candidates", {})[item["candidate_id"]] = {
            "status": "canonicalized"
        }

    kept = pipeline._deduplicate_cross_topic_lkm([beta_dup, alpha_second, alpha_first])

    # Same-topic candidates sharing a key both survive; the cross-topic
    # duplicate collapses to the candidate from the earliest configured topic.
    assert kept == [alpha_second, alpha_first]
    state = pipeline.state["candidates"][beta_dup["candidate_id"]]
    assert state["status"] == "duplicate_cross_topic"
    assert state["duplicate_of"] == "CAN-AAAAAAAAAAAA"
    assert state["shared_lkm_source_key"] == "lkm:shared-global-question"
    assert alpha_first["shared_topic_ids"] == ["alpha", "beta"]
    assert "shared_topic_ids" not in alpha_second
    artifact = json.loads(
        (pipeline.run_dir / "cross-topic-dedup.json").read_text(encoding="utf-8")
    )
    assert artifact["duplicates"] == [
        {
            "candidate_id": "CAN-CCCCCCCCCCCC",
            "topic_id": "beta",
            "duplicate_of": "CAN-AAAAAAAAAAAA",
            "kept_topic_id": "alpha",
            "source_key": "lkm:shared-global-question",
        }
    ]


def test_discovery_candidates_all_reach_research(
    tmp_path: Path,
) -> None:
    runner = TopicAgentRunner()
    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="all-discovery-candidates",
        agent_runner=runner,
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 2
    assert runner.calls.count("research") == 2
    assert "selection" not in runner.calls


def test_quarantined_candidate_recovers_on_resume(tmp_path: Path) -> None:
    """A research-stage failure quarantines the candidate; resume re-runs it."""

    class FlakyResearchRunner(TopicAgentRunner):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def run(self, **kwargs: Any) -> AgentRun:
            if kwargs["role"] == "research" and self.fail:
                memory = (kwargs["cwd"] / "memory.md").read_text(
                    encoding="utf-8"
                )
                if "Determine whether the finite lattice admits the stated witness" in memory:
                    self.calls.append("research")
                    raise AgentExecutionError("transport unavailable")
            return super().run(**kwargs)

    runner = FlakyResearchRunner()
    pipeline = _start_pipeline(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="quarantine-resume",
        agent_runner=runner,
    )

    summary = pipeline.run()
    assert len(summary["accepted_problem_ids"]) == 1
    assert len(summary["failed_candidates"]) == 1
    failed_id = summary["failed_candidates"][0]["candidate_id"]
    assert pipeline.state["candidates"][failed_id]["status"] == "research_failed"

    # The failed stage has no ledger cache, so a plain resume re-runs it; the
    # already-accepted sibling stays fully cached.
    runner.fail = False
    summary = pipeline.run()
    assert len(summary["accepted_problem_ids"]) == 2
    assert summary["failed_candidates"] == []
    assert pipeline.state["candidates"][failed_id]["status"] == "accepted"
