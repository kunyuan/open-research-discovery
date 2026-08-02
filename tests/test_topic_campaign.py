from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
import pytest

from open_research_discovery.agent import AgentRun
from open_research_discovery.campaign import CampaignError, CampaignPipeline
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
                    "importance_rationale": "It tests a concrete boundary of the model.",
                    "scientific_significance_score": 9 if finite else 7,
                    "scientific_significance_rationale": (
                        "A resolution would separate a genuine finite-size mechanism from an artifact."
                    ),
                    "expected_result": "A complete proof, counterexample, or certified bound.",
                    "answer_types": [
                        "proof",
                        "counterexample",
                        "certified numerical bound",
                    ],
                    "verification_clarity": "clear",
                    "verification_standard": "Independently replay every stated assumption and decisive check.",
                    "proposed_subproblems": [],
                    "verification_difficulty": 10 if finite else 4,
                    "verification_difficulty_rationale": "The score records reviewer burden only.",
                    "ci_status": "solution-reviewer-only",
                }
            elif role == "research":
                output = _assessment(candidate_id, finite=finite)
            elif role == "problem-reviewer":
                output = {
                    "candidate_id": candidate_id,
                    "verdict": "accept",
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


def _assessment(candidate_id: str, *, finite: bool) -> dict[str, Any]:
    title = "Finite-lattice witness" if finite else "Critical-coupling interval"
    statement = (
        "Determine whether the finite lattice admits the stated witness."
        if finite
        else "Establish or refute the stated critical-coupling interval."
    )
    return {
        "candidate_id": candidate_id,
        "canonical_title": title,
        "canonical_statement": statement,
        "definitions": [
            "The source fixes the finite model, observable, and parameter regime."
        ],
        "scope": "Only the finite model and regime stated in the source are included.",
        "aliases": [],
        "resolution_status": "still_open",
        "resolution_conclusion": "likely_open",
        "resolution_confidence": "medium",
        "literature_treatment": "Later work treats adjacent regimes but not this exact target.",
        "status_rationale": "The audited literature leaves this scoped target unresolved.",
        "checked_through": "2026-08-01",
        "major_progress_found": False,
        "major_progress_effect": "none",
        "surviving_open_core": statement,
        "post_progress_decision": "continue",
        "importance_level": "high" if finite else "medium",
        "importance_motivation": "The result would settle a concrete model boundary.",
        "scientific_significance_score": 9 if finite else 7,
        "scientific_significance_rationale": (
            "It would distinguish a physical mechanism from a finite-size artifact."
        ),
        "consequences_of_progress": "It would sharpen subsequent analytical and numerical work.",
        "current_best_result": "Adjacent parameter regimes are known, but this target is not.",
        "expected_result": "A proof, counterexample, or certified numerical bound.",
        "answer_types": ["proof", "counterexample", "certified numerical bound"],
        "verification_clarity": "clear",
        "verification_standard": (
            "Accept only after an independent reviewer checks the fixed assumptions, "
            "replays the decisive calculation, and confirms the claimed conclusion."
        ),
        "proposed_subproblems": [],
        "verification_difficulty": 10 if finite else 4,
        "verification_difficulty_rationale": "The score measures residual reviewer burden.",
        "solution_review_checklist": [
            "Confirm the submitted result uses the fixed source model and regime.",
            "Replay every decisive derivation or certified calculation.",
            "Confirm the conclusion exactly answers the canonical statement.",
        ],
        "estimated_solution_review_time": "one expert day",
        "acceptance_boundary": "Adjacent regimes or qualitative phase diagrams do not pass.",
        "ci_status": "solution-reviewer-only",
        "ci_pseudocode": [
            "check_scope()",
            "replay_decisive_result()",
            "check_conclusion()",
        ],
        "ci_runner": "expert review with deterministic replay",
        "ci_estimated_runtime": "one day",
        "ci_timeout_minutes": 1440,
        "compute": {
            "expected_scale": "one finite target",
            "cpu": "problem dependent",
            "gpu": "optional",
            "notes": "Verification may combine expert derivation review and deterministic replay.",
        },
        "evidence": [
            {
                "source": "web",
                "title": "Later scoped result",
                "identifier": "later-result",
                "url": "https://example.test/later-result",
                "date": "2025",
                "content_level": "partial_full_text",
                "relation": "adjacent_only",
                "supports": "The later result does not cover the exact finite target.",
                "direct_support": True,
            }
        ],
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

    assert len(records) == 2
    assert {record["topic_id"] for record in records} == {"alpha", "beta"}
    assert {record["source_key"] for record in records} == {
        "alpha:global_id:shared-global-question",
        "beta:global_id:shared-global-question",
    }
    assert all("Paper context:" in record["surrounding_context"] for record in records)
    assert all(
        record["exact_excerpt"] in record["surrounding_context"] for record in records
    )
    assert all(not record["author_attribution_verified"] for record in records)


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
            if kwargs["role"] != "triage":
                return result
            output = result.output
            if '"canonical_title": "Finite-lattice witness"' in kwargs["prompt"]:
                output["verification_clarity"] = "needs_decomposition"
                output["verification_standard"] = (
                    "The parent must be split before one passing artifact exists."
                )
                output["proposed_subproblems"] = [
                    {
                        "question": "Does the pinned finite lattice admit witness A?",
                        "answer_types": ["proof", "counterexample"],
                        "verification_standard": (
                            "Check witness A against every pinned finite-lattice equation."
                        ),
                        "rationale": "This isolates witness A.",
                    },
                    {
                        "question": "Does the pinned finite lattice admit witness B?",
                        "answer_types": ["proof", "counterexample"],
                        "verification_standard": (
                            "Check witness B against every pinned finite-lattice equation."
                        ),
                        "rationale": "This isolates witness B.",
                    },
                ]
            elif '"parent_candidate_id"' in kwargs["prompt"]:
                output["scientific_significance_score"] = 9
                output["verification_clarity"] = "clear"
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
