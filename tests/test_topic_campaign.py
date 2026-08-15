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
    _load_topic_queue,
    is_refinable,
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
        "answer_types": ["proof", "counterexample", "certified numerical bound"],
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


class TopicAgentRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.prompts: dict[str, list[str]] = {}

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
        self.prompts.setdefault(role, []).append(prompt)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(json.dumps({"role": role}) + "\n", encoding="utf-8")
        if role == "discovery":
            output = {
                "domain_id": "hubbard",
                "search_summary": "Inspected a reference chapter and a scoped web source.",
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
        elif role == "canonicalization":
            output = {
                "clusters": [
                    {
                        "topic_id": "hubbard",
                        "parent_theme": "Finite Hubbard-model questions",
                        "canonical_title": "Finite-lattice witness",
                        "canonical_statement": "Determine whether the finite lattice admits the stated witness.",
                        "scope": "The finite model and regime stated in the source.",
                        "named_problem": False,
                        "authoritative_formulation": None,
                        "formulation_alignment": "not_applicable",
                        "domain": "physics",
                        "source_keys": ["lead:hubbard:book-target"],
                        "source_support": [
                            {
                                "source_key": "lead:hubbard:book-target",
                                "exact_excerpt": "Determine whether the finite lattice admits the stated witness.",
                            }
                        ],
                        "aliases": [],
                        "answer_types": ["proof", "counterexample"],
                        "verification_plan": "Check the theorem or witness against the fixed finite model.",
                        "decomposition_rationale": "This is one finite acceptance target.",
                        "rationale": "The reference asks exactly this scoped question.",
                    },
                    {
                        "topic_id": "hubbard",
                        "parent_theme": "Finite Hubbard-model questions",
                        "canonical_title": "Critical-coupling interval",
                        "canonical_statement": "Establish or refute the stated critical-coupling interval.",
                        "scope": "The interval and model stated in the source.",
                        "named_problem": False,
                        "authoritative_formulation": None,
                        "formulation_alignment": "not_applicable",
                        "domain": "physics",
                        "source_keys": ["lead:hubbard:web-target"],
                        "source_support": [
                            {
                                "source_key": "lead:hubbard:web-target",
                                "exact_excerpt": "Establish or refute the stated critical-coupling interval.",
                            }
                        ],
                        "aliases": [],
                        "answer_types": ["proof", "certified numerical bound"],
                        "verification_plan": "Reproduce the certified bounds under the fixed protocol.",
                        "decomposition_rationale": "The parameter interval and pass condition are fixed.",
                        "rationale": "The contextual source supplies the interval and scope.",
                    },
                ]
            }
        else:
            match = re.search(r"CAN-[A-F0-9]{12}", prompt)
            assert match is not None
            candidate_id = match.group(0)
            finite = "Finite-lattice witness" in prompt
            if role == "triage":
                output = {
                    "candidate_id": candidate_id,
                    "importance_level": "high" if finite else "medium",
                    "verification_clarity": "clear",
                    "decomposition_parent_coverage": "not_applicable",
                    "proposed_subproblems": [],
                    "assessment": (
                        "It tests a concrete boundary of the model; a resolution would separate a "
                        "genuine finite-size mechanism from an artifact. The acceptance condition is "
                        "an independently replayable check of every stated assumption and decisive step."
                    ),
                }
            elif role == "research" or role == "refine":
                output = _assessment(candidate_id, finite=finite)
            elif role == "problem-reviewer":
                output = {
                    "candidate_id": candidate_id,
                    "verdict": "accept",
                    "source_fidelity": "pass",
                    "scope_change": "not_applicable",
                    "authoritative_alignment": "not_applicable",
                    "concerns": [],
                    "revision_instructions": [],
                    "rationale": "The source context and acceptance standard are explicit.",
                }
            else:
                raise AssertionError(role)
        dump_json(output_path, output)
        return AgentRun(
            output=output,
            metadata={"exit_code": 0, "role": role, "schema": str(schema_path)},
        )


class MutableReviewTopicAgentRunner(TopicAgentRunner):
    def __init__(self) -> None:
        super().__init__()
        self.review_verdict = "accept"
        self.retitle_research = False

    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        output = result.output
        if kwargs["role"] == "problem-reviewer" and self.review_verdict != "accept":
            output = {
                **output,
                "verdict": self.review_verdict,
                "concerns": ["The status evidence needs another review."],
                "revision_instructions": ["Re-audit the same-core citation chain."],
                "rationale": "The refreshed review no longer supports publication.",
            }
        elif kwargs["role"] == "problem-reviewer" and self.retitle_research:
            output = {**output, "scope_change": "pass"}
        elif kwargs["role"] == "research" and self.retitle_research:
            problem = output["problem"]
            problem["title"] = problem["title"] + " corrected"
            problem["resolution_audit"]["progress_assessment"] = {
                "major_progress_found": True,
                "effect": "reframes",
            }
        dump_json(kwargs["output_path"], output)
        return AgentRun(output=output, metadata=result.metadata)


def _assessment(candidate_id: str, *, finite: bool) -> dict[str, Any]:
    """Nested Research draft matching schemas/stages/research-topic.schema.json.

    The mechanical fields (progress decision, formulation diff, reassessment
    flags) are injected by the pipeline in ``_finalize_research_output`` and
    deliberately do not appear here.
    """

    title = "Finite-lattice witness" if finite else "Critical-coupling interval"
    statement = (
        "Determine whether the finite lattice admits the stated witness."
        if finite
        else "Establish or refute the stated critical-coupling interval."
    )
    return {
        "candidate_id": candidate_id,
        "problem": {
            "title": title,
            "question": {
                "canonical_statement": statement,
                "definitions": [
                    "The source fixes the finite model, observable, and parameter regime."
                ],
                "scope": (
                    "The finite model and regime stated in the source."
                    if finite
                    else "The interval and model stated in the source."
                ),
                "aliases": [],
                "named_problem": False,
                "authoritative_formulation": None,
                "formulation_alignment": "not_applicable",
            },
            "resolution_audit": {
                "status": "still_open",
                "coverage": "systematic_literature",
                "conclusion": {
                    "label": "likely_open",
                    "confidence": "medium",
                },
                "checked_through": "2026-08-01",
                "surviving_open_core": statement,
                "evidence": [
                    {
                        "source": "web",
                        "title": "Later status review",
                        "identifier": "later-status-review",
                        "url": "https://example.test/later-status-review",
                        "date": "2025",
                        "content_level": "partial_full_text",
                        "relation": "continuing_open",
                        "supports": "The same finite target remains untreated after adjacent results.",
                        "direct_support": True,
                    }
                ],
                "progress_assessment": {
                    "major_progress_found": False,
                    "effect": "none",
                },
            },
            "importance": {
                "motivation": "The result would settle a concrete model boundary.",
                "consequences_of_progress": "It would sharpen subsequent analytical and numerical work.",
                "current_best_result": "Adjacent parameter regimes are known, but this target is not.",
            },
            "research_triage": {
                "importance_level": "high" if finite else "medium",
                "rationale": "The audited target remains a concrete, high-value model boundary.",
                "scientific_significance_score": 9 if finite else 7,
                "scientific_significance_rationale": (
                    "It would distinguish a physical mechanism from a finite-size artifact."
                ),
            },
            "discovery_contract": {
                "expected_result": "A proof, counterexample, or certified numerical bound.",
                "answer_types": (
                    ["proof", "counterexample"]
                    if finite
                    else ["proof", "certified numerical bound"]
                ),
            },
            "solution_review_contract": {
                "verification_difficulty": 10 if finite else 4,
                "rationale": "The score measures residual reviewer burden.",
                "verification_clarity": "clear",
                "verification_standard": (
                    "Accept only after an independent reviewer checks the fixed assumptions, "
                    "replays the decisive calculation, and confirms the claimed conclusion."
                ),
                "checklist": (
                    "Confirm the submitted result uses the fixed source model and regime. "
                    "Replay every decisive derivation or certified calculation. "
                    "Confirm the conclusion exactly answers the canonical statement."
                ),
                "estimated_review_time": "one expert day",
                "acceptance_boundary": "Adjacent regimes or qualitative phase diagrams do not pass.",
            },
            "ci_contract": {
                "status": "solution-reviewer-only",
                "workflow": None,
                "driver": None,
                "pseudocode": None,
                "runner": None,
                "estimated_runtime": None,
                "timeout_minutes": None,
            },
            "compute": {
                "expected_scale": "one finite target",
                "cpu": "problem dependent",
                "gpu": "optional",
                "notes": "Verification may combine expert derivation review and deterministic replay.",
            },
        },
        "report_markdown": (
            "## Audit report\n\n"
            "The audited literature leaves this scoped target unresolved. "
            "Later work treats adjacent regimes but not this exact target."
        ),
        "decomposition_parent_coverage": "not_applicable",
        "proposed_subproblems": [],
        "estimated_solution_scale": "single-paper",
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
                "repo_slug": "hubbard-open-problems",
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
            "max_verification_difficulty": 0,
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


@pytest.mark.parametrize(
    "invalid_evidence",
    [
        [
            {
                "source": "web",
                "title": "Metadata hit",
                "identifier": "metadata-hit",
                "url": "",
                "date": "2026",
                "content_level": "metadata",
                "relation": "continuing_open",
                "supports": "Only bibliographic metadata was inspected.",
                "direct_support": True,
            }
        ],
        [
            {
                "source": "web",
                "title": "Adjacent result",
                "identifier": "adjacent-result",
                "url": "https://example.test/adjacent-result",
                "date": "2026",
                "content_level": "full_text",
                "relation": "adjacent_only",
                "supports": "This result concerns a neighboring target.",
                "direct_support": True,
            }
        ],
        [
            {
                "source": "web",
                "title": "Indirect review",
                "identifier": "indirect-review",
                "url": "",
                "date": "2026",
                "content_level": "full_text",
                "relation": "continuing_open",
                "supports": "The source does not directly treat the target.",
                "direct_support": False,
            }
        ],
    ],
)
def test_topic_assessment_requires_traceable_direct_status_evidence(
    tmp_path: Path,
    invalid_evidence: list[dict[str, Any]],
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (repository_root / "schemas/stages/research-topic.schema.json").read_text(
            encoding="utf-8"
        )
    )
    valid = _assessment("CAN-000000000001", finite=True)
    assert list(Draft202012Validator(schema).iter_errors(valid)) == []

    # The stage schema deliberately accepts these records; the conditional
    # traceability rule is enforced by the publication gate, not the schema.
    invalid = copy.deepcopy(valid)
    invalid["problem"]["resolution_audit"]["evidence"] = invalid_evidence
    assert list(Draft202012Validator(schema).iter_errors(invalid)) == []

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=repository_root,
        run_id="evidence-gate",
        agent_runner=TopicAgentRunner(),
    )
    verdict = {
        "candidate_id": "CAN-000000000001",
        "verdict": "accept",
        "source_fidelity": "pass",
        "scope_change": "not_applicable",
        "authoritative_alignment": "not_applicable",
        "concerns": [],
        "revision_instructions": [],
        "rationale": "The source context and acceptance standard are explicit.",
    }
    # The pipeline injects the mechanical progress decision and formulation
    # diff after schema validation; mirror that before exercising the gate.
    candidate = {
        "canonical_title": "Finite-lattice witness",
        "canonical_statement": (
            "Determine whether the finite lattice admits the stated witness."
        ),
        "scope": "The finite model and regime stated in the source.",
        "named_problem": False,
        "answer_types": ["proof", "counterexample"],
    }
    triage: dict[str, Any] = {}
    for draft in (valid, invalid):
        CampaignPipeline._finalize_research_output(candidate, draft)
    # Positive control: a valid assessment with an accepting verdict passes.
    assert pipeline._passes_publication_gate(valid, verdict)
    # Schema-valid but untraceable status evidence must be gated out here
    # instead of failing the whole run at compile time.
    assert not pipeline._passes_publication_gate(invalid, verdict)


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

    assert summary["source_open_questions"] == 0
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
        assert "Scientific significance:" in text
    combined = "\n".join(texts)
    assert "《10000个科学难题》物理学卷" in combined
    assert "The author isolates one unresolved finite-regime target." in combined
    assert "Current best result: Adjacent parameter regimes are known" in combined
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
            if item["problem_id"] == problem["id"]
        )
        assert problem["repository"]["slug"] == Path(
            matching["solution_repo"]
        ).name
    invalid_problem = yaml.safe_load(manifests[0].read_text(encoding="utf-8"))
    invalid_problem["resolution_audit"]["evidence"] = [
        {
            "source": "web",
            "title": "Adjacent metadata only",
            "identifier": "adjacent-metadata",
            "url": "",
            "date": "2026",
            "content_level": "metadata",
            "relation": "adjacent_only",
            "supports": "No direct same-core status evidence.",
            "direct_support": False,
        }
    ]
    invalid_manifest = tmp_path / "invalid-problem.yaml"
    invalid_manifest.write_text(
        yaml.safe_dump(invalid_problem, sort_keys=False), encoding="utf-8"
    )
    assert any(
        "traceable direct non-metadata same-core status evidence" in error
        for error in validate_problem(
            invalid_manifest, repository_root / "schemas/problem.schema.json"
        )
    )
    hardest = max(
        yaml.safe_load(path.read_text(encoding="utf-8"))["solution_review_contract"][
            "verification_difficulty"
        ]
        for path in manifests
    )
    assert hardest == 10
    ranking = json.loads(
        (pipeline.run_dir / "ranking.json").read_text(encoding="utf-8")
    )["ranking"]
    assert ranking[0]["scientific_significance_score"] == 9
    assert ranking[0]["verification_difficulty"] == 10
    assert ranking[0]["ranking_lane"] == "research-ready"
    calls = list(runner.calls)
    assert pipeline.run() == summary
    assert runner.calls == calls
    assert "never add finite-size" in runner.prompts["discovery"][0].lower()
    assert "famous or standard open problem" in runner.prompts[
        "canonicalization"
    ][0].lower()
    assert "must not narrow or redefine" in runner.prompts["triage"][0].lower()
    assert "famous or named problem" in runner.prompts["research"][0].lower()
    assert "authoritative formulation" in runner.prompts["problem-reviewer"][
        0
    ].lower()


@pytest.mark.parametrize(
    ("review_verdict", "expected_reason"),
    [("revise", "needs_revision"), ("reject", "rejected")],
)
def test_reviewer_withdrawal_depublishes_without_touching_solution_repo(
    tmp_path: Path, review_verdict: str, expected_reason: str
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["outputs"]["pool_root"] = str(tmp_path / "pool-repo")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    runner = MutableReviewTopicAgentRunner()
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="topic-depublication",
        agent_runner=runner,
    )
    first = pipeline.run()
    candidate_id = sorted(pipeline.state["candidates"])[0]
    candidate_state = pipeline.state["candidates"][candidate_id]
    withdrawn_id = candidate_state["problem_id"]
    repo = Path(candidate_state["solution_repo"])
    user_file = repo / "research-notes.md"
    user_file.write_text("user-owned progress\n", encoding="utf-8")
    subprocess.run(["git", "add", "research-notes.md"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Researcher",
            "-c",
            "user.email=researcher@example.test",
            "commit",
            "-m",
            "Add research notes",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    user_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    runner.review_verdict = review_verdict
    second = pipeline.retry(candidate_id, "problem-review")

    assert withdrawn_id in first["accepted_problem_ids"]
    assert withdrawn_id not in second["accepted_problem_ids"]
    assert len(second["accepted_problem_ids"]) == 1
    ranking_ids = {
        row["id"]
        for row in json.loads(
            (pipeline.run_dir / "ranking.json").read_text(encoding="utf-8")
        )["ranking"]
    }
    assert withdrawn_id not in ranking_ids
    catalog_ids = {
        json.loads(line)["id"]
        for line in (tmp_path / "pool-repo/pool/catalog.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    assert withdrawn_id not in catalog_ids
    assert (tmp_path / f"pool-repo/pool/depublished/{withdrawn_id}.yaml").is_file()
    tombstone = json.loads(
        (pipeline.run_dir / f"candidates/{candidate_id}/depublication.json").read_text(
            encoding="utf-8"
        )
    )
    assert tombstone["status"] == "depublished"
    assert tombstone["reason"] == expected_reason
    assert tombstone["repository_action"] == "preserved"
    assert user_file.read_text(encoding="utf-8") == "user-owned progress\n"
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        == user_head
    )


def test_research_retitle_keeps_allocated_solution_repo_slug(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    runner = MutableReviewTopicAgentRunner()
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=repository_root,
        run_id="topic-retitle",
        agent_runner=runner,
    )
    pipeline.run()
    candidate_id = sorted(pipeline.state["candidates"])[0]
    allocated_repo = Path(pipeline.state["candidates"][candidate_id]["solution_repo"])

    runner.retitle_research = True
    pipeline.retry(candidate_id, "research")

    candidate_state = pipeline.state["candidates"][candidate_id]
    assert Path(candidate_state["solution_repo"]) == allocated_repo
    problem = yaml.safe_load(
        (pipeline.run_dir / f"candidates/{candidate_id}/problem.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert problem["title"].endswith(" corrected")
    assert problem["repository"]["slug"] == allocated_repo.name
    assert candidate_state["problem_repo_slug"] == allocated_repo.name


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
    assert config["agents"]["workers"] == 4
    assert config["agents"]["networked_workers"] == 4
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
    assert config["limits"]["max_decomposition_depth"] == 1
    assert config["limits"]["max_audited_candidates_per_topic"] == 6


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
            "repo_slug": f"{topic_id}-open-problems",
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

    records = pipeline._ingest(discovered)

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

    # The post-canonicalization pass keeps the candidate from the earliest
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


def test_topic_id_is_derived_from_source_records_and_repair_is_audited(
    tmp_path: Path,
) -> None:
    class DerivedTopicRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "canonicalization":
                for cluster in result.output["clusters"]:
                    cluster["topic_id"] = "invented-method-slug"
                dump_json(kwargs["output_path"], result.output)
            return result

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="topic-id-repair",
        agent_runner=DerivedTopicRunner(),
    )
    candidates = pipeline._canonicalize(pipeline._ingest(pipeline._discover()))

    assert {candidate["topic_id"] for candidate in candidates} == {"hubbard"}
    repairs = json.loads(
        (pipeline.run_dir / "canonicalization-repairs.json").read_text(
            encoding="utf-8"
        )
    )["repairs"]
    assert len(repairs) == 2
    assert {repair["kind"] for repair in repairs} == {"topic_id"}
    assert {repair["repaired_topic_id"] for repair in repairs} == {"hubbard"}


def test_topic_campaign_retriages_decomposed_children_and_caps_audits(
    tmp_path: Path,
) -> None:
    class DecompositionRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "research" and '"parent_candidate_id"' in kwargs[
                "prompt"
            ]:
                output = result.output
                statement = (
                    "Does the pinned finite lattice admit witness A?"
                    if "witness A" in kwargs["prompt"]
                    else "Does the pinned finite lattice admit witness B?"
                )
                problem = output["problem"]
                problem["title"] = statement.rstrip("?")
                problem["question"]["canonical_statement"] = statement
                problem["question"]["scope"] = (
                    "The finite model and witness A stated in the source."
                    if "witness A" in kwargs["prompt"]
                    else "The finite model and witness B stated in the source."
                )
                problem["discovery_contract"]["answer_types"] = [
                    "proof",
                    "counterexample",
                ]
                dump_json(kwargs["output_path"], output)
                return AgentRun(output=output, metadata=result.metadata)
            if kwargs["role"] != "triage":
                return result
            output = result.output
            if '"canonical_title": "Finite-lattice witness"' in kwargs["prompt"]:
                output["verification_clarity"] = "needs_decomposition"
                output["assessment"] = (
                    "The parent must be split before one passing artifact exists."
                )
                output["decomposition_parent_coverage"] = "complete"
                output["proposed_subproblems"] = [
                    {
                        "question": "Does the pinned finite lattice admit witness A?",
                        "scope": "The finite model and witness A stated in the source.",
                        "answer_types": ["proof", "counterexample"],
                        "verification_standard": (
                            "Check witness A against every pinned finite-lattice equation."
                        ),
                        "rationale": "This isolates witness A.",
                        "relation_to_parent": "component",
                        "source_support": [
                            {
                                "source_key": "lead:hubbard:book-target",
                                "exact_excerpt": "Determine whether the finite lattice admits the stated witness.",
                            }
                        ],
                    },
                    {
                        "question": "Does the pinned finite lattice admit witness B?",
                        "scope": "The finite model and witness B stated in the source.",
                        "answer_types": ["proof", "counterexample"],
                        "verification_standard": (
                            "Check witness B against every pinned finite-lattice equation."
                        ),
                        "rationale": "This isolates witness B.",
                        "relation_to_parent": "component",
                        "source_support": [
                            {
                                "source_key": "lead:hubbard:book-target",
                                "exact_excerpt": "Determine whether the finite lattice admits the stated witness.",
                            }
                        ],
                    },
                ]
            elif '"parent_candidate_id"' in kwargs["prompt"]:
                output["verification_clarity"] = "clear"
                output["decomposition_parent_coverage"] = "not_applicable"
                output["proposed_subproblems"] = []
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)

    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["limits"]["max_decomposition_depth"] = 1
    config["limits"]["max_audited_candidates_per_topic"] = 2
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    runner = DecompositionRunner()
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="decomposition-loop",
        agent_runner=runner,
    )

    summary = pipeline.run()

    assert summary["canonical_candidates"] == 2
    assert summary["active_candidates"] == 3
    assert summary["decomposed_parent_count"] == 1
    assert summary["generated_subproblem_count"] == 2
    assert summary["audit_budget_deferred_count"] == 1
    assert summary["triage_deferred_count"] == 1
    assert len(summary["accepted_problem_ids"]) == 2
    assert runner.calls.count("triage") == 4
    assert runner.calls.count("research") == 2
    assert runner.calls.count("problem-reviewer") == 2
    decompositions = json.loads(
        (pipeline.run_dir / "decompositions.json").read_text(encoding="utf-8")
    )
    assert len(decompositions["decompositions"]) == 1
    assert len(decompositions["active_candidate_ids"]) == 3


def test_decomposition_batches_children_from_multiple_parents_by_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["limits"]["max_decomposition_depth"] = 1
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="multi-parent-frontier",
        agent_runner=TopicAgentRunner(),
    )
    parents = [
        {
            "candidate_id": candidate_id,
            "topic_id": "hubbard",
            "topic_title": "Hubbard Model",
                "canonical_title": title,
                "canonical_statement": f"Can {title.lower()} be established?",
                "scope": f"The complete source-supported claim for {title}.",
                "named_problem": False,
                "authoritative_formulation": None,
                "formulation_alignment": "not_applicable",
                "domain": "condensed-matter physics",
                "source_keys": [f"lead:hubbard:{candidate_id}"],
                "source_support": [
                    {
                        "source_key": f"lead:hubbard:{candidate_id}",
                        "exact_excerpt": f"Can {title.lower()} be established?",
                    }
                ],
            "source_records": [],
            "source_open_questions": [],
        }
        for candidate_id, title in (
            ("CAN-000000000002", "Parent B"),
            ("CAN-000000000001", "Parent A"),
        )
    ]
    triage_by_id: dict[str, dict[str, Any]] = {}
    for parent in parents:
        candidate_id = parent["candidate_id"]
        pipeline.state["candidates"][candidate_id] = {
            "status": "canonicalized",
            "canonical_title": parent["canonical_title"],
            "topic_id": "hubbard",
        }
        triage_by_id[candidate_id] = {
                "candidate_id": candidate_id,
                "importance_level": "high",
                "verification_clarity": "needs_decomposition",
                "decomposition_parent_coverage": "complete",
                "assessment": "The parent claim splits into two independently checkable components.",
                "proposed_subproblems": [
                    {
                        "question": f"{parent['canonical_title']} component {index}?",
                        "scope": (
                            f"Component {index} of the complete source-supported claim."
                        ),
                        "answer_types": ["proof", "counterexample"],
                    "verification_standard": (
                        f"Check component {index} against its defining claim."
                        ),
                        "rationale": f"This isolates component {index}.",
                        "relation_to_parent": "component",
                        "source_support": list(parent["source_support"]),
                    }
                for index in (1, 2)
            ],
        }

    batches: list[list[dict[str, Any]]] = []

    def triage_frontier(
        candidates: list[dict[str, Any]], *, workers: int
    ) -> dict[str, dict[str, Any]]:
        assert workers == 4
        batches.append(list(candidates))
        return {
            candidate["candidate_id"]: {
                "candidate_id": candidate["candidate_id"],
                "importance_level": "high",
                "verification_clarity": "clear",
                "decomposition_parent_coverage": "not_applicable",
                "proposed_subproblems": [],
                "assessment": "The decomposed child is a clear, atomic check.",
            }
            for candidate in candidates
        }

    monkeypatch.setattr(pipeline, "_triage_candidates", triage_frontier)

    leaves, updated_triage, decompositions = pipeline._decompose_unclear_candidates(
        parents,
        triage_by_id,
        workers=4,
    )

    assert len(batches) == 1
    assert len(batches[0]) == 4
    assert [item["candidate_id"] for item in batches[0]] == sorted(
        item["candidate_id"] for item in batches[0]
    )
    assert {item["parent_candidate_id"] for item in batches[0]} == {
        "CAN-000000000001",
        "CAN-000000000002",
    }
    assert [item["parent_candidate_id"] for item in decompositions] == [
        "CAN-000000000001",
        "CAN-000000000002",
    ]
    assert len(leaves) == 4
    assert len(updated_triage) == 6


def test_restricted_derived_child_does_not_replace_parent_end_to_end(
    tmp_path: Path,
) -> None:
    class RestrictedRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            prompt = kwargs["prompt"]
            output = result.output
            if kwargs["role"] == "triage" and (
                '"canonical_title": "Finite-lattice witness"' in prompt
            ):
                output["verification_clarity"] = "needs_decomposition"
                output["decomposition_parent_coverage"] = "complete"
                output["proposed_subproblems"] = [
                    {
                        "question": "Does one pinned finite lattice admit witness A?",
                        "scope": "One pinned finite lattice and witness A.",
                        "answer_types": ["proof", "counterexample"],
                        "verification_standard": "Check witness A on the pinned lattice.",
                        "rationale": "This is useful but narrower than the parent.",
                        "relation_to_parent": "restricted_derived",
                        "source_support": [
                            {
                                "source_key": "lead:hubbard:book-target",
                                "exact_excerpt": "Determine whether the finite lattice admits the stated witness.",
                            }
                        ],
                    }
                ]
            elif kwargs["role"] == "triage" and '"parent_candidate_id"' in prompt:
                pass
            elif kwargs["role"] == "research" and '"parent_candidate_id"' in prompt:
                problem = output["problem"]
                problem["title"] = "Does one pinned finite lattice admit witness A"
                problem["question"]["canonical_statement"] = (
                    "Does one pinned finite lattice admit witness A?"
                )
                problem["question"]["scope"] = "One pinned finite lattice and witness A."
                problem["discovery_contract"]["answer_types"] = [
                    "proof",
                    "counterexample",
                ]
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="restricted-child-retains-parent",
        agent_runner=RestrictedRunner(),
    )

    summary = pipeline.run()

    decompositions = json.loads(
        (pipeline.run_dir / "decompositions.json").read_text(encoding="utf-8")
    )
    item = decompositions["decompositions"][0]
    assert item["parent_replaced"] is False
    assert item["parent_candidate_id"] in decompositions["active_candidate_ids"]
    assert pipeline.state["candidates"][item["parent_candidate_id"]]["status"] == (
        "triage_deferred"
    )
    derived_repo = next(
        Path(repo["solution_repo"])
        for repo in summary["solution_repositories"]
        if "pinned-finite-lattice" in repo["solution_repo"]
    )
    assert "restricted derived problem" in (
        derived_repo / "README.md"
    ).read_text(encoding="utf-8")


def test_research_cannot_narrow_formulation_without_major_progress_end_to_end(
    tmp_path: Path,
) -> None:
    class NarrowingRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "research":
                result.output["problem"]["title"] = "Artificial finite proxy"
                result.output["problem"]["question"]["canonical_statement"] = (
                    "Solve only an artificial finite proxy."
                )
                dump_json(kwargs["output_path"], result.output)
            return result

    runner = NarrowingRunner()
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="reject-silent-research-narrowing",
        agent_runner=runner,
    )

    summary = pipeline.run()

    # The narrowed draft is rejected by the frozen-formulation contract, but
    # that is a refinable structure failure: the Refine Agent repairs it
    # offline and both candidates publish.
    assert len(summary["accepted_problem_ids"]) == 2
    assert summary["failed_candidates"] == []
    assert len(list((tmp_path / "problems").glob("ORP-*"))) == 2
    assert runner.calls.count("refine") == 2
    for candidate_state in pipeline.state["candidates"].values():
        assert candidate_state["status"] == "accepted"
        assert candidate_state["refined"] is True
        assert candidate_state["refine_rounds"] == 1


def test_named_problem_requires_source_grounded_authoritative_formulation(
    tmp_path: Path,
) -> None:
    class MissingAuthorityRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "canonicalization":
                result.output["clusters"][0].update(
                    {
                        "named_problem": True,
                        "authoritative_formulation": None,
                        "formulation_alignment": "exact",
                    }
                )
                dump_json(kwargs["output_path"], result.output)
            return result

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="reject-missing-named-authority",
        agent_runner=MissingAuthorityRunner(),
    )

    with pytest.raises(CampaignError, match="requires an authoritative formulation"):
        pipeline.run()
    assert not list((tmp_path / "problems").glob("ORP-*"))


def test_named_problem_reviewer_alignment_is_a_publication_hard_gate(
    tmp_path: Path,
) -> None:
    class NamedReviewerRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            prompt = kwargs["prompt"]
            output = result.output
            if kwargs["role"] == "canonicalization":
                output["clusters"][0].update(
                    {
                        "named_problem": True,
                        "authoritative_formulation": {
                            "source_key": "lead:hubbard:book-target",
                            "citation": "Standard formulation",
                            "url": "https://example.test/book-target",
                            "exact_excerpt": "Determine whether the finite lattice admits the stated witness.",
                        },
                        "formulation_alignment": "exact",
                    }
                )
            elif kwargs["role"] == "research" and "Finite-lattice witness" in prompt:
                problem = output["problem"]
                problem["question"]["named_problem"] = True
                problem["question"]["authoritative_formulation"] = {
                    "citation": "Standard formulation",
                    "url": "https://example.test/standard",
                    "exact_excerpt": "Does the finite lattice admit the stated witness?",
                    "evidence_identifier": "standard-formulation",
                }
                problem["question"]["formulation_alignment"] = "exact"
                problem["resolution_audit"]["evidence"].append(
                    {
                        "source": "web",
                        "title": "Standard formulation",
                        "identifier": "standard-formulation",
                        "url": "https://example.test/standard",
                        "date": "2024",
                        "content_level": "full_text",
                        "relation": "continuing_open",
                        "supports": "States the standard named problem directly.",
                        "direct_support": True,
                    }
                )
            elif kwargs["role"] == "problem-reviewer" and (
                "Finite-lattice witness" in prompt
            ):
                output["authoritative_alignment"] = "fail"
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="named-reviewer-hard-gate",
        agent_runner=NamedReviewerRunner(),
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 1
    named_state = next(
        state
        for state in pipeline.state["candidates"].values()
        if state["canonical_title"] == "Finite-lattice witness"
    )
    assert named_state["problem_review_verdict"] == "accept"
    assert named_state["status"] == "audited_out"


def test_reviewer_source_fidelity_fail_is_a_publication_hard_gate(
    tmp_path: Path,
) -> None:
    class FidelityRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            output = result.output
            if kwargs["role"] == "problem-reviewer" and (
                "Finite-lattice witness" in kwargs["prompt"]
            ):
                output = {**output, "source_fidelity": "fail"}
                dump_json(kwargs["output_path"], output)
                return AgentRun(output=output, metadata=result.metadata)
            return result

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="reviewer-fidelity-hard-gate",
        agent_runner=FidelityRunner(),
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 1
    finite_state = next(
        state
        for state in pipeline.state["candidates"].values()
        if state["canonical_title"] == "Finite-lattice witness"
    )
    assert finite_state["problem_review_verdict"] == "accept"
    assert finite_state["status"] == "audited_out"


def test_unconfirmed_formulation_change_is_a_publication_hard_gate(
    tmp_path: Path,
) -> None:
    class ScopeRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            output = result.output
            if kwargs["role"] == "research" and (
                "Finite-lattice witness" in kwargs["prompt"]
            ):
                problem = output["problem"]
                problem["title"] = problem["title"] + " corrected"
                problem["resolution_audit"]["progress_assessment"] = {
                    "major_progress_found": True,
                    "effect": "reframes",
                }
                dump_json(kwargs["output_path"], output)
                return AgentRun(output=output, metadata=result.metadata)
            # The reviewer accepts but never confirms the declared formulation
            # change: scope_change stays "not_applicable" instead of "pass".
            return result

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="reviewer-scope-change-hard-gate",
        agent_runner=ScopeRunner(),
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 1
    changed_state = next(
        state
        for state in pipeline.state["candidates"].values()
        if str(state["canonical_title"]).startswith("Finite-lattice witness")
    )
    assert changed_state["problem_review_verdict"] == "accept"
    assert changed_state["status"] == "audited_out"


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
                "search_summary": "Only metadata was found.",
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
            ids_by_title[problem["title"]] = problem["id"]
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
            "repo_slug": f"{topic_id}-open-problems",
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
    ) -> AgentRun:
        assert role == "discovery"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(json.dumps({"role": role}) + "\n", encoding="utf-8")
        self.prompts.append(prompt)
        domain_id = "alpha" if "Domain id: alpha" in prompt else "beta"
        output = {
            "domain_id": domain_id,
            "search_summary": "Agent adaptive search summary.",
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

    discovered = pipeline._discover()

    assert set(discovered) == {"alpha", "beta"}
    artifact = json.loads(
        (pipeline.run_dir / "domains" / "alpha" / "lkm-sweep.json").read_text(
            encoding="utf-8"
        )
    )
    assert artifact["status"] == "failed"
    assert "FileNotFoundError" in artifact["error"]
    assert artifact["query"] == "Find scoped targets for alpha."
    # The agent-driven discovery route still produced its papers.
    assert [paper["paper_id"] for paper in discovered["alpha"]["papers"]] == [
        "agent-alpha"
    ]


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

    discovered = pipeline._discover()

    # Merge order is seed -> sweep -> agent and papers_per_domain=2 caps the
    # merged total, so sweep hits outrank the agent's adaptive papers.
    assert [paper["paper_id"] for paper in discovered["alpha"]["papers"]] == [
        "seed-alpha",
        "sweep-1",
    ]
    assert [paper["paper_id"] for paper in discovered["beta"]["papers"]] == [
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


def test_formulation_change_fields_are_computed_mechanically() -> None:
    candidate = {
        "canonical_title": "Original title",
        "canonical_statement": "Original statement?",
        "scope": "Original scope.",
        "named_problem": False,
        # Answer types are produced at canonicalization and carried on the
        # candidate; Triage only routes, so the freeze baseline lives here.
        "answer_types": ["proof", "counterexample"],
    }
    triage: dict[str, Any] = {}

    def draft(**overrides: Any) -> dict[str, Any]:
        problem: dict[str, Any] = {
            "title": "Original title",
            "question": {
                "canonical_statement": "Original statement?",
                "scope": "Original scope.",
                "named_problem": False,
                "authoritative_formulation": None,
                "formulation_alignment": "not_applicable",
            },
            "resolution_audit": {
                "status": "still_open",
                "progress_assessment": {
                    "major_progress_found": False,
                    "effect": "none",
                },
            },
            # order-free compare against the candidate answer types
            "discovery_contract": {"answer_types": ["counterexample", "proof"]},
        }
        for key, value in overrides.items():
            section, _, field = key.partition(".")
            if field:
                problem[section][field] = value
            else:
                problem[key] = value
        return {"candidate_id": "CAN-000000000001", "problem": problem}

    # An unchanged formulation validates and the pipeline injects the
    # mechanical diff and derived decision; the agent never reports them.
    unchanged = draft()
    CampaignPipeline._validate_topic_research_contract(candidate, unchanged)
    CampaignPipeline._finalize_research_output(candidate, unchanged)
    assert unchanged["_formulation_changed"] is False
    assert unchanged["_formulation_changed_fields"] == []
    progress = unchanged["problem"]["resolution_audit"]["progress_assessment"]
    assert progress["decision"] == "continue"

    # A real change backed by major progress: changed_fields are computed from
    # the draft, not self-reported.
    changed = draft(
        title="Corrected title",
        **{
            "resolution_audit.progress_assessment": {
                "major_progress_found": True,
                "effect": "reframes",
            }
        },
    )
    CampaignPipeline._validate_topic_research_contract(candidate, changed)
    CampaignPipeline._finalize_research_output(candidate, changed)
    assert changed["_formulation_changed"] is True
    assert changed["_formulation_changed_fields"] == ["title"]
    changed_progress = changed["problem"]["resolution_audit"]["progress_assessment"]
    assert changed_progress["decision"] == "rewrite-core"

    # A real change without major progress still fails, from the computed
    # (not self-reported) diff.
    silent = draft(**{"question.canonical_statement": "A silently narrowed statement?"})
    with pytest.raises(CampaignError, match="without major progress"):
        CampaignPipeline._validate_topic_research_contract(candidate, silent)


def test_verification_clarity_contract_matrix() -> None:
    base = {
        "importance_level": "high",
        "assessment": "The target is a concrete finite check worth auditing.",
    }
    subproblem = {
        "question": "Does the pinned finite lattice admit witness A?",
        "scope": "One pinned finite lattice and witness A.",
        "answer_types": ["proof"],
        "verification_standard": "Check witness A on the pinned lattice.",
        "rationale": "This isolates witness A.",
        "relation_to_parent": "component",
        "source_support": [],
    }

    # clear with non-empty subproblems is a contradiction and must be rejected.
    with pytest.raises(
        CampaignError, match="not_applicable coverage and no subproblems"
    ):
        CampaignPipeline._validate_verification_fields(
            {
                **base,
                "verification_clarity": "clear",
                "decomposition_parent_coverage": "not_applicable",
                "proposed_subproblems": [subproblem],
            },
            "Triage Agent",
        )
    # unverifiable without subproblems would strand the candidate: reject.
    with pytest.raises(CampaignError, match="must propose subproblems"):
        CampaignPipeline._validate_verification_fields(
            {
                **base,
                "verification_clarity": "unverifiable",
                "decomposition_parent_coverage": "complete",
                "proposed_subproblems": [],
            },
            "Research Agent",
        )
    # unverifiable with concrete subproblems and stated coverage passes.
    CampaignPipeline._validate_verification_fields(
        {
            **base,
            "verification_clarity": "unverifiable",
            "decomposition_parent_coverage": "complete",
            "proposed_subproblems": [subproblem],
        },
        "Triage Agent",
    )
    # Control: clear without subproblems stays valid.
    CampaignPipeline._validate_verification_fields(
        {
            **base,
            "verification_clarity": "clear",
            "decomposition_parent_coverage": "not_applicable",
            "proposed_subproblems": [],
        },
        "Triage Agent",
    )


def test_authoritative_formulation_flows_from_lead_into_source_record(
    tmp_path: Path,
) -> None:
    standard_excerpt = (
        "The standard formulation asks whether every finite witness lattice "
        "admits the stated construction."
    )

    class AuthoritativeRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            output = result.output
            if kwargs["role"] == "discovery":
                output["problem_leads"][0]["authoritative_formulation"] = {
                    "citation": "Standard reference formulation",
                    "url": "https://example.test/standard-formulation",
                    "exact_excerpt": standard_excerpt,
                    "evidence_identifier": "standard-formulation",
                }
                dump_json(kwargs["output_path"], output)
                return AgentRun(output=output, metadata=result.metadata)
            if kwargs["role"] == "canonicalization":
                output["clusters"][0].update(
                    {
                        "named_problem": True,
                        "authoritative_formulation": {
                            "source_key": "lead:hubbard:book-target",
                            "citation": "Standard reference formulation",
                            "url": "https://example.test/standard-formulation",
                            "exact_excerpt": standard_excerpt,
                        },
                        "formulation_alignment": "exact",
                    }
                )
                dump_json(kwargs["output_path"], output)
                return AgentRun(output=output, metadata=result.metadata)
            return result

    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="authoritative-formulation-wiring",
        agent_runner=AuthoritativeRunner(),
    )
    records = pipeline._ingest(pipeline._discover())

    by_key = {record["source_key"]: record for record in records}
    named = by_key["lead:hubbard:book-target"]
    # The standard excerpt is deliberately absent from surrounding_context:
    # only the wiring appends it to source_text so the network-less
    # canonicalization stage can pass its verbatim-substring check.
    assert standard_excerpt not in named["surrounding_context"]
    assert named["authoritative_formulation"]["exact_excerpt"] == standard_excerpt
    assert standard_excerpt in named["source_text"]
    plain = by_key["lead:hubbard:web-target"]
    assert plain["authoritative_formulation"] is None
    assert plain["source_text"] == plain["surrounding_context"]

    candidates = pipeline._canonicalize(records)

    named_candidate = next(
        candidate for candidate in candidates if candidate["named_problem"]
    )
    assert named_candidate["authoritative_formulation"]["exact_excerpt"] == (
        standard_excerpt
    )
    assert named_candidate["formulation_alignment"] == "exact"


def _queued_subproblems(
    parent_support: dict[str, str], tag: str
) -> list[dict[str, Any]]:
    return [
        {
            "question": f"Subproblem {tag}-A of the parent question?",
            "scope": f"Scope {tag}-A",
            "answer_types": ["proof"],
            "verification_standard": "Replay the stated finite check.",
            "rationale": f"Component {tag}-A covering part of the parent claim.",
            "relation_to_parent": "component",
            "source_support": [parent_support],
        },
        {
            "question": f"Subproblem {tag}-B of the parent question?",
            "scope": f"Scope {tag}-B",
            "answer_types": ["counterexample"],
            "verification_standard": "Replay the stated finite check.",
            "rationale": f"Component {tag}-B covering the rest of the parent claim.",
            "relation_to_parent": "component",
            "source_support": [parent_support],
        },
    ]


class UnverifiableTriageRunner(TopicAgentRunner):
    """Top-level candidates triage unverifiable; children triage clear+low."""

    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        output = result.output
        if kwargs["role"] == "triage":
            prompt = kwargs["prompt"]
            match = re.search(
                r'"source_support": \[\s*\{\s*"source_key": "([^"]+)",\s*'
                r'"exact_excerpt": "([^"]+)"',
                prompt,
            )
            assert match is not None
            parent_support = {
                "source_key": match.group(1),
                "exact_excerpt": match.group(2),
            }
            if '"parent_candidate_id"' in prompt:
                # Decomposed child: clear but unimportant, so the run stops there.
                output["importance_level"] = "low"
            else:
                finite = "Finite-lattice witness" in prompt
                tag = "finite" if finite else "coupling"
                output["verification_clarity"] = "unverifiable"
                output["decomposition_parent_coverage"] = "complete"
                output["proposed_subproblems"] = _queued_subproblems(
                    parent_support, tag
                )
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)
        return result


def test_unverifiable_triage_queues_subproblems_when_depth_cap_reached(
    tmp_path: Path,
) -> None:
    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["limits"]["max_decomposition_depth"] = 0
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="run-depth0",
        agent_runner=UnverifiableTriageRunner(),
    )

    summary = pipeline.run()

    # With the depth cap at zero there is no in-run decomposition: the
    # proposed subproblems enter the persistent topic queue instead.
    queue = _load_topic_queue(tmp_path / "runs" / "topic-queue.jsonl")
    assert summary["decomposed_parent_count"] == 0
    assert len(queue) == 4
    assert all(entry["status"] == "pending" for entry in queue)
    assert all(entry["depth"] == 0 for entry in queue)
    parents = {entry["parent_candidate_id"] for entry in queue}
    assert len(parents) == 2
    for parent_id in parents:
        state = pipeline.state["candidates"][parent_id]
        assert state["status"] == "triage_deferred"
        assert len(state["topic_queue_ids"]) == 2
    decompositions = json.loads(
        (pipeline.run_dir / "decompositions.json").read_text(encoding="utf-8")
    )
    assert decompositions["decompositions"] == []
    assert len(decompositions["topic_queue_enqueued"]) == 2


def test_unverifiable_triage_decomposes_in_run_below_depth_cap(
    tmp_path: Path,
) -> None:
    config_path = _config(tmp_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["limits"]["max_decomposition_depth"] = 1
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="run-depth1",
        agent_runner=UnverifiableTriageRunner(),
    )

    summary = pipeline.run()

    assert summary["decomposed_parent_count"] == 2
    assert summary["generated_subproblem_count"] == 4
    # Replaced parents are not leaves, so nothing may be queued.
    queue_path = tmp_path / "runs" / "topic-queue.jsonl"
    assert not queue_path.exists() or not _load_topic_queue(queue_path)
    statuses = {
        state["canonical_title"]: state["status"]
        for state in pipeline.state["candidates"].values()
    }
    assert statuses["Finite-lattice witness"] == "decomposed"
    assert statuses["Critical-coupling interval"] == "decomposed"
    children = [
        state
        for state in pipeline.state["candidates"].values()
        if state.get("decomposition_parent_id")
    ]
    assert len(children) == 4
    assert all(state["status"] == "triage_deferred" for state in children)
    active = json.loads(
        (pipeline.run_dir / "decompositions.json").read_text(encoding="utf-8")
    )["active_candidate_ids"]
    assert sorted(
        candidate_id
        for candidate_id, state in pipeline.state["candidates"].items()
        if state.get("decomposition_parent_id")
    ) == active


class ResearchReflowRunner(TopicAgentRunner):
    """Research cannot reach a clear standard for the finite candidate."""

    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        output = result.output
        if kwargs["role"] == "research" and "Finite-lattice witness" in kwargs["prompt"]:
            match = re.search(
                r'"source_support": \[\s*\{\s*"source_key": "([^"]+)",\s*'
                r'"exact_excerpt": "([^"]+)"',
                kwargs["prompt"],
            )
            assert match is not None
            output["problem"]["solution_review_contract"]["verification_clarity"] = (
                "needs_decomposition"
            )
            output["decomposition_parent_coverage"] = "partial"
            output["proposed_subproblems"] = _queued_subproblems(
                {"source_key": match.group(1), "exact_excerpt": match.group(2)},
                "research",
            )[:1]
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)
        return result


class ReinjectionRunner(TopicAgentRunner):
    """Dynamic canonicalization covering queue: records; triage defers all."""

    def run(self, **kwargs: Any) -> AgentRun:
        if kwargs["role"] == "canonicalization":
            prompt = kwargs["prompt"]
            self.calls.append("canonicalization")
            self.prompts.setdefault("canonicalization", []).append(prompt)
            blob = prompt.split(
                "Source records with provenance and context:\n", 1
            )[1].split("\n\nHeuristic possible-duplicate pairs:", 1)[0]
            records = json.loads(blob)
            clusters = []
            for record in records:
                excerpt = record["exact_excerpt"]
                assert excerpt in (record.get("source_text") or record["content"])
                statement = str(record["content"])
                clusters.append(
                    {
                        "topic_id": record["topic_id"],
                        "parent_theme": "Re-issued queued subproblems",
                        "canonical_title": statement.rstrip("?")[:80],
                        "canonical_statement": statement,
                        "scope": "The scope stated in the source record.",
                        "named_problem": False,
                        "authoritative_formulation": None,
                        "formulation_alignment": "not_applicable",
                        "domain": "physics",
                        "source_keys": [record["source_key"]],
                        "source_support": [
                            {
                                "source_key": record["source_key"],
                                "exact_excerpt": excerpt,
                            }
                        ],
                        "aliases": [],
                        "answer_types": ["proof"],
                        "verification_plan": "Check the answer against the stated question.",
                        "decomposition_rationale": "One source record, one candidate.",
                        "rationale": "The record poses exactly this question.",
                    }
                )
            output = {"clusters": clusters}
            dump_json(kwargs["output_path"], output)
            return AgentRun(
                output=output,
                metadata={"exit_code": 0, "role": "canonicalization"},
            )
        result = super().run(**kwargs)
        output = result.output
        if kwargs["role"] == "triage":
            output["importance_level"] = "low"
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)
        return result


def test_research_non_clear_reflows_to_queue_and_next_run_reinjects(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    first = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=repository_root,
        run_id="run-research",
        agent_runner=ResearchReflowRunner(),
    )

    summary = first.run()

    assert len(summary["accepted_problem_ids"]) == 1
    finite_id, finite_state = next(
        (candidate_id, state)
        for candidate_id, state in first.state["candidates"].items()
        if state["canonical_title"] == "Finite-lattice witness"
    )
    assert finite_state["status"] == "decomposed_to_queue"
    assert finite_state["problem_review_verdict"] == "accept"
    assert len(finite_state["topic_queue_ids"]) == 1
    assert "milestone_queue_ids" not in finite_state
    queue = _load_topic_queue(tmp_path / "runs" / "topic-queue.jsonl")
    assert len(queue) == 1
    entry = queue[0]
    assert entry["kind"] == "decomposition"
    assert entry["parent_candidate_id"] == finite_id
    assert entry["lineage"] == [finite_id]
    assert entry["status"] == "pending"
    assert entry["created_run_id"] == "run-research"
    assert entry["statement"] == "Subproblem research-A of the parent question?"

    # The next run over the same runs_root re-ingests the pending entry as a
    # queue:<id> derived_subproblem source record and marks it consumed.
    runner = ReinjectionRunner()
    second = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=repository_root,
        run_id="run-reinject",
        agent_runner=runner,
    )
    second.run()

    queue = _load_topic_queue(tmp_path / "runs" / "topic-queue.jsonl")
    assert len(queue) == 1
    entry = queue[0]
    assert entry["status"] == "consumed"
    assert entry["consumed_run_id"] == "run-reinject"
    canonicalization = json.loads(
        (second.run_dir / "canonicalization.json").read_text(encoding="utf-8")
    )
    keys = {
        key for cluster in canonicalization["clusters"] for key in cluster["source_keys"]
    }
    assert f"queue:{entry['queue_id']}" in keys
    queued_candidates = [
        state
        for state in second.state["candidates"].values()
        if state["canonical_title"] == "Subproblem research-A of the parent question"
    ]
    assert len(queued_candidates) == 1
    assert queued_candidates[0]["status"] == "triage_deferred"
    # The canonicalization prompt carries the queue provenance guidance.
    assert "queue:" in runner.prompts["canonicalization"][0]
    assert "persistent topic queue" in runner.prompts["canonicalization"][0]


def test_topic_queue_write_dedup_pending_consumed_and_source_record(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (repository_root / "schemas/topic-queue.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    runs_root = tmp_path / "runs"
    pipeline = object.__new__(CampaignPipeline)
    run_dir = runs_root / "run-a"
    run_dir.mkdir(parents=True)
    pipeline.run_dir = run_dir
    pipeline.state = {"run_id": "run-a", "candidates": {}}
    pipeline.config = {
        "schema_version": 2,
        "topics": [{"id": "hubbard"}, {"id": "other-topic"}],
    }

    candidate = {
        "candidate_id": "CAN-AAAA1111BBBB",
        "topic_id": "hubbard",
        "source_keys": ["lead:hubbard:book-target"],
        "decomposition_depth": 0,
    }
    subproblems = [
        {
            "question": "Does the sublattice witness exist for L=4?",
            "scope": "L=4 sublattice",
            "answer_types": ["proof"],
            "verification_standard": "Replay the stated check.",
            "rationale": "Component one of the parent claim.",
            "relation_to_parent": "component",
            "source_support": [
                {
                    "source_key": "lead:hubbard:book-target",
                    "exact_excerpt": "Determine whether the finite lattice admits the stated witness.",
                }
            ],
        },
        {
            "question": "Does the sublattice witness exist for L=6?",
            "scope": "L=6 sublattice",
            "answer_types": ["proof"],
            "verification_standard": "Replay the stated check.",
            "rationale": "Component two of the parent claim.",
            "relation_to_parent": "component",
            "source_support": [],
        },
    ]

    entries = pipeline._queue_entries_for_subproblems(
        candidate=candidate, subproblems=subproblems, kind="decomposition"
    )
    assert len(entries) == 2
    for entry in entries:
        validator.validate(entry)
        assert entry["kind"] == "decomposition"
        assert entry["status"] == "pending"
        assert entry["consumed_run_id"] is None
        assert entry["created_run_id"] == "run-a"
        assert entry["parent_candidate_id"] == "CAN-AAAA1111BBBB"
        assert entry["lineage"] == ["CAN-AAAA1111BBBB"]
        assert entry["depth"] == 0
    # Empty child source_support falls back to the parent's source keys.
    assert entries[0]["source_keys"] == ["lead:hubbard:book-target"]
    assert entries[1]["source_keys"] == ["lead:hubbard:book-target"]

    # Enqueue is idempotent on queue_id: re-enqueueing writes nothing.
    written = pipeline._enqueue_topic_queue(entries)
    assert written == [entry["queue_id"] for entry in entries]
    assert pipeline._enqueue_topic_queue(entries) == []
    assert len(_load_topic_queue(pipeline._topic_queue_path())) == 2

    # Pending filters to configured topics in deterministic queue_id order.
    other = dict(entries[0])
    other["topic_id"] = "unconfigured"
    other["queue_id"] = "q0000000000000000"
    other["statement"] = "Out-of-scope question?"
    pipeline._enqueue_topic_queue([other])
    pending = pipeline._pending_topic_queue_entries()
    assert [entry["queue_id"] for entry in pending] == sorted(
        entry["queue_id"] for entry in entries
    )

    # Consumed marking rewrites the file and leaves the pending set.
    pipeline._mark_topic_queue_consumed([entries[0]["queue_id"]])
    loaded = _load_topic_queue(pipeline._topic_queue_path())
    assert len(loaded) == 3
    by_id = {entry["queue_id"]: entry for entry in loaded}
    assert by_id[entries[0]["queue_id"]]["status"] == "consumed"
    assert by_id[entries[0]["queue_id"]]["consumed_run_id"] == "run-a"
    assert by_id[entries[1]["queue_id"]]["status"] == "pending"
    for entry in loaded:
        validator.validate(entry)

    # The synthesized source record satisfies the excerpt contract by
    # construction: the statement doubles as source_text.
    record = pipeline._queue_source_record(entries[0])
    assert record["source_key"] == f"queue:{entries[0]['queue_id']}"
    assert record["source_kind"] == "derived_subproblem"
    assert record["source_text"] == entries[0]["statement"]
    assert record["exact_excerpt"] in record["source_text"]
    assert record["topic_id"] == "hubbard"


def test_research_scale_milestone_contract_matrix() -> None:
    """Scale-dependent clarity rules for the nested Research draft."""

    def draft(
        *,
        clarity: str = "clear",
        scale: str = "single-paper",
        coverage: str = "not_applicable",
        subproblems: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        output = _assessment("CAN-000000000001", finite=True)
        contract = output["problem"]["solution_review_contract"]
        contract["verification_clarity"] = clarity
        output["estimated_solution_scale"] = scale
        output["decomposition_parent_coverage"] = coverage
        output["proposed_subproblems"] = list(subproblems or [])
        return output

    milestone = {
        "question": "Does the pinned finite lattice admit witness A?",
        "scope": "One pinned finite lattice and witness A.",
        "answer_types": ["proof"],
        "verification_standard": "Check witness A on the pinned lattice.",
        "rationale": "A natural waypoint towards the parent question.",
        "relation_to_parent": "component",
        "source_support": [
            {
                "source_key": "lead:hubbard:book-target",
                "exact_excerpt": "Determine whether the finite lattice admits the stated witness.",
            }
        ],
    }

    validate = CampaignPipeline._validate_research_draft_fields

    # (b) A clear single-result draft must not pad the queue with subproblems.
    with pytest.raises(CampaignError, match="must not propose subproblems"):
        validate(
            draft(
                scale="single-result",
                coverage="complete",
                subproblems=[milestone],
            ),
            "Research Agent",
        )
    # Milestones with unstated (not_applicable) coverage are rejected.
    with pytest.raises(
        CampaignError, match="complete or partial parent coverage"
    ):
        validate(
            draft(
                scale="multi-paper",
                coverage="not_applicable",
                subproblems=[milestone],
            ),
            "Research Agent",
        )
    # An unknown scale value is rejected outright.
    with pytest.raises(CampaignError, match="invalid estimated_solution_scale"):
        validate(draft(scale="moonshot"), "Research Agent")
    # (c) A clear multi-paper draft may legitimately decline milestones.
    validate(draft(scale="multi-paper"), "Research Agent")
    # Clear research-program scale with stated partial coverage passes.
    validate(
        draft(
            scale="research-program",
            coverage="partial",
            subproblems=[milestone],
        ),
        "Research Agent",
    )
    # (d) Non-clear drafts ignore the scale: subproblems stay mandatory.
    validate(
        draft(
            clarity="unverifiable",
            scale="single-result",
            coverage="complete",
            subproblems=[milestone],
        ),
        "Research Agent",
    )
    with pytest.raises(CampaignError, match="must propose subproblems"):
        validate(
            draft(clarity="needs_decomposition", scale="multi-paper"),
            "Research Agent",
        )


class ResearchMilestoneRunner(TopicAgentRunner):
    """The finite candidate is clear but estimated at multi-paper scale."""

    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        output = result.output
        if kwargs["role"] == "research" and "Finite-lattice witness" in kwargs["prompt"]:
            match = re.search(
                r'"source_support": \[\s*\{\s*"source_key": "([^"]+)",\s*'
                r'"exact_excerpt": "([^"]+)"',
                kwargs["prompt"],
            )
            assert match is not None
            output["estimated_solution_scale"] = "multi-paper"
            output["decomposition_parent_coverage"] = "partial"
            output["proposed_subproblems"] = _queued_subproblems(
                {"source_key": match.group(1), "exact_excerpt": match.group(2)},
                "milestone",
            )[:1]
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)
        return result


def _run_milestone_campaign(tmp_path: Path) -> CampaignPipeline:
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="run-milestone",
        agent_runner=ResearchMilestoneRunner(),
    )
    pipeline.run()
    return pipeline


def test_research_clear_multi_paper_queues_milestones_and_parent_publishes(
    tmp_path: Path,
) -> None:
    first = _run_milestone_campaign(tmp_path)

    # Both candidates stay clear and publish; the milestones do not divert
    # the parent out of the review/publication flow.
    assert len(first.state["summary"]["accepted_problem_ids"]) == 2
    finite_id, finite_state = next(
        (candidate_id, state)
        for candidate_id, state in first.state["candidates"].items()
        if state["canonical_title"] == "Finite-lattice witness"
    )
    assert finite_state["status"] == "accepted"
    assert finite_state["problem_review_verdict"] == "accept"
    assert len(finite_state["milestone_queue_ids"]) == 1
    assert "topic_queue_ids" not in finite_state
    queue = _load_topic_queue(tmp_path / "runs" / "topic-queue.jsonl")
    assert len(queue) == 1
    entry = queue[0]
    assert entry["kind"] == "milestone"
    assert entry["parent_candidate_id"] == finite_id
    assert entry["lineage"] == [finite_id]
    assert entry["status"] == "pending"
    assert entry["created_run_id"] == "run-milestone"
    assert entry["queue_id"] == finite_state["milestone_queue_ids"][0]
    assert entry["statement"] == "Subproblem milestone-A of the parent question?"


def test_research_milestone_entry_reinjects_next_run(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    first = _run_milestone_campaign(tmp_path)
    queue = _load_topic_queue(tmp_path / "runs" / "topic-queue.jsonl")
    assert len(queue) == 1
    queue_id = queue[0]["queue_id"]

    runner = ReinjectionRunner()
    second = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=repository_root,
        run_id="run-reinject-milestone",
        agent_runner=runner,
    )
    second.run()

    queue = _load_topic_queue(tmp_path / "runs" / "topic-queue.jsonl")
    assert len(queue) == 1
    entry = queue[0]
    assert entry["kind"] == "milestone"
    assert entry["status"] == "consumed"
    assert entry["consumed_run_id"] == "run-reinject-milestone"
    canonicalization = json.loads(
        (second.run_dir / "canonicalization.json").read_text(encoding="utf-8")
    )
    keys = {
        key for cluster in canonicalization["clusters"] for key in cluster["source_keys"]
    }
    assert f"queue:{queue_id}" in keys
    queued_candidates = [
        state
        for state in second.state["candidates"].values()
        if state["canonical_title"] == "Subproblem milestone-A of the parent question"
    ]
    assert len(queued_candidates) == 1
    assert queued_candidates[0]["status"] == "triage_deferred"


def test_is_refinable_classification_matrix() -> None:
    # Schema errors and contract_structure failures are text/structure
    # problems the non-networked Refine Agent can repair.
    assert is_refinable(AgentOutputError("output failed schema validation"))
    assert is_refinable(CampaignError("frozen field", code=CONTRACT_STRUCTURE))
    # contract_evidence needs new information; execution failures need a
    # fresh research call. Neither enters the refine loop.
    assert not is_refinable(CampaignError("missing evidence", code=CONTRACT_EVIDENCE))
    assert not is_refinable(CampaignError("plain failure"))
    assert not is_refinable(AgentExecutionError("exit 1"))
    assert not is_refinable(RuntimeError("transport unavailable"))


class _AnswerTypeNarrowingRunner(TopicAgentRunner):
    """Research silently narrows answer_types (a frozen-field violation)."""

    def __init__(self) -> None:
        super().__init__()
        self.narrow = True

    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        if kwargs["role"] == "research" and self.narrow:
            result.output["problem"]["discovery_contract"]["answer_types"] = ["proof"]
            dump_json(kwargs["output_path"], result.output)
        return result


def test_refine_repairs_frozen_answer_types_and_publishes(tmp_path: Path) -> None:
    runner = _AnswerTypeNarrowingRunner()
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="refine-repairs-answer-types",
        agent_runner=runner,
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 2
    assert summary["failed_candidates"] == []
    assert runner.calls.count("refine") == 2
    for candidate_state in pipeline.state["candidates"].values():
        assert candidate_state["status"] == "accepted"
        assert candidate_state["refined"] is True
        assert candidate_state["refine_rounds"] == 1
    refine_prompt = runner.prompts["refine"][0]
    assert "minimal edits" in refine_prompt
    assert "without major progress" in refine_prompt
    assert "subset of the failed output" in refine_prompt
    assert "named_problem" in refine_prompt
    # The refine stage is a ledger stage carrying the failure provenance.
    refine_stages = [
        (key, record)
        for key, record in pipeline.state["stages"].items()
        if ".refine-1" in key
    ]
    assert len(refine_stages) == 2
    for _, record in refine_stages:
        assert record["status"] == "completed"


def test_refine_ledger_cache_hits_on_resume(tmp_path: Path) -> None:
    runner = _AnswerTypeNarrowingRunner()
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="refine-ledger-cache",
        agent_runner=runner,
    )
    pipeline.run()
    assert runner.calls.count("research") == 2
    assert runner.calls.count("refine") == 2

    # The failed research stage is re-executed on resume, but the identical
    # failure makes the refine stage a ledger cache hit: no new refine call.
    summary = pipeline.run()
    assert len(summary["accepted_problem_ids"]) == 2
    assert runner.calls.count("research") == 4
    assert runner.calls.count("refine") == 2


class _RefineAddsEvidenceRunner(TopicAgentRunner):
    """Refine violates the guardrail by introducing a new evidence item."""

    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        if "Finite-lattice witness" not in kwargs["prompt"]:
            return result
        if kwargs["role"] == "research":
            result.output["problem"]["discovery_contract"]["answer_types"] = ["proof"]
        elif kwargs["role"] == "refine":
            result.output["problem"]["resolution_audit"]["evidence"].append(
                {
                    "source": "web",
                    "title": "Fabricated status review",
                    "identifier": "fabricated-evidence",
                    "url": "https://example.test/fabricated",
                    "date": "2026",
                    "content_level": "full_text",
                    "relation": "continuing_open",
                    "supports": "Invented during refine.",
                    "direct_support": True,
                }
            )
        dump_json(kwargs["output_path"], result.output)
        return result


def test_refine_guardrail_rejects_new_evidence_identifiers(tmp_path: Path) -> None:
    runner = _RefineAddsEvidenceRunner()
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="refine-guardrail",
        agent_runner=runner,
    )

    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 1
    assert len(summary["failed_candidates"]) == 1
    failed = summary["failed_candidates"][0]
    assert "new evidence identifiers" in failed["error"]
    assert "fabricated-evidence" in failed["error"]
    assert failed["refinable"] is True
    failed_state = next(
        state
        for state in pipeline.state["candidates"].values()
        if state["status"] == "research_failed"
    )
    assert failed_state["research_error_class"] == "contract_structure"
    refine_stages = [
        record
        for key, record in pipeline.state["stages"].items()
        if ".refine-1" in key
    ]
    assert [record["status"] for record in refine_stages] == ["failed"]


class _StubbornNarrowingRunner(TopicAgentRunner):
    """Research and every refine round keep the frozen-field violation."""

    def __init__(self) -> None:
        super().__init__()
        self.narrow = True

    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        if kwargs["role"] in {"research", "refine"} and self.narrow:
            result.output["problem"]["discovery_contract"]["answer_types"] = ["proof"]
            dump_json(kwargs["output_path"], result.output)
        return result


def test_refine_exhaustion_quarantines_without_aborting_run(tmp_path: Path) -> None:
    runner = _StubbornNarrowingRunner()
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="refine-exhausted",
        agent_runner=runner,
    )

    summary = pipeline.run()

    # refine_rounds defaults to 1; the still-invalid refined draft exhausts
    # the loop and both candidates quarantine while the run completes.
    assert summary["accepted_problem_ids"] == []
    assert len(summary["failed_candidates"]) == 2
    assert runner.calls.count("refine") == 2
    for failed in summary["failed_candidates"]:
        assert "without major progress" in failed["error"]
        assert failed["refinable"] is True
    for candidate_state in pipeline.state["candidates"].values():
        assert candidate_state["status"] == "research_failed"
        assert candidate_state["research_error_class"] == "contract_structure"
    saved = json.loads((pipeline.run_dir / "state.json").read_text(encoding="utf-8"))
    assert saved["status"] == "completed"
    assert saved["error"] == ""


def test_contract_evidence_failure_skips_refine_and_quarantines(
    tmp_path: Path,
) -> None:
    class MissingDirectEvidenceRunner(TopicAgentRunner):
        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            prompt = kwargs["prompt"]
            output = result.output
            if kwargs["role"] == "canonicalization":
                output["clusters"][0].update(
                    {
                        "named_problem": True,
                        "authoritative_formulation": {
                            "source_key": "lead:hubbard:book-target",
                            "citation": "Standard formulation",
                            "url": "https://example.test/book-target",
                            "exact_excerpt": "Determine whether the finite lattice admits the stated witness.",
                        },
                        "formulation_alignment": "exact",
                    }
                )
            elif kwargs["role"] in {"research", "refine"} and (
                "Finite-lattice witness" in prompt
            ):
                problem = output["problem"]
                problem["question"]["named_problem"] = True
                problem["question"]["authoritative_formulation"] = {
                    "citation": "Standard formulation",
                    "url": "https://example.test/standard",
                    "exact_excerpt": "Does the finite lattice admit the stated witness?",
                    "evidence_identifier": "missing-direct-evidence",
                }
                problem["question"]["formulation_alignment"] = "exact"
            dump_json(kwargs["output_path"], output)
            return AgentRun(output=output, metadata=result.metadata)

    runner = MissingDirectEvidenceRunner()
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="evidence-failure-no-refine",
        agent_runner=runner,
    )

    summary = pipeline.run()

    # A missing direct-evidence reference needs new information, so the
    # candidate quarantines immediately without spending a refine round.
    assert "refine" not in runner.calls
    assert len(summary["accepted_problem_ids"]) == 1
    assert len(summary["failed_candidates"]) == 1
    failed = summary["failed_candidates"][0]
    assert "must reference direct research evidence" in failed["error"]
    assert failed["refinable"] is False
    failed_state = next(
        state
        for state in pipeline.state["candidates"].values()
        if state["status"] == "research_failed"
    )
    assert failed_state["research_error_class"] == "contract_evidence"


def test_quarantined_candidate_revives_via_deferred_research_retry(
    tmp_path: Path,
) -> None:
    runner = _StubbornNarrowingRunner()
    pipeline = CampaignPipeline.start(
        _config(tmp_path),
        repository_root=Path(__file__).resolve().parents[1],
        run_id="quarantine-retry-revive",
        agent_runner=runner,
    )
    summary = pipeline.run()
    assert summary["accepted_problem_ids"] == []
    candidate_id = sorted(pipeline.state["candidates"])[0]

    deferral = pipeline.retry(candidate_id, "research", defer=True)
    assert deferral["deferred"] is True
    candidate_state = pipeline.state["candidates"][candidate_id]
    assert candidate_state["status"] == "retry_requested"
    assert "research_error" not in candidate_state
    # The stale refine round is invalidated together with the research stage.
    refine_records = [
        record
        for key, record in pipeline.state["stages"].items()
        if key.startswith(f"candidate.{candidate_id}.refine-")
    ]
    assert refine_records
    assert all(record["status"] == "invalidated" for record in refine_records)

    runner.narrow = False
    summary = pipeline.run()

    assert len(summary["accepted_problem_ids"]) == 2
    assert summary["failed_candidates"] == []
    assert pipeline.state["candidates"][candidate_id]["status"] == "accepted"


# ---------------------------------------------------------------------------
# _normalize_decomposition_support
# ---------------------------------------------------------------------------


def _make_parent_with_support(
    sources: list[tuple[str, str]],
) -> dict[str, Any]:
    return {
        "source_support": [
            {"source_key": key, "exact_excerpt": excerpt}
            for key, excerpt in sources
        ],
    }


class TestNormalizeDecompositionSupport:
    """Unit tests for CampaignPipeline._normalize_decomposition_support."""

    def test_rewrites_paraphrased_excerpt_to_parent_exact(self) -> None:
        parent = _make_parent_with_support(
            [("src-1", "The exact parent excerpt text.")]
        )
        triage = {
            "proposed_subproblems": [
                {
                    "source_support": [
                        {
                            "source_key": "src-1",
                            "exact_excerpt": "A paraphrased shorter version.",
                        }
                    ],
                }
            ]
        }

        CampaignPipeline._normalize_decomposition_support(parent, triage)

        assert (
            triage["proposed_subproblems"][0]["source_support"][0]["exact_excerpt"]
            == "The exact parent excerpt text."
        )

    def test_leaves_matching_excerpt_unchanged(self) -> None:
        parent = _make_parent_with_support(
            [("src-1", "The exact parent excerpt text.")]
        )
        triage = {
            "proposed_subproblems": [
                {
                    "source_support": [
                        {
                            "source_key": "src-1",
                            "exact_excerpt": "The exact parent excerpt text.",
                        }
                    ],
                }
            ]
        }

        CampaignPipeline._normalize_decomposition_support(parent, triage)

        assert (
            triage["proposed_subproblems"][0]["source_support"][0]["exact_excerpt"]
            == "The exact parent excerpt text."
        )

    def test_leaves_unknown_source_key_untouched(self) -> None:
        """A source_key absent from the parent must not be silently rewritten;
        the validator rejects it."""
        parent = _make_parent_with_support(
            [("src-1", "Parent excerpt.")]
        )
        triage = {
            "proposed_subproblems": [
                {
                    "source_support": [
                        {
                            "source_key": "src-UNKNOWN",
                            "exact_excerpt": "Some other source.",
                        }
                    ],
                }
            ]
        }

        CampaignPipeline._normalize_decomposition_support(parent, triage)

        support = triage["proposed_subproblems"][0]["source_support"][0]
        assert support["source_key"] == "src-UNKNOWN"
        assert support["exact_excerpt"] == "Some other source."

    def test_handles_multiple_sources_and_subproblems(self) -> None:
        parent = _make_parent_with_support(
            [
                ("src-1", "First parent excerpt."),
                ("src-2", "Second parent excerpt."),
            ]
        )
        triage = {
            "proposed_subproblems": [
                {
                    "source_support": [
                        {"source_key": "src-1", "exact_excerpt": "Paraphrase one."},
                        {"source_key": "src-2", "exact_excerpt": "Second parent excerpt."},
                    ],
                },
                {
                    "source_support": [
                        {"source_key": "src-2", "exact_excerpt": "Paraphrase two."},
                    ],
                },
            ]
        }

        CampaignPipeline._normalize_decomposition_support(parent, triage)

        sub0 = triage["proposed_subproblems"][0]["source_support"]
        assert sub0[0]["exact_excerpt"] == "First parent excerpt."
        assert sub0[1]["exact_excerpt"] == "Second parent excerpt."

        sub1 = triage["proposed_subproblems"][1]["source_support"]
        assert sub1[0]["exact_excerpt"] == "Second parent excerpt."

    def test_empty_proposed_subproblems_is_noop(self) -> None:
        parent = _make_parent_with_support([("src-1", "Parent.")])
        triage: dict[str, Any] = {"proposed_subproblems": []}

        # Should not raise.
        CampaignPipeline._normalize_decomposition_support(parent, triage)

        assert triage["proposed_subproblems"] == []

    def test_missing_proposed_subproblems_key_is_noop(self) -> None:
        parent = _make_parent_with_support([("src-1", "Parent.")])
        triage: dict[str, Any] = {}

        # Should not raise.
        CampaignPipeline._normalize_decomposition_support(parent, triage)

    def test_decomposition_succeeds_with_paraphrased_excerpts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Integration-level: when the triage LLM returns paraphrased excerpts
        in subproblem source_support, the normalization step ensures
        decomposition validation still passes (regression for the
        'decomposition child source_support must be a non-empty subset' error).
        """
        config_path = _config(tmp_path)
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["limits"]["max_decomposition_depth"] = 1
        config_path.write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        pipeline = CampaignPipeline.start(
            config_path,
            repository_root=Path(__file__).resolve().parents[1],
            run_id="normalize-paraphrased-excerpts",
            agent_runner=TopicAgentRunner(),
        )

        parent_excerpt = "The exact parent source excerpt."
        parent = {
            "candidate_id": "CAN-PARENT000001",
            "topic_id": "hubbard",
            "topic_title": "Hubbard Model",
            "canonical_title": "Parent claim",
            "canonical_statement": "Can the parent claim be established?",
            "scope": "The full claim.",
            "named_problem": False,
            "authoritative_formulation": None,
            "formulation_alignment": "not_applicable",
            "domain": "condensed-matter physics",
            "source_keys": ["lead:hubbard:parent"],
            "source_support": [
                {
                    "source_key": "lead:hubbard:parent",
                    "exact_excerpt": parent_excerpt,
                }
            ],
            "source_records": [],
            "source_open_questions": [],
        }
        triage_by_id = {
            "CAN-PARENT000001": {
                "candidate_id": "CAN-PARENT000001",
                "importance_level": "high",
                "verification_clarity": "needs_decomposition",
                "decomposition_parent_coverage": "complete",
                "assessment": "Splits into two components.",
                "proposed_subproblems": [
                    {
                        "question": "Component A?",
                        "scope": "Component A.",
                        "answer_types": ["proof"],
                        "verification_standard": "Check A.",
                        "rationale": "Isolates A.",
                        "relation_to_parent": "component",
                        "source_support": [
                            {
                                "source_key": "lead:hubbard:parent",
                                # Deliberately paraphrased — the LLM does this.
                                "exact_excerpt": "A shortened paraphrase.",
                            }
                        ],
                    },
                    {
                        "question": "Component B?",
                        "scope": "Component B.",
                        "answer_types": ["proof"],
                        "verification_standard": "Check B.",
                        "rationale": "Isolates B.",
                        "relation_to_parent": "component",
                        "source_support": [
                            {
                                "source_key": "lead:hubbard:parent",
                                # Also paraphrased, different wording.
                                "exact_excerpt": "Another paraphrase of the source.",
                            }
                        ],
                    },
                ],
            }
        }
        pipeline.state["candidates"]["CAN-PARENT000001"] = {
            "status": "canonicalized",
            "canonical_title": "Parent claim",
            "topic_id": "hubbard",
        }

        def fake_triage_frontier(
            candidates: list[dict[str, Any]], *, workers: int
        ) -> dict[str, dict[str, Any]]:
            return {
                candidate["candidate_id"]: {
                    "candidate_id": candidate["candidate_id"],
                    "importance_level": "high",
                    "verification_clarity": "clear",
                    "decomposition_parent_coverage": "not_applicable",
                    "proposed_subproblems": [],
                    "assessment": "Atomic check.",
                }
                for candidate in candidates
            }

        monkeypatch.setattr(pipeline, "_triage_candidates", fake_triage_frontier)

        # Before the fix this raised CampaignError.
        leaves, updated_triage, decompositions = (
            pipeline._decompose_unclear_candidates(
                [parent],
                triage_by_id,
                workers=1,
            )
        )

        assert len(decompositions) == 1
        assert decompositions[0]["parent_candidate_id"] == "CAN-PARENT000001"
        assert len(decompositions[0]["child_candidate_ids"]) == 2
