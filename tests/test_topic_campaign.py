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
    is_refinable,
)
from open_research_discovery.cli import main as cli_main
from open_research_discovery.common import dump_json
from open_research_discovery.problem_contract import (
    README_SECTIONS,
    validate_problem_readme,
)
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
        "authoritative_formulation": None,
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
                    "importance_rationale": "It tests a concrete boundary of the model.",
                    "expected_result": "A complete proof, counterexample, or certified bound.",
                    "answer_types": [
                        "proof",
                        "counterexample",
                        "certified numerical bound",
                    ],
                    "verification_standard": "Independently replay every stated assumption and decisive check.",
                    "verification_difficulty": 10 if finite else 4,
                    "verification_difficulty_rationale": "The score records reviewer burden only.",
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
            "scientific_significance": {
                "condensed-matter physics": {
                    "level": "high" if finite else "medium",
                    "description": (
                        "It would distinguish a physical mechanism from a "
                        "finite-size artifact."
                    ),
                }
            },
            "solution_difficulty": [
                "Existing arguments do not control the fixed target regime."
            ],
            "verification_contract": {
                "proof": {
                    "contract": (
                        "Accept a proof only after checking every fixed assumption "
                        "and the conclusion against the stated target."
                    ),
                    "ci_contract": None,
                },
                "counterexample": {
                    "contract": (
                        "Accept an explicit counterexample satisfying every fixed "
                        "assumption and violating the claim."
                    ),
                    "ci_contract": "Replay the witness checks against the fixed model.",
                },
                "certified numerical bound": {
                    "contract": (
                        "Accept certified bounds only when they settle the full "
                        "stated interval under the fixed model."
                    ),
                    "ci_contract": "Replay the certificate and compare its interval.",
                },
            },
            "verification_difficulty": {
                "score": 10 if finite else 4,
                "rationale": "The score measures residual reviewer burden.",
            },
        },
        "report_markdown": (
            "## Audit report\n\n"
            "The audited literature leaves this scoped target unresolved. "
            "Later work treats adjacent regimes but not this exact target."
        ),
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
    }
    triage = {"answer_types": ["proof", "counterexample", "certified numerical bound"]}
    for draft in (valid, invalid):
        CampaignPipeline._finalize_research_output(candidate, triage, draft)
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
        assert sorted(path.name for path in repo.iterdir()) == [
            ".git",
            "README.md",
            "problem.json",
        ]
        text = readme.read_text(encoding="utf-8")
        texts.append(text)
        assert [
            line[3:] for line in text.splitlines() if line.startswith("## ")
        ] == list(README_SECTIONS)
        assert "The contracts below evaluate answers" in text
        assert "## Scientific Significance" in text
    combined = "\n".join(texts)
    assert "《10000个科学难题》物理学卷" in combined
    assert "Adjacent parameter regimes are known" in combined
    assert "Overall score: `10/10`" in combined

    manifests = sorted(pipeline.run_dir.glob("candidates/*/problem.json"))
    assert len(manifests) == 2
    for manifest in manifests:
        assert (
            validate_problem(manifest, repository_root / "schemas/problem.schema.json")
            == []
        )
        problem = json.loads(manifest.read_text(encoding="utf-8"))
        matching = next(
            item
            for item in summary["solution_repositories"]
            if item["problem_id"] == problem["problem_id"]
        )
        assert Path(matching["solution_repo"], "problem.json").is_file()
    hardest = max(
        json.loads(path.read_text(encoding="utf-8"))["verification_difficulty"][
            "score"
        ]
        for path in manifests
    )
    assert hardest == 10
    ranking = json.loads(
        (pipeline.run_dir / "ranking.json").read_text(encoding="utf-8")
    )["ranking"]
    assert ranking[0]["scientific_significance_level"] in {"high", "medium"}
    assert ranking[0]["verification_difficulty"] == 10
    assert ranking[0]["ranking_lane"] == "catalog"
    calls = list(runner.calls)
    assert pipeline.run() == summary
    assert runner.calls == calls
    assert "never add finite-size" in runner.prompts["discovery"][0].lower()
    assert "discovery agent owns the scientific target" in runner.prompts[
        "discovery"
    ][0].lower()
    assert "famous or standard open problem" in runner.prompts[
        "canonicalization"
    ][0].lower()
    assert "canonicalization owns the final candidate target" in runner.prompts[
        "canonicalization"
    ][0].lower()
    canonical_prompt = " ".join(
        runner.prompts["canonicalization"][0].lower().split()
    )
    assert "literal identity with the source question is not required" in (
        canonical_prompt
    )
    assert "every candidate proceeds" in " ".join(
        runner.prompts["triage"][0].lower().split()
    )
    assert "famous or named problem" in runner.prompts["research"][0].lower()
    assert "research agent owns any surviving target" in runner.prompts[
        "research"
    ][0].lower()
    assert "authoritative formulation" in runner.prompts["problem-reviewer"][
        0
    ].lower()
    assert "scope-ownership hard gate" in runner.prompts["problem-reviewer"][
        0
    ].lower()
    assert "difference alone is never a reason to fail" in runner.prompts[
        "problem-reviewer"
    ][0].lower()
    assert "scientifically solid, consequential, concrete" in runner.prompts[
        "problem-reviewer"
    ][0].lower()


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
    for key in ("source_records", "canonical_candidates", "active_candidates"):
        assert second[key] == first[key]
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
    assert (tmp_path / f"pool-repo/pool/depublished/{withdrawn_id}.json").is_file()
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
    problem = json.loads(
        (pipeline.run_dir / f"candidates/{candidate_id}/problem.json").read_text(
            encoding="utf-8"
        )
    )
    assert problem["title"].endswith(" corrected")
    assert (allocated_repo / "problem.json").is_file()
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
        for manifest in pipeline.run_dir.glob("candidates/*/problem.json"):
            problem = json.loads(manifest.read_text(encoding="utf-8"))
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
    }
    triage = {"answer_types": ["proof", "counterexample"]}

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
            # order-free compare against the triage answer types
                "verification_contract": {
                    "counterexample": {"contract": "Check it.", "ci_contract": None},
                    "proof": {"contract": "Review it.", "ci_contract": None},
                },
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
    CampaignPipeline._validate_topic_research_contract(candidate, triage, unchanged)
    CampaignPipeline._finalize_research_output(candidate, triage, unchanged)
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
    CampaignPipeline._validate_topic_research_contract(candidate, triage, changed)
    CampaignPipeline._finalize_research_output(candidate, triage, changed)
    assert changed["_formulation_changed"] is True
    assert changed["_formulation_changed_fields"] == ["title"]
    changed_progress = changed["problem"]["resolution_audit"]["progress_assessment"]
    assert changed_progress["decision"] == "rewrite-core"

    # A real change without major progress still fails, from the computed
    # (not self-reported) diff.
    silent = draft(**{"question.canonical_statement": "A silently narrowed statement?"})
    with pytest.raises(CampaignError, match="without major progress"):
        CampaignPipeline._validate_topic_research_contract(candidate, triage, silent)


def test_triage_verification_fields_use_the_contract_boundary() -> None:
    base = {
        "answer_types": ["proof"],
        "verification_standard": "Replay the stated finite check.",
    }
    CampaignPipeline._validate_verification_fields(base, "Triage Agent")
    with pytest.raises(CampaignError, match="verification_standard"):
        CampaignPipeline._validate_verification_fields(
            {"answer_types": ["proof"]}, "Triage Agent"
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
            verification = result.output["problem"]["verification_contract"]
            result.output["problem"]["verification_contract"] = {
                "proof": verification["proof"]
            }
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
    assert "never repair verification by delegating" in refine_prompt.lower()
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
            verification = result.output["problem"]["verification_contract"]
            result.output["problem"]["verification_contract"] = {
                "proof": verification["proof"]
            }
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
            verification = result.output["problem"]["verification_contract"]
            result.output["problem"]["verification_contract"] = {
                "proof": verification["proof"]
            }
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
