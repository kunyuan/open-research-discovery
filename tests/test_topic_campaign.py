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


def _lead(
    lead_id: str,
    title: str,
    excerpt: str,
    question: str,
    kind: str,
) -> dict[str, Any]:
    context = f"The source first fixes the model and observable. {excerpt} It excludes adjacent regimes."
    return {
        "lead_id": lead_id,
        "proposed_question": question,
        "source": {
            "kind": kind,
            "title": title,
            "identifier": lead_id,
            "url": "https://example.test/" + lead_id,
            "locator": "Chapter 4" if kind == "book" else "Section 3",
            "date": "2024",
        },
        "exact_excerpt": excerpt,
        "surrounding_context": context,
        "source_intent": "The author isolates one unresolved finite-regime target.",
        "derivation_rationale": (
            "The proposed question preserves the stated model, observable, and regime."
        ),
        "evidence": [
            {
                "source": kind,
                "identifier": lead_id,
                "url": "https://example.test/" + lead_id,
                "content_level": "partial_full_text",
                "supports": "The exact target and its local scope.",
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
        "source_support": [
            {
                "source_key": source_key,
                "exact_excerpt": statement,
            }
        ],
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
                "papers": [],
                "problem_leads": [
                    _lead(
                        "book-target",
                        "《10000个科学难题》物理学卷",
                        "Determine whether the finite lattice admits the stated witness.",
                        "Does the finite lattice admit the stated witness?",
                        "book",
                    ),
                    _lead(
                        "web-target",
                        "Finite-size transition bounds",
                        "Establish or refute the stated critical-coupling interval.",
                        "Can the stated critical-coupling interval be established or refuted?",
                        "web",
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
            finite = "Finite-lattice witness" in memory
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
            "papers_per_domain": 2,
            "questions_per_domain": 10,
            "leads_per_topic": 10,
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


def test_publication_gate_requires_accept_and_open_outcome() -> None:
    pipeline = object.__new__(CampaignPipeline)
    open_draft = {"status": "open"}
    accept = {"verdict": "accept"}
    # Positive control: an open, schema-validated draft with an accepting
    # verdict passes the gate.
    assert pipeline._passes_publication_gate(open_draft, accept)
    assert not pipeline._passes_publication_gate(open_draft, {"verdict": "reject"})
    assert not pipeline._passes_publication_gate(open_draft, None)
    assert not pipeline._passes_publication_gate(
        {"status": "resolved-externally"}, accept
    )


def test_reviewer_reject_is_terminal(tmp_path: Path) -> None:
    class RejectRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "problem-reviewer":
                memory = (kwargs["cwd"] / "memory.md").read_text(
                    encoding="utf-8"
                )
                if "Finite-lattice witness" in memory:
                    output = {
                        **result.output,
                        "verdict": "reject",
                        "concerns": ["The status evidence is insufficient."],
                    }
                    dump_json(kwargs["output_path"], output)
                    return AgentRun(output=output, metadata=result.metadata)
            return result

    pipeline = CampaignPipeline.start(
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

    pipeline = CampaignPipeline.start(
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

    pipeline = CampaignPipeline.start(
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


def test_missing_research_notes_warns_without_failing(tmp_path: Path) -> None:
    runner = TopicAgentRunner()
    runner.write_notes = False
    pipeline = CampaignPipeline.start(
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


def test_topic_campaign_builds_one_solution_repo_per_problem_and_ignores_difficulty_cutoff(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    runner = TopicAgentRunner()
    pipeline = CampaignPipeline.start(
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
    # every agent prompt opens with the read instruction, and each agent runs
    # with its stage directory as cwd.
    for prompt_list in runner.prompts.values():
        for prompt in prompt_list:
            assert prompt.startswith("First read ./memory.md for full context.")
    domain_dir = pipeline.run_dir / "domains" / "hubbard"
    assert runner.cwds["discovery"][0] == domain_dir
    assert runner.cwds["selection"][0] == domain_dir
    domain_memory = (domain_dir / "memory.md").read_text(encoding="utf-8")
    assert "## Discovery: source records" in domain_memory
    assert "## Selection: routing" in domain_memory
    assert "lead:hubbard:book-target" in domain_memory
    for manifest in manifests:
        candidate_dir = manifest.parent
        memory = (candidate_dir / "memory.md").read_text(encoding="utf-8")
        assert [
            line for line in memory.splitlines() if line.startswith("## ")
        ] == [
            "## Source records",
            "## Selection routing",
            "## Research audit",
            "## Problem review",
        ]
        assert "- Verdict: `accept`" in memory
        assert "lead:hubbard:" in memory
        assert "- Outcome: reviewed record adopted for compilation" in memory
        # The reviewer edits a copy of the candidate directory, not the
        # research originals.
        review_workdir = candidate_dir / "review-workdir"
        assert (review_workdir / "research.json").is_file()
        assert (review_workdir / "memory.md").is_file()
        assert (review_workdir / "research-memory.md").is_file()
        assert not (review_workdir / "events").exists()
        assert not (review_workdir / "review-workdir").exists()
        assert (candidate_dir / "research-memory.md").is_file()
    assert {path.name for path in runner.cwds["problem-reviewer"]} == {
        "review-workdir"
    }
    memory_before = {
        path: path.read_text(encoding="utf-8")
        for path in pipeline.run_dir.glob("**/memory.md")
    }
    calls = list(runner.calls)
    assert pipeline.run() == summary
    assert runner.calls == calls
    # A cached resume rewrites every memory section idempotently.
    assert {
        path: path.read_text(encoding="utf-8")
        for path in pipeline.run_dir.glob("**/memory.md")
    } == memory_before
    assert "never add finite-size" in runner.prompts["discovery"][0].lower()
    assert "famous or standard open problem" in runner.prompts["selection"][0].lower()
    assert "must not narrow or redefine" in runner.prompts["selection"][0].lower()
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

    pipeline = CampaignPipeline.start(
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
                    "context_summary": (
                        "The paper fixes one finite model, its exact conventions, and "
                        "the construction whose existence remains unresolved."
                    ),
                    "source_intent": (
                        "The authors isolate the construction as a bounded open target."
                    ),
                    "evidence": [
                        {
                            "source": "lkm",
                            "identifier": f"paper-{topic_id}",
                            "url": "",
                            "content_level": "abstract",
                            "supports": "The model, conventions, and unresolved target.",
                        }
                    ],
                }
            ],
            "problem_leads": [],
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


def test_topic_discovery_rejects_out_of_context_excerpt(tmp_path: Path) -> None:
    class BadExcerptRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] != "discovery":
                return result
            output = result.output
            output["problem_leads"][0]["exact_excerpt"] = (
                "A sentence absent from context."
            )
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="bad-context",
        agent_runner=BadExcerptRunner(),
    )

    with pytest.raises(CampaignError, match="exact substring"):
        pipeline._discover()
    assert (
        pipeline.state["stages"]["campaign.discovery.hubbard"]["status"]
        == "failed"
    )


def test_selection_injects_topic_id_and_excerpt_repair_is_audited(
    tmp_path: Path,
) -> None:
    class CapitalizingRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "selection":
                support = result.output["candidates"][0]["source_support"][0]
                support["exact_excerpt"] = (
                    "determine whether the finite lattice admits the stated witness."
                )
                dump_json(kwargs["output_path"], result.output)
            return result

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="selection-excerpt-repair",
        agent_runner=CapitalizingRunner(),
    )
    candidates = pipeline._select(pipeline._discover())

    # The per-topic call owns the topic: topic_id is injected by the pipeline,
    # never chosen by the agent.
    assert {candidate["topic_id"] for candidate in candidates} == {"hubbard"}
    mutated = next(
        candidate
        for candidate in candidates
        if candidate["canonical_title"] == "Finite-lattice witness"
    )
    assert mutated["source_support"][0]["exact_excerpt"] == (
        "Determine whether the finite lattice admits the stated witness."
    )
    repairs = json.loads(
        (pipeline.run_dir / "selection-repairs.json").read_text(
            encoding="utf-8"
        )
    )["repairs"]
    assert len(repairs) == 1
    assert repairs[0]["source_key"] == "lead:hubbard:book-target"
    assert repairs[0]["original_excerpt"] == (
        "determine whether the finite lattice admits the stated witness."
    )
    assert repairs[0]["repaired_excerpt"] == (
        "Determine whether the finite lattice admits the stated witness."
    )


def test_audit_budget_caps_audits_per_topic(tmp_path: Path) -> None:
    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["limits"]["max_audited_candidates_per_topic"] = 1
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    runner = TopicAgentRunner()
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="audit-budget-cap",
        agent_runner=runner,
    )

    summary = pipeline.run()

    # Selection selected both candidates; the per-topic audit budget admits
    # only the high-importance one and defers the medium one.
    assert summary["canonical_candidates"] == 2
    assert summary["active_candidates"] == 2
    assert summary["audit_budget_deferred_count"] == 1
    assert summary["selection_deferred_count"] == 0
    assert len(summary["accepted_problem_ids"]) == 1
    assert runner.calls.count("selection") == 1
    assert runner.calls.count("research") == 1
    assert runner.calls.count("problem-reviewer") == 1
    deferred_state = next(
        state
        for state in pipeline.state["candidates"].values()
        if state["status"] == "audit_budget_deferred"
    )
    assert deferred_state["canonical_title"] == "Critical-coupling interval"


def test_direct_lkm_discovery_rejects_metadata_only_context(tmp_path: Path) -> None:
    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["topics"][0]["sources"] = ["lkm_open_questions"]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    class MetadataRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            assert kwargs["role"] == "discovery"
            output = {
                "domain_id": "hubbard",
                "papers": [
                    {
                        "paper_id": "metadata-paper",
                        "doi": "",
                        "title": "Metadata-only paper",
                        "context_summary": (
                            "This nominal summary cannot be trusted because no "
                            "content-level evidence beyond metadata was inspected."
                        ),
                        "source_intent": (
                            "The purported intent is not content-grounded."
                        ),
                        "evidence": [
                            {
                                "source": "lkm",
                                "identifier": "metadata-paper",
                                "url": "",
                                "content_level": "metadata",
                                "supports": "Paper identity only.",
                            }
                        ],
                    }
                ],
                "problem_leads": [],
            }
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata={"exit_code": 0})

    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="metadata-context",
        agent_runner=MetadataRunner(),
    )

    with pytest.raises(CampaignError, match="abstract-level"):
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
        pipeline = CampaignPipeline.start(
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
        "context_summary": (
            "The paper fixes one finite model, its exact conventions, and the "
            "construction whose existence remains unresolved."
        ),
        "source_intent": "The authors isolate the construction as a bounded open target.",
        "evidence": [
            {
                "source": "lkm",
                "identifier": paper_id,
                "url": "",
                "content_level": "abstract",
                "supports": "The model, conventions, and unresolved target.",
            }
        ],
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
            "papers": [_lkm_paper(f"agent-{domain_id}")],
            "problem_leads": [],
        }
        dump_json(output_path, output)
        return AgentRun(output=output, metadata={"exit_code": 0, "role": role})


def test_lkm_sweep_failure_is_nonfatal_and_leaves_error_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("gaia executable missing")

    monkeypatch.setattr(campaign_mod, "run_gaia_knowledge", boom)
    pipeline = CampaignPipeline.start(
        _lkm_config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="sweep-fail",
        agent_runner=LkmDiscoveryRunner(),
        paper_collector=None,
    )
    pipeline._ingest_domain = lambda *a, **k: {  # type: ignore[method-assign]
        "source_records": [],
        "open_questions": [],
    }

    records = pipeline._discover()

    assert records == []
    artifact = json.loads(
        (pipeline.run_dir / "domains" / "alpha" / "lkm-sweep.json").read_text(
            encoding="utf-8"
        )
    )
    assert artifact["status"] == "failed"
    assert "FileNotFoundError" in artifact["error"]
    assert artifact["query"] == "Find scoped targets for alpha."
    # The agent-driven discovery route still produced its papers.
    source = json.loads(
        (pipeline.run_dir / "domains" / "alpha" / "source-papers.json").read_text(
            encoding="utf-8"
        )
    )
    assert [paper["paper_id"] for paper in source["papers"]] == ["agent-alpha"]


def test_lkm_sweep_merges_seed_sweep_agent_papers_in_priority_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_sweep(query: str, out_path: Path, **kwargs: Any) -> dict[str, Any]:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "trace_id": "sweep-trace",
            "data": {
                "variables": [
                    {"id": "v1", "provenance": {"source_packages": ["pkg-1"]}},
                    {"id": "v2", "provenance": {"source_packages": ["pkg-2"]}},
                ],
                "papers": {
                    "pkg-1": {"id": "sweep-1", "doi": "10.1/a", "title": "Sweep One"},
                    "pkg-2": {"id": "sweep-2", "doi": "", "title": "Sweep Two"},
                },
            },
        }
        dump_json(out_path, payload)
        return payload

    monkeypatch.setattr(campaign_mod, "run_gaia_knowledge", fake_sweep)
    config_path = _lkm_config(
        tmp_path,
        seed_papers={"alpha": [{"paper_id": "seed-alpha", "doi": "", "title": ""}]},
    )
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="sweep-order",
        agent_runner=LkmDiscoveryRunner(),
        paper_collector=None,
    )
    pipeline._ingest_domain = lambda *a, **k: {  # type: ignore[method-assign]
        "source_records": [],
        "open_questions": [],
    }

    pipeline._discover()

    # Merge order is seed -> sweep -> agent and papers_per_domain=2 caps the
    # merged total, so sweep hits outrank the agent's adaptive papers.
    alpha_source = json.loads(
        (pipeline.run_dir / "domains" / "alpha" / "source-papers.json").read_text(
            encoding="utf-8"
        )
    )
    beta_source = json.loads(
        (pipeline.run_dir / "domains" / "beta" / "source-papers.json").read_text(
            encoding="utf-8"
        )
    )
    assert [paper["paper_id"] for paper in alpha_source["papers"]] == [
        "seed-alpha",
        "sweep-1",
    ]
    assert [paper["paper_id"] for paper in beta_source["papers"]] == [
        "sweep-1",
        "sweep-2",
    ]
    artifact = json.loads(
        (pipeline.run_dir / "domains" / "beta" / "lkm-sweep.json").read_text(
            encoding="utf-8"
        )
    )
    assert artifact["status"] == "ok"
    assert artifact["hit_count"] == 2
    assert artifact["paper_count"] == 2
    assert artifact["trace_id"] == "sweep-trace"


def test_cross_topic_lkm_dedup_marks_duplicates_and_writes_artifact(
    tmp_path: Path,
) -> None:
    pipeline = CampaignPipeline.start(
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


class LowImportanceSelectionRunner(TopicAgentRunner):
    """Selection marks every candidate low importance."""

    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        output = result.output
        if kwargs["role"] == "selection":
            for entry in output["candidates"]:
                entry["importance_level"] = "low"
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)
        return result


def test_low_importance_selection_defers_candidate(
    tmp_path: Path,
) -> None:
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="run-low-importance",
        agent_runner=LowImportanceSelectionRunner(),
    )

    summary = pipeline.run()

    # A low-importance selection is archived in place: the candidate defers
    # and nothing reaches the audit.
    for state in pipeline.state["candidates"].values():
        assert state["status"] == "selection_deferred"
    assert summary["selection_deferred_count"] == 2
    assert summary["accepted_problem_ids"] == []


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
                if "Finite-lattice witness" in memory:
                    self.calls.append("research")
                    raise AgentExecutionError("transport unavailable")
            return super().run(**kwargs)

    runner = FlakyResearchRunner()
    pipeline = CampaignPipeline.start(
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
