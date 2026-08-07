from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from open_research_discovery.agent import AgentRun
from open_research_discovery.topic_orchestrator import (
    CodexTopicSession,
    EvidenceLedger,
    TopicOrchestrationResult,
    TopicOrchestrationError,
    TopicOrchestrator,
    TopicSessionTurn,
)


def _content(statement: str = "Determine whether property P always holds.") -> dict[str, Any]:
    return {
        "parent_problem_id": "",
        "subproblem_ids": [],
        "title": "A finite test of property P",
        "abstract": "This asks for a proof or finite counterexample to P.",
        "background": "Prior work proves P only in a restricted regime.",
        "references": ["must be replaced by the ledger"],
        "previous_progress": ["P is known in the restricted regime."],
        "problem_statement": statement,
        "scientific_significance": [
            {
                "field": "mathematics",
                "level": "medium",
                "description": "It determines whether the restricted theorem generalizes.",
            }
        ],
        "solution_difficulty": ["The unrestricted regime has no known invariant."],
        "verification_contracts": [
            {
                "answer_type": "proof_or_counterexample",
                "contract": "Submit a complete proof of P or a finite object violating P.",
                "ci_contract": "A submitted finite object is parsed and checked for P.",
            }
        ],
        "verification_difficulty_score": 6,
        "verification_difficulty_rationale": (
            "Finite witnesses are mechanical; a proof requires connected reasoning review."
        ),
    }


def _plan(topic_id: str, groups: int) -> dict[str, Any]:
    return {
        "domain_id": topic_id,
        "strategy_id": "lkm_topic_decomposition",
        "briefs": [
            {
                "brief_id": f"brief-{index}",
                "operator": "gap_tension" if index == 0 else "boundary_counterfactual",
                "coverage_axis": f"axis-{index}",
                "rationale": f"Search independent direction {index}.",
                "lkm_queries": [f"query {index}"],
                "web_queries": [f"web {index}"],
                "target_evidence": ["A precise gap statement."],
                "disconfirming_queries": [f"closed query {index}"],
                "distinct_from": [f"axis-{1 - index}"] if groups == 2 else [],
            }
            for index in range(groups)
        ],
    }


class FakeTopicSession:
    def __init__(self, topic_id: str, groups: int = 2) -> None:
        self.topic_id = topic_id
        self.groups = groups
        self.starts: list[str] = []
        self.resumes: list[tuple[str, str, str]] = []
        self.thread_id = str(uuid.uuid4())

    def start(self, **kwargs: Any) -> TopicSessionTurn:
        self.starts.append(kwargs["prompt"])
        output = _plan(self.topic_id, self.groups)
        kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_path"].write_text(json.dumps(output), encoding="utf-8")
        return TopicSessionTurn(output=output, metadata={"turn": "start"}, thread_id=self.thread_id)

    def resume(self, **kwargs: Any) -> TopicSessionTurn:
        prompt = kwargs["prompt"]
        schema_name = kwargs["schema_path"].name
        self.resumes.append((kwargs["thread_id"], schema_name, prompt))
        assert kwargs["thread_id"] == self.thread_id
        if schema_name == "problem-contract-content.schema.json":
            output = _content("Determine P under the clarified hypotheses H.")
        else:
            source_ids = sorted(set(re.findall(r"SRC-[A-F0-9]{16}", prompt)))
            anchor_ids = sorted(set(re.findall(r"ANC-[A-F0-9]{16}", prompt)))
            revisions = [int(value) for value in re.findall(r'"revision": (\d+)', prompt)]
            output = {
                "domain_id": self.topic_id,
                "ledger_revision": max(revisions),
                "drafts": [
                    {
                        "draft_key": "property-p",
                        "anchor_ids": [anchor_ids[0]],
                        "source_ids": [source_ids[0]],
                        "content": _content(),
                    }
                ],
            }
        kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_path"].write_text(json.dumps(output), encoding="utf-8")
        return TopicSessionTurn(output=output, metadata={"turn": "resume"}, thread_id=self.thread_id)


class FakeSearchRunner:
    def __init__(self, topic_id: str) -> None:
        self.topic_id = topic_id
        self.prompts: list[str] = []

    def run(self, **kwargs: Any) -> AgentRun:
        prompt = kwargs["prompt"]
        self.prompts.append(prompt)
        brief_id = re.search(r'"brief_id": "([^"]+)"', prompt).group(1)  # type: ignore[union-attr]
        quote = f"The unresolved boundary for {brief_id} is property P."
        output = {
            "domain_id": self.topic_id,
            "strategy_id": "lkm_topic_decomposition",
            "brief_id": brief_id,
            "sources": [
                {
                    "source_id": f"worker-{brief_id}",
                    "source": "lkm",
                    "title": "The same source",
                    "identifier": "doi:10.1234/example",
                    "url": "https://doi.org/10.1234/example",
                    "date": "2025",
                    "content_level": "partial_full_text",
                    "exact_excerpt": quote,
                    "surrounding_context": f"Before. {quote} After.",
                }
            ],
            "anchors": [
                {
                    "anchor_id": f"worker-anchor-{brief_id}",
                    "anchor_type": "explicit_gap",
                    "statement": f"Resolve P along {brief_id}.",
                    "source_ids": [f"worker-{brief_id}"],
                    "closest_prior": "P is known only in a restricted regime.",
                    "why_open": "The source states the remaining boundary.",
                    "freshness_searches": [f"{brief_id} solution"],
                }
            ],
            "search_summary": f"Searched {brief_id} and its disconfirmation query.",
        }
        return AgentRun(output=output, metadata={"brief_id": brief_id})


class EmptySearchRunner(FakeSearchRunner):
    def run(self, **kwargs: Any) -> AgentRun:
        result = super().run(**kwargs)
        output = dict(result.output)
        output["sources"] = []
        output["anchors"] = []
        output["search_summary"] = "The allowed source returned no usable evidence."
        return AgentRun(output=output, metadata=result.metadata)


def test_codex_topic_session_starts_non_ephemeral_and_resumes_exact_uuid(
    tmp_path: Path, monkeypatch: Any
) -> None:
    thread_id = str(uuid.uuid4())
    command_log = tmp_path / "commands.jsonl"
    monkeypatch.setenv("FAKE_TOPIC_THREAD", thread_id)
    monkeypatch.setenv("FAKE_TOPIC_COMMANDS", str(command_log))
    fake = tmp_path / "fake_codex.py"
    fake.write_text(
        """
import json
import os
import pathlib
import sys

if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
with pathlib.Path(os.environ["FAKE_TOPIC_COMMANDS"]).open("a") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
output = pathlib.Path(sys.argv[sys.argv.index("--output-last-message") + 1])
output.write_text(json.dumps({"ok": True}))
print(json.dumps({"type": "thread.started", "thread_id": os.environ["FAKE_TOPIC_THREAD"]}))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            }
        ),
        encoding="utf-8",
    )
    session = CodexTopicSession(
        repository_root=tmp_path, executable=f"{sys.executable} {fake}"
    )
    started = session.start(
        prompt="plan",
        schema_path=schema,
        output_path=tmp_path / "start.json",
        events_path=tmp_path / "start.jsonl",
    )
    resumed = session.resume(
        thread_id=started.thread_id,
        prompt="synthesize",
        schema_path=schema,
        output_path=tmp_path / "resume.json",
        events_path=tmp_path / "resume.jsonl",
    )
    commands = [json.loads(line) for line in command_log.read_text().splitlines()]
    assert started.thread_id == resumed.thread_id == thread_id
    assert "--ephemeral" not in commands[0]
    assert "resume" in commands[1]
    assert thread_id in commands[1]
    assert "--last" not in commands[1]


def test_evidence_ledger_deduplicates_source_and_persists_compact_context(
    tmp_path: Path,
) -> None:
    ledger = EvidenceLedger.load(topic_id="topic", path=tmp_path / "ledger.json")
    runner = FakeSearchRunner("topic")
    for index, brief_id in enumerate(("brief-0", "brief-1"), start=1):
        packet = runner.run(
            prompt=f'{{"brief_id": "{brief_id}"}}',
            role="strategy-search",
            schema_path=Path("unused"),
            output_path=Path("unused"),
            events_path=Path("unused"),
        ).output
        ledger.ingest(packet=packet, brief_id=brief_id, fingerprint=f"fp-{index}")
    ledger.save()
    reloaded = EvidenceLedger.load(topic_id="topic", path=tmp_path / "ledger.json")
    assert reloaded.revision == 2
    assert len(reloaded.data["sources"]) == 1
    assert len(next(iter(reloaded.data["sources"].values()))["observations"]) == 2
    assert len(reloaded.data["anchors"]) == 2
    delta = reloaded.synthesis_view(since_revision=1, context_chars_per_source=80)
    assert delta["since_revision"] == 1
    assert len(delta["sources"]) == 1
    assert all(
        len(item["surrounding_context"]) <= 86
        for source in delta["sources"]
        for item in source["observations"]
    )


def test_topic_orchestrator_refuses_new_contracts_without_new_anchors(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    session = FakeTopicSession("empty-evidence", groups=1)
    orchestrator = TopicOrchestrator(
        repository_root=repository_root,
        state_root=tmp_path,
        session=session,
        search_runner=EmptySearchRunner("empty-evidence"),  # type: ignore[arg-type]
        workers=1,
    )
    with pytest.raises(TopicOrchestrationError, match="no usable evidence anchors"):
        orchestrator.run(
            topic_id="empty-evidence",
            topic="A topic with no source support",
            search_groups=1,
        )
    assert len(session.starts) == 1
    assert session.resumes == []


def test_topic_orchestrator_reuses_searches_and_sends_compact_delta(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    session = FakeTopicSession("monte-carlo")
    searches = FakeSearchRunner("monte-carlo")
    orchestrator = TopicOrchestrator(
        repository_root=repository_root,
        state_root=tmp_path,
        session=session,
        search_runner=searches,  # type: ignore[arg-type]
        workers=2,
    )
    first = orchestrator.run(
        topic_id="monte-carlo", topic="Monte Carlo methods", search_groups=2
    )
    assert len(session.starts) == 1
    assert len(session.resumes) == 1
    assert len(searches.prompts) == 2
    assert all(
        "surrounding_context must also be verbatim source text" in prompt
        for prompt in searches.prompts
    )
    assert all(
        "Use $research-evidence-search" in prompt
        and "execute at least one Gaia LKM route" in prompt
        for prompt in searches.prompts
    )
    assert len(first.contracts) == 1
    assert first.contracts[0]["references"] == [
        "The same source — doi:10.1234/example — https://doi.org/10.1234/example"
    ]
    companion_path = (
        first.dossier_path.parent
        / "contracts"
        / f"{first.contracts[0]['problem_id']}.dossier.json"
    )
    companion = json.loads(companion_path.read_text())
    assert companion["problem_id"] == first.contracts[0]["problem_id"]
    assert len(companion["sources"]) == 1
    assert len(companion["anchors"]) == 1
    synthesis_prompt = session.resumes[0][2]
    assert '"since_revision": 0' in synthesis_prompt
    assert synthesis_prompt.count('"source_id": "SRC-') == 1
    assert "Original literature is an allowed dependency" in synthesis_prompt
    assert "largest source-faithful scope" in synthesis_prompt
    assert "classified as\nsolving or not solving" in synthesis_prompt
    assert "load-bearing bottleneck" in synthesis_prompt
    assert "The Topic Main Agent owns the scientific target" in synthesis_prompt
    assert "Apply a scope-ownership gate" in synthesis_prompt
    assert "choose, select, define, or delimit" in synthesis_prompt
    assert "Aim to emit 6 evidence-supported leaves" in synthesis_prompt
    assert "Do not return zero merely because" in synthesis_prompt

    second = orchestrator.run(
        topic_id="monte-carlo", topic="Monte Carlo methods", search_groups=2
    )
    assert second.thread_id == first.thread_id
    assert second.reused_search_briefs == ["brief-0", "brief-1"]
    assert len(session.starts) == 1
    assert len(session.resumes) == 1
    assert len(searches.prompts) == 2
    dossier = json.loads(second.dossier_path.read_text())
    assert dossier["thread_id"] == session.thread_id
    assert dossier["session_evidence_revision"] == 2
    assert dossier["evidence"]["coverage"]["source_count"] == 1


def test_topics_have_separate_sessions_and_noncolliding_dossiers(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    results: list[TopicOrchestrationResult] = []
    for topic_id in ("a/b", "a-b"):
        session = FakeTopicSession(topic_id, groups=1)
        result = TopicOrchestrator(
            repository_root=repository_root,
            state_root=tmp_path,
            session=session,
            search_runner=FakeSearchRunner(topic_id),  # type: ignore[arg-type]
            workers=1,
        ).run(topic_id=topic_id, topic=f"Topic {topic_id}", search_groups=1)
        results.append(result)
    assert results[0].thread_id != results[1].thread_id
    assert results[0].dossier_path != results[1].dossier_path


def test_existing_topic_session_rejects_changed_topic_text(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    session = FakeTopicSession("stable-topic", groups=1)
    orchestrator = TopicOrchestrator(
        repository_root=repository_root,
        state_root=tmp_path,
        session=session,
        search_runner=FakeSearchRunner("stable-topic"),  # type: ignore[arg-type]
        workers=1,
    )
    orchestrator.run(
        topic_id="stable-topic", topic="Original scientific topic", search_groups=1
    )
    with pytest.raises(TopicOrchestrationError, match="topic text changed"):
        orchestrator.run(
            topic_id="stable-topic", topic="A different scientific topic", search_groups=1
        )


def test_revise_contract_resumes_same_session_with_only_contract_and_review(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    session = FakeTopicSession("exact-solutions", groups=1)
    orchestrator = TopicOrchestrator(
        repository_root=repository_root,
        state_root=tmp_path,
        session=session,
        search_runner=FakeSearchRunner("exact-solutions"),  # type: ignore[arg-type]
        workers=1,
    )
    initial = orchestrator.run(
        topic_id="exact-solutions", topic="Exact solutions", search_groups=1
    )
    review = {
        "verdict": "rewrite",
        "rewrite_prompt": "State hypotheses H explicitly.",
    }
    revised = orchestrator.revise_contract(
        topic_id="exact-solutions", contract=initial.contracts[0], review_delta=review
    )
    thread_id, schema_name, prompt = session.resumes[-1]
    assert thread_id == initial.thread_id
    assert schema_name == "problem-contract-content.schema.json"
    assert "State hypotheses H explicitly." in prompt
    assert initial.contracts[0]["problem_statement"] in prompt
    assert "Evidence delta" not in prompt
    assert "not as permission to replace the\nscientific question" in prompt
    assert "largest source-faithful\nscope" in prompt
    assert "internal canonical source IDs out" in prompt
    assert (
        "alternative answer branches resolve the same quantified target" in prompt
    )
    assert "Never repair an unresolved scope" in prompt
    assert "Apply the scope-ownership gate after rewriting" in prompt
    assert revised["problem_id"] == initial.contracts[0]["problem_id"]
    assert revised["references"] == initial.contracts[0]["references"]
    assert "clarified hypotheses H" in revised["problem_statement"]
    dossier = json.loads(initial.dossier_path.read_text())
    assert dossier["revisions"][-1]["review_delta_sha256"]


def test_same_topic_runs_are_serialized_by_file_lock(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    orchestrator = TopicOrchestrator(
        repository_root=repository_root,
        state_root=tmp_path,
        session=FakeTopicSession("locked", groups=1),
        search_runner=FakeSearchRunner("locked"),  # type: ignore[arg-type]
    )
    active = 0
    maximum = 0
    guard = threading.Lock()

    def fake_run_locked(**kwargs: Any) -> TopicOrchestrationResult:
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.1)
        with guard:
            active -= 1
        return TopicOrchestrationResult(
            topic_id="locked",
            thread_id=str(uuid.uuid4()),
            ledger_path=tmp_path / "ledger",
            dossier_path=tmp_path / "dossier",
            contracts=[],
            reused_search_briefs=[],
        )

    orchestrator._run_locked = fake_run_locked  # type: ignore[method-assign]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(orchestrator.run, topic_id="locked", topic="Locked")
            for _ in range(2)
        ]
        [future.result() for future in futures]
    assert maximum == 1
