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

from open_research_discovery import campaign as campaign_mod
from open_research_discovery.agent import (
    AgentExecutionError,
    AgentOutputError,
    AgentRun,
    file_sha256,
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
    slugify,
)
from open_research_discovery.lkm import extract_paper_open_questions
from open_research_discovery.validation import validate_problem


TOPIC_ID = "mathematics"
SOURCE_KEY = "lkm:GQ-1"
SOURCE_CONTENT = (
    "Does there exist a finite object satisfying A and B while violating C?"
)
CANONICAL_TITLE = "Finite witness for the example bound"
CANONICAL_STATEMENT = (
    "Does there exist a finite object satisfying assumptions "
    "A and B while violating bound C?"
)
CANONICAL_SCOPE = "Finite objects under the source paper's conventions."
CANONICAL_ANSWER_TYPES = ["counterexample"]


def _write_config(
    tmp_path: Path,
    name: str,
    topic_ids: list[str],
    agents_overrides: dict[str, Any] | None = None,
    limits_overrides: dict[str, Any] | None = None,
    *,
    pool_root: str = "",
    relative_paths: bool = False,
) -> Path:
    outputs = {
        "runs_root": str(tmp_path / "runs"),
        "problem_root": str(tmp_path / "problems"),
        "pool_root": pool_root,
    }
    if relative_paths:
        outputs = {"runs_root": "runs", "problem_root": "problems", "pool_root": ""}
    config = {
        "schema_version": 2,
        "name": name,
        "topics": [
            {
                "id": topic_id,
                "title": topic_id.title(),
                "query": f"Find finite targets in {topic_id}.",
                "sources": ["lkm_open_questions"],
                "seed_papers": [],
                "seed_references": [],
            }
            for topic_id in topic_ids
        ],
        "limits": {
            "questions_per_domain": 3,
            "lkm_timeout_seconds": 30,
            **{
                key: value
                for key, value in (limits_overrides or {}).items()
                if key != "papers_per_domain"
            },
        },
        "agents": {
            "model": "",
            "codex_executable": "codex",
            "sandbox": "read-only",
            "timeout_seconds": 3600,
            **(agents_overrides or {}),
        },
        "outputs": outputs,
    }
    config_path = tmp_path / f"{name}.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def _offline_citation_fetch(kind: str, identifier: str) -> dict[str, Any]:
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


def start_campaign(
    tmp_path: Path,
    name: str,
    topic_ids: list[str] | None = None,
    agents_overrides: dict[str, Any] | None = None,
    *,
    limits_overrides: dict[str, Any] | None = None,
    pool_root: str = "",
    agent_runner: Any | None = None,
    paper_collector: Any | None = None,
    citation_fetcher: Any | None = None,
) -> CampaignPipeline:
    repository_root = Path(__file__).resolve().parents[1]
    config_path = _write_config(
        tmp_path,
        name,
        topic_ids or [TOPIC_ID],
        agents_overrides,
        limits_overrides,
        pool_root=pool_root,
    )
    return CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id=name,
        agent_runner=agent_runner or FakeAgentRunner(),
        paper_collector=paper_collector or fake_collector,
        citation_fetcher=citation_fetcher or _offline_citation_fetch,
    )


def _selection_entry(
    *,
    title: str = CANONICAL_TITLE,
    statement: str = CANONICAL_STATEMENT,
    source_key: str = SOURCE_KEY,
    importance: str = "high",
    topic_id: str | None = None,
) -> dict[str, Any]:
    """One Selection Agent candidate entry (canonical plus routing fields).

    ``topic_id`` is only present on pipeline-materialized entries; the raw
    agent output never carries it (the per-topic call owns the topic).
    """

    entry = {
        "canonical_title": title,
        "canonical_statement": statement,
        "domain": TOPIC_ID,
        "source_keys": [source_key],
        "importance_level": importance,
        "assessment": (
            "A counterexample changes a standard bound; the witness is directly "
            "checkable."
        ),
    }
    if topic_id is not None:
        entry["topic_id"] = topic_id
    return entry


def _source_record() -> dict[str, Any]:
    return {
        "id": "source::open_question",
        "global_id": "GQ-1",
        "paper_id": "PAPER-1",
        "paper_title": "A paper with an explicit open question",
        "paper_doi": "10.0000/example",
        "content": SOURCE_CONTENT,
        "domain_id": TOPIC_ID,
        "topic_id": TOPIC_ID,
        "source_key": SOURCE_KEY,
        "source_kind": "lkm_open_question",
        "author_attribution_verified": False,
        "exact_excerpt": SOURCE_CONTENT,
        "surrounding_context": (
            f"{SOURCE_CONTENT}\n\nPaper context: The paper fixes a finite model."
        ),
        "source_intent": "The authors pose the finite-witness question explicitly.",
        "derivation_rationale": (
            "Copied from the dedicated LKM open-question field."
        ),
        "evidence": [],
    }


def _candidate_record(candidate_id: str) -> dict[str, Any]:
    return {
        **_selection_entry(topic_id=TOPIC_ID),
        "candidate_id": candidate_id,
        "topic_title": TOPIC_ID.title(),
        "source_records": [_source_record()],
    }


def _accept_verdict(candidate_id: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "verdict": "accept",
        "concerns": [],
        "problem": {
            key: value
            for key, value in assessment(candidate_id).items()
            if key != "audit_outcome"
        },
    }


def assessment(
    candidate_id: str,
    *,
    title: str = CANONICAL_TITLE,
    statement: str = CANONICAL_STATEMENT,
    scope: str = CANONICAL_SCOPE,
    answer_types: list[str] | None = None,
) -> dict[str, Any]:
    """Problem Schema v1.0 record content plus the audit outcome.

    The pipeline injects the mechanical fields (problem_id, status, domain,
    topic_id, repository, schema_version) during validation; they do not
    appear here.
    """

    del candidate_id, scope  # the research stage is keyed by candidate already
    contract: dict[str, Any] = {}
    for answer_type in answer_types or CANONICAL_ANSWER_TYPES:
        contract[answer_type] = {
            "contract": (
                "Submit a JSON object containing the finite witness; accept "
                "only when every stated hypothesis checks and the violation "
                "recomputes exactly."
            ),
            "ci_contract": (
                "Recompute the witness check deterministically: parse the "
                "submitted object, verify the stated assumptions, and confirm "
                "the strict violation."
            ),
        }
    return {
        "audit_outcome": "open",
        "title": title,
        "abstract": "Whether the stated finite witness exists remains open.",
        "background": (
            "A, B, and C are defined in the source record. Later work settled "
            "bounded-size cases but not the general finite regime."
        ),
        "references": [
            "A later special-case result. DOI 10.0000/later "
            "(https://example.test/later), 2025.",
            "Author manuscript of the later result. DOI 10.0000/later-manuscript "
            "(https://example.test/later-manuscript), 2025.",
        ],
        "previous_progress": [
            "The bounded-size case is settled by the 2025 special-case result; "
            "the general finite regime remains untreated in the audited "
            "literature."
        ],
        "problem_statement": statement,
        "scientific_significance": {
            "affected_field": {
                "level": "high",
                "description": (
                    "A witness would directly invalidate a standard bound used "
                    "by several later constructions."
                ),
            }
        },
        "solution_difficulty": [
            "The witness search space grows combinatorially with size.",
        ],
        "verification_contract": contract,
        "verification_difficulty": {
            "score": 0,
            "rationale": (
                "The claim is decided by one finite object; every stated check "
                "is mechanical."
            ),
        },
    }


class FakeAgentRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.prompts: list[tuple[str, str]] = []

    def _research_output(self, candidate_id: str, prompt: str) -> dict[str, Any]:
        return assessment(candidate_id)

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
        self.prompts.append((role, prompt))
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(
            json.dumps({"type": "fake", "role": role}) + "\n",
            encoding="utf-8",
        )
        if role == "discovery":
            output = {
                "domain_id": TOPIC_ID,
                "selected_open_questions": [
                    {
                        "paper_id": "PAPER-1",
                        "doi": "10.0000/example",
                        "title": "A paper with an explicit open question",
                        "global_id": "GQ-1",
                        "summary": "This explicit finite-witness question could overturn a standard bound.",
                    }
                ],
                "problem_summaries": [],
            }
        elif role == "selection":
            output = {"candidates": [_selection_entry()]}
        else:
            # Candidate stages run with cwd=<candidate dir> (research) or
            # <candidate dir>/review-workdir (review); the candidate id is the
            # directory name, not part of the prompt.
            candidate = output_path.parent.name
            assert cwd is not None and cwd.name in {candidate, "review-workdir"}
            assert (cwd / "memory.md").is_file()
            if role == "research":
                output = self._research_output(candidate, prompt)
                # The real agent also leaves its audit notes in the workdir.
                (cwd / "research-memory.md").write_text(
                    "# audit notes\n", encoding="utf-8"
                )
            elif role == "problem-reviewer":
                output = _accept_verdict(candidate)
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
                            "content": SOURCE_CONTENT,
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


def test_discovery_materializes_selected_question_summary_and_lkm_context(
    tmp_path: Path,
) -> None:
    pipeline = start_campaign(tmp_path, "discovery-handoff")

    summary = pipeline.run()

    assert summary["active_candidates"] == 1
    candidate_dir = next((pipeline.run_dir / "candidates").iterdir())
    discovery = json.loads((candidate_dir / "discovery.json").read_text(encoding="utf-8"))
    lkm = json.loads((candidate_dir / "lkm.json").read_text(encoding="utf-8"))
    memory = (candidate_dir / "memory.md").read_text(encoding="utf-8")
    assert discovery["discovery_summary"].startswith("This explicit finite-witness")
    assert lkm["source_records"][0]["global_id"] == "GQ-1"
    assert (pipeline.run_dir / lkm["source_records"][0]["lkm_graph"]).is_file()
    assert "## Discovery summary" in memory
    assert "selection" not in pipeline.agent_runner.calls


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


def test_candidate_audit_chains_run_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = object.__new__(CampaignPipeline)
    candidates = [{"candidate_id": f"CAN-{index:012X}"} for index in range(1, 4)]
    barrier = threading.Barrier(3)
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_audit(
        candidate: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        nonlocal active, max_active
        candidate_id = candidate["candidate_id"]
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
            candidate_id = kwargs["output_path"].parent.name
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

    # Repeat the real audit chain: a one-off run used to mask the shared
    # reviewer-schema write race that CI exposed only intermittently.
    for attempt in range(5):
        agents = ParallelAuditRunner()
        pipeline = start_campaign(
            tmp_path,
            f"parallel-real-audit-{attempt}",
            agents_overrides={"workers": 3},
            limits_overrides={"papers_per_domain": 1, "questions_per_domain": 3},
            agent_runner=agents,
        )
        candidates = [
            _candidate_record(f"CAN-{index:012X}")
            for index in range(1, 4)
        ]
        for candidate in candidates:
            pipeline.state["candidates"][candidate["candidate_id"]] = {
                "status": "selected"
            }
        audits = pipeline._audit_candidates(
            candidates,
            workers=3,
        )

        assert agents.max_active_research == 3
        quarantined = {
            candidate["candidate_id"]: pipeline.state["candidates"][
                candidate["candidate_id"]
            ].get("research_error")
            for candidate in candidates
            if pipeline.state["candidates"][candidate["candidate_id"]].get(
                "status"
            )
            == "research_failed"
        }
        assert quarantined == {}
        assert list(audits) == [candidate["candidate_id"] for candidate in candidates]
        assert json.loads(
            (pipeline.run_dir / "schemas" / "problem-review.schema.json").read_text(
                encoding="utf-8"
            )
        ) == campaign_mod._PROBLEM_REVIEW_SCHEMA
        for candidate in candidates:
            candidate_id = candidate["candidate_id"]
            assert agents.roles_by_candidate[candidate_id] == [
                "research",
                "problem-reviewer",
            ]
            candidate_dir = pipeline.run_dir / "candidates" / candidate_id
            assert (candidate_dir / "research.json").is_file()
            assert (candidate_dir / "problem-review-verdict.json").is_file()
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
    def fake_audit(
        candidate: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
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


def test_parallel_audit_and_compile_preserve_deterministic_problem_id_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = start_campaign(
        tmp_path,
        "parallel-audit-order",
        agents_overrides={"workers": 3},
        limits_overrides={"papers_per_domain": 1, "questions_per_domain": 3},
    )
    candidate_ids = [
        "CAN-000000000003",
        "CAN-000000000001",
        "CAN-000000000002",
    ]
    candidates = [_candidate_record(candidate_id) for candidate_id in candidate_ids]
    for candidate_id in candidate_ids:
        pipeline.state["candidates"][candidate_id] = {"status": "selected"}
    completion_order: list[str] = []
    compile_barrier = threading.Barrier(3)
    compile_lock = threading.Lock()
    active_compiles = 0
    max_active_compiles = 0
    barrier = threading.Barrier(3)
    release = {candidate_id: threading.Event() for candidate_id in candidate_ids}
    completed = {candidate_id: threading.Event() for candidate_id in candidate_ids}

    def fake_audit(
        candidate: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        candidate_id = candidate["candidate_id"]
        barrier.wait(timeout=5)
        assert release[candidate_id].wait(timeout=5)
        completion_order.append(candidate_id)
        completed[candidate_id].set()
        draft = assessment(candidate_id)
        pipeline._validate_research_output(draft, candidate)
        return (_accept_verdict(candidate_id), draft)

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
        candidate_assessment: dict[str, Any],
        verdict: dict[str, Any],
    ) -> dict[str, Any]:
        del candidate_assessment, verdict
        nonlocal active_compiles, max_active_compiles
        candidate_id = candidate["candidate_id"]
        with compile_lock:
            active_compiles += 1
            max_active_compiles = max(max_active_compiles, active_compiles)
        compile_barrier.wait(timeout=5)
        with compile_lock:
            active_compiles -= 1
        problem_id = pipeline.state["candidates"][candidate_id]["problem_id"]
        return {
            "problem_id": problem_id,
            "topic_id": candidate["topic_id"],
            "solution_repo": str(tmp_path / "problems" / problem_id),
        }

    monkeypatch.setattr(pipeline, "_discover", lambda: [])
    monkeypatch.setattr(
        pipeline, "_materialize_discovery_candidates", lambda questions: candidates
    )
    monkeypatch.setattr(pipeline, "_research_and_problem_review", fake_audit)
    monkeypatch.setattr(pipeline, "_compile", fake_compile)
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
    # Serial ID allocation follows the deterministic selection order
    # regardless of parallel audit/compile completion timing.
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
    pipeline = start_campaign(
        tmp_path,
        "parallel-audit-failure",
        agents_overrides={"workers": 3},
        limits_overrides={"papers_per_domain": 1, "questions_per_domain": 3},
    )
    candidate_ids = [
        "CAN-000000000003",
        "CAN-000000000001",
        "CAN-000000000002",
    ]
    candidates = [_candidate_record(candidate_id) for candidate_id in candidate_ids]
    for candidate_id in candidate_ids:
        pipeline.state["candidates"][candidate_id] = {"status": "selected"}
    compile_calls: list[str] = []
    ranking_calls: list[list[str]] = []

    def fake_audit(
        candidate: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        candidate_id = candidate["candidate_id"]
        if candidate_id != "CAN-000000000002":
            raise RuntimeError(f"failed {candidate_id}")
        draft = assessment(candidate_id)
        pipeline._validate_research_output(draft, candidate)
        return (_accept_verdict(candidate_id), draft)

    monkeypatch.setattr(pipeline, "_discover", lambda: [])
    monkeypatch.setattr(
        pipeline, "_materialize_discovery_candidates", lambda questions: candidates
    )
    monkeypatch.setattr(pipeline, "_research_and_problem_review", fake_audit)

    def fake_compile(candidate: dict[str, Any], *args: Any) -> dict[str, Any]:
        compile_calls.append(candidate["candidate_id"])
        return {
            "problem_id": "ORP-0001",
            "topic_id": candidate["topic_id"],
            "solution_repo": str(tmp_path / "problems" / "ORP-0001"),
        }

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
        },
        {
            "candidate_id": "CAN-000000000001",
            "error": "RuntimeError: failed CAN-000000000001",
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
    pipeline = start_campaign(
        tmp_path,
        "atomic-split",
        limits_overrides={"papers_per_domain": 1, "questions_per_domain": 2},
    )
    source_key = "global_id:GQ-SPLIT"
    questions = [
        {
            "source_key": source_key,
            "content": "First, determine exact value A. Second, construct object B.",
            "topic_id": TOPIC_ID,
            "paper_id": "PAPER-SPLIT",
            "paper_doi": "10.0000/split",
            "paper_title": "Two explicit open questions",
        }
    ]
    output = {
        "candidates": [
            _selection_entry(
                title="Determine exact value A",
                statement="Determine the exact value of A.",
                source_key=source_key,
                topic_id=TOPIC_ID,
            ),
            _selection_entry(
                title="Construct object B",
                statement="Construct an object satisfying B.",
                source_key=source_key,
                topic_id=TOPIC_ID,
            ),
        ]
    }
    candidates = pipeline._materialize_candidates(output, questions)
    assert len(candidates) == 2
    assert len(pipeline.state["active_candidate_ids"]) == 2

    duplicate_output = {
        "candidates": [
            json.loads(json.dumps(output["candidates"][0])),
            json.loads(json.dumps(output["candidates"][0])),
        ]
    }
    with pytest.raises(CampaignError, match="duplicate candidate_id"):
        pipeline._materialize_candidates(duplicate_output, questions)

    output["candidates"][0]["source_keys"] = ["unknown:source"]
    with pytest.raises(CampaignError, match="unknown source_keys"):
        pipeline._materialize_candidates(output, questions)


def test_candidate_id_collision_fallback_preserves_mathematical_case(
    tmp_path: Path,
) -> None:
    source_key = "global_id:GQ-CASE"
    upper = _selection_entry(
        title="Upper-case functions",
        statement="Is F_k ≤ c H_k?",
        source_key=source_key,
        topic_id=TOPIC_ID,
    )
    lower = _selection_entry(
        title="Lower-case functions",
        statement="Is f_k ≤ c h_k?",
        source_key=source_key,
        topic_id=TOPIC_ID,
    )
    assert _candidate_id(upper) == _candidate_id(lower)

    pipeline = start_campaign(
        tmp_path,
        "candidate-id-collision",
        limits_overrides={"papers_per_domain": 1, "questions_per_domain": 1},
    )
    questions = [
        {
            "source_key": source_key,
            "content": "Compare F_k and f_k, and H_k and h_k.",
            "topic_id": TOPIC_ID,
            "paper_id": "PAPER-CASE",
            "paper_doi": "",
            "paper_title": "Case-sensitive functions",
        }
    ]
    candidates = pipeline._materialize_candidates(
        {"candidates": [upper, lower]}, questions
    )

    assert len({candidate["candidate_id"] for candidate in candidates}) == 2


def test_invalid_selection_is_retried_by_stage_ledger(
    tmp_path: Path,
) -> None:
    class InvalidThenValidRunner(FakeAgentRunner):
        def __init__(self) -> None:
            super().__init__()
            self.selection_attempts = 0

        def run(self, **kwargs: Any) -> AgentRun:
            result = super().run(**kwargs)
            if kwargs["role"] == "selection":
                self.selection_attempts += 1
                if self.selection_attempts == 1:
                    result.output["candidates"][0]["source_keys"] = [
                        "unknown:source"
                    ]
                    dump_json(kwargs["output_path"], result.output)
            return result

    runner = InvalidThenValidRunner()
    pipeline = start_campaign(
        tmp_path,
        "selection-retry",
        limits_overrides={"papers_per_domain": 1, "questions_per_domain": 1},
        agent_runner=runner,
    )
    questions = [
        {
            "source_key": SOURCE_KEY,
            "content": SOURCE_CONTENT,
            "topic_id": TOPIC_ID,
            "paper_id": "PAPER-1",
            "paper_doi": "",
            "paper_title": "Finite witness question",
        }
    ]

    with pytest.raises(CampaignError, match="unknown source_keys"):
        pipeline._select(questions)
    assert (
        pipeline.state["stages"][f"campaign.selection.{TOPIC_ID}"]["status"]
        == "failed"
    )

    candidates = pipeline._select(questions)

    assert len(candidates) == 1
    assert runner.selection_attempts == 2
    assert pipeline.state["stages"][f"campaign.selection.{TOPIC_ID}"]["attempt"] == 2
    assert (
        pipeline.state["stages"][f"campaign.selection.{TOPIC_ID}"]["status"]
        == "completed"
    )


def test_campaign_config_paths_are_resolved_relative_to_config(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    config_path = _write_config(
        tmp_path,
        "relative",
        [TOPIC_ID],
        limits_overrides={"papers_per_domain": 1, "questions_per_domain": 1},
        relative_paths=True,
    )
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=repository_root,
        run_id="relative",
        agent_runner=FakeAgentRunner(),
        paper_collector=fake_collector,
        citation_fetcher=_offline_citation_fetch,
    )
    stored = yaml.safe_load(
        (pipeline.run_dir / "campaign.yaml").read_text(encoding="utf-8")
    )
    assert stored["outputs"]["runs_root"] == str((tmp_path / "runs").resolve())
    assert stored["outputs"]["problem_root"] == str((tmp_path / "problems").resolve())


def test_campaign_does_not_treat_total_lkm_failure_as_zero_questions(
    tmp_path: Path,
) -> None:
    def failing_collector(**_: Any) -> dict[str, Any]:
        raise RuntimeError("transport unavailable")

    pipeline = start_campaign(
        tmp_path,
        "failed",
        limits_overrides={"papers_per_domain": 1, "questions_per_domain": 1},
        paper_collector=failing_collector,
    )
    with pytest.raises(CampaignError, match="all configured source routes failed"):
        pipeline.run()
    state = json.loads((pipeline.run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"


def test_ingest_retries_paper_id_then_doi_then_title(tmp_path: Path) -> None:
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

    pipeline = start_campaign(
        tmp_path,
        "fallback",
        limits_overrides={"papers_per_domain": 1, "questions_per_domain": 1},
        paper_collector=fallback_collector,
    )
    source = {
        "domain_id": TOPIC_ID,
        "papers": [
            {
                "paper_id": "stale-paper-id",
                "doi": "10.0000/example",
                "title": "Resolved by DOI",
            }
        ],
    }


def compile_campaign(tmp_path: Path, name: str) -> CampaignPipeline:
    return start_campaign(
        tmp_path,
        name,
        limits_overrides={"papers_per_domain": 1, "questions_per_domain": 1},
        pool_root=str(tmp_path / "pool-repo"),
    )


def compile_inputs(
    pipeline: CampaignPipeline, candidate_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = _candidate_record(candidate_id)
    verdict = _accept_verdict(candidate_id)
    research_assessment = assessment(candidate_id)
    pipeline._validate_research_output(research_assessment, candidate)
    return candidate, research_assessment, verdict


def compile_slug(research_assessment: dict[str, Any]) -> str:
    return slugify(str(research_assessment["title"]))[:72].strip("-")


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
    candidate, research_assessment, verdict = compile_inputs(pipeline, candidate_id)
    compiled = pipeline._compile(candidate, research_assessment, verdict)
    repo_dir = Path(compiled["problem_repo"])
    assert compiled["problem_id"] == "ORP-0001"

    # Simulate a crash after the repository was recorded but before
    # compile.json was written, leaving a partial repository behind.
    compile_path = pipeline.run_dir / "candidates" / candidate_id / "compile.json"
    compile_path.unlink()
    (repo_dir / "README.md").unlink()
    (repo_dir / "stray.txt").write_text("partial", encoding="utf-8")

    recompiled = pipeline._compile(candidate, research_assessment, verdict)
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
    candidate, research_assessment, verdict = compile_inputs(pipeline, candidate_id)
    compiled = pipeline._compile(candidate, research_assessment, verdict)
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

    assert pipeline._compile(candidate, research_assessment, verdict) == compiled
    assert notes.read_text(encoding="utf-8") == "preserve this user-owned work\n"

    shutil.rmtree(repo_dir / ".git")
    with pytest.raises(CampaignError, match="lost its independent Git metadata"):
        pipeline._compile(candidate, research_assessment, verdict)
    assert notes.read_text(encoding="utf-8") == "preserve this user-owned work\n"


def test_cached_compile_rejects_rewritten_git_history(tmp_path: Path) -> None:
    pipeline = compile_campaign(tmp_path, "cached-git-history-rewrite")
    candidate_id = "CAN-AAAA00000010"
    pipeline.state["candidates"][candidate_id] = {}
    candidate, research_assessment, verdict = compile_inputs(pipeline, candidate_id)
    compiled = pipeline._compile(candidate, research_assessment, verdict)
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
        pipeline._compile(candidate, research_assessment, verdict)


def test_compile_cleans_partial_repository_after_produce_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = compile_campaign(tmp_path, "produce-failure")
    candidate_id = "CAN-AAAA00000003"
    pipeline.state["candidates"][candidate_id] = {}
    candidate, research_assessment, verdict = compile_inputs(pipeline, candidate_id)
    repo_dir = tmp_path / "problems" / f"ORP-0001-{compile_slug(research_assessment)}"

    monkeypatch.setattr(
        "open_research_discovery.campaign.validate_problem",
        lambda *args, **kwargs: ["injected validation failure"],
    )
    with pytest.raises(CampaignError, match="compiled problem ORP-0001 is invalid"):
        pipeline._compile(candidate, research_assessment, verdict)

    # The partial build was removed; the empty reservation remains so no
    # other campaign can reuse the problem ID.
    assert repo_dir.is_dir()
    assert list(repo_dir.iterdir()) == []

    monkeypatch.undo()
    compiled = pipeline._compile(candidate, research_assessment, verdict)
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
    # The lock file is a file, not a directory, and never matches the ORP-* scan.
    assert not re.match(r"ORP-(\d+)", lock_path.name)
    scanned = [path.name for path in (tmp_path / "problems").iterdir() if path.is_dir()]
    assert scanned == ["ORP-0001-reserved-problem"]

    # The empty reserved directory still counts as a used problem ID.
    second_candidate_id = "CAN-AAAA00000005"
    pipeline.state["candidates"][second_candidate_id] = {}
    next_id, _ = pipeline._reserve_problem_repo(second_candidate_id, "another-problem")
    assert next_id == "ORP-0002"
    assert repo_dir.is_dir()


def test_problem_manifest_injects_pipeline_fields(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    pipeline = compile_campaign(tmp_path, "manifest-inject")
    candidate = _candidate_record("CAN-AAAA00000006")

    draft = assessment("CAN-AAAA00000006")
    pipeline._validate_research_output(draft, candidate)
    assert draft["status"] == "open"
    manifest = pipeline._problem_manifest(
        "ORP-0001", candidate, draft, repo_slug="ORP-0001-example"
    )
    assert manifest["problem_id"] == "ORP-0001"
    assert manifest["status"] == "ready"
    assert manifest["repository"] == {"kind": "solution", "slug": "ORP-0001-example"}
    manifest_path = tmp_path / "manifest.yaml"
    dump_yaml(manifest_path, manifest)
    assert (
        validate_problem(
            manifest_path,
            repository_root / "schemas" / "problem.schema.json",
        )
        == []
    )


def test_campaign_defaults_to_32_workers(tmp_path: Path) -> None:
    pipeline = start_campaign(tmp_path, "default-32-workers", ["alpha"])

    assert pipeline.workers == 32
    assert pipeline.networked_workers == 32


def discovery_output(domain_id: str) -> dict[str, Any]:
    return {
        "domain_id": domain_id,
        "selected_open_questions": [
            {
                "paper_id": f"PAPER-{domain_id}",
                "doi": "",
                "title": f"A {domain_id} paper with an explicit open question",
                "global_id": f"GQ-{domain_id}",
                "summary": "A selected LKM open question for concurrency coverage.",
            }
        ],
        "problem_summaries": [],
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
        cwd: Path | None = None,
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


def _fake_ingest_domain(
    source: dict[str, Any], domain_id: str, domain_dir: Path, source_modes: list[str]
) -> dict[str, Any]:
    return {
        "source_records": [
            {"domain_id": domain_id, "source_key": f"lead:{domain_id}:test"}
        ],
        "open_questions": [],
    }


def test_discovery_runs_domains_in_parallel_and_merges_in_config_order(
    tmp_path: Path,
) -> None:
    runner = ParallelDiscoveryRunner(3, slow_domain="alpha")
    pipeline = start_campaign(
        tmp_path,
        "parallel-discovery",
        ["alpha", "beta", "gamma"],
        {"workers": 3},
        agent_runner=runner,
    )

    pipeline._ingest_domain = _fake_ingest_domain  # type: ignore[method-assign]
    records = pipeline._discover()

    assert runner.max_active == 3
    # alpha finished last, but the merge follows the configured domain order.
    assert runner.completed[-1] == "alpha"
    assert [r["domain_id"] for r in records] == ["alpha", "beta", "gamma"]
    for domain_id in ("alpha", "beta", "gamma"):
        artifact = json.loads(
            (pipeline.run_dir / "domains" / domain_id / "source-papers.json").read_text(
                encoding="utf-8"
            )
        )
        assert artifact["domain_id"] == domain_id
        assert artifact["papers"][0]["paper_id"] == f"PAPER-{domain_id}"
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
            cwd: Path | None = None,
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

    pipeline = start_campaign(
        tmp_path,
        "serial-discovery",
        ["alpha", "beta", "gamma"],
        {"workers": 1},
        agent_runner=SerialDiscoveryRunner(),
    )

    pipeline._ingest_domain = _fake_ingest_domain  # type: ignore[method-assign]
    records = pipeline._discover()

    assert max_active == 1
    assert events == [
        "start:alpha",
        "end:alpha",
        "start:beta",
        "end:beta",
        "start:gamma",
        "end:gamma",
    ]
    assert [r["domain_id"] for r in records] == ["alpha", "beta", "gamma"]


class GoverningRunner:
    """Tracks concurrent networked and non-networked agent invocations."""

    def __init__(self, selection_parties: int) -> None:
        self.selection_barrier = threading.Barrier(selection_parties)
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
        cwd: Path | None = None,
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
        elif role == "selection":
            match = re.search(r"Topic id: (\S+)", prompt)
            assert match is not None
            with self.lock:
                self.plain_active += 1
                self.max_plain_active = max(self.max_plain_active, self.plain_active)
            self.selection_barrier.wait(timeout=5)
            with self.lock:
                self.plain_active -= 1
            output = {"candidates": []}
        else:
            raise AssertionError(role)
        return AgentRun(output=output, metadata={"exit_code": 0, "role": role})


def test_networked_workers_bound_only_networked_roles(tmp_path: Path) -> None:
    runner = GoverningRunner(3)
    pipeline = start_campaign(
        tmp_path,
        "networked-governance",
        ["alpha", "beta", "gamma"],
        {"workers": 3, "networked_workers": 1, "retries": 0},
        agent_runner=runner,
    )

    pipeline._ingest_domain = _fake_ingest_domain  # type: ignore[method-assign]
    records = pipeline._discover()
    assert [r["domain_id"] for r in records] == ["alpha", "beta", "gamma"]
    # workers=3 allows three discovery threads, but the shared semaphore
    # serializes the networked role.
    assert runner.max_networked_active == 1

    candidates = pipeline._select(records)
    assert candidates == []
    # Non-networked roles are not throttled by networked_workers.
    assert runner.max_plain_active == 3


def _alpha_source_record() -> dict[str, Any]:
    return {
        "source_key": "lead:alpha:1",
        "content": "Determine whether the alpha model admits the stated witness.",
        "topic_id": "alpha",
        "source_kind": "web",
        "paper_id": "",
        "paper_doi": "",
        "paper_title": "Alpha witness source",
    }


def _alpha_selection_output() -> dict[str, Any]:
    return {
        "candidates": [
            _selection_entry(
                title="Alpha witness",
                statement="Determine whether the alpha model admits the stated witness.",
                source_key="lead:alpha:1",
            )
        ]
    }


class FlakySelectionRunner:
    """Fails the first ``failures`` invocations, then returns valid selection."""

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
        cwd: Path | None = None,
    ) -> AgentRun:
        assert role == "selection"
        self.calls += 1
        if self.remaining:
            self.remaining -= 1
            raise RuntimeError("transport unavailable")
        return AgentRun(
            output=_alpha_selection_output(),
            metadata={"exit_code": 0, "role": role},
        )


def test_failed_agent_invocations_retry_then_succeed(tmp_path: Path) -> None:
    runner = FlakySelectionRunner(2)
    pipeline = start_campaign(
        tmp_path,
        "retry-success",
        ["alpha"],
        {"retries": 2, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    candidates = pipeline._select([_alpha_source_record()])

    assert len(candidates) == 1
    assert runner.calls == 3
    assert (
        pipeline.state["stages"]["campaign.selection.alpha"]["status"]
        == "completed"
    )


def test_agent_invocation_retry_exhaustion_fails(tmp_path: Path) -> None:
    runner = FlakySelectionRunner(5)
    pipeline = start_campaign(
        tmp_path,
        "retry-exhaustion",
        ["alpha"],
        {"retries": 1, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    with pytest.raises(RuntimeError, match="transport unavailable"):
        pipeline._select([_alpha_source_record()])

    assert runner.calls == 2
    assert (
        pipeline.state["stages"]["campaign.selection.alpha"]["status"] == "failed"
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
            cwd: Path | None = None,
        ) -> AgentRun:
            del prompt, schema_path, output_path, events_path
            self.calls += 1
            raise AgentExecutionError(
                f"{role} timed out after 2s; killed process group"
            )

    runner = TimeoutRunner()
    pipeline = start_campaign(
        tmp_path,
        "retry-timeout",
        ["alpha"],
        {"retries": 1, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    with pytest.raises(AgentExecutionError, match="timed out after 2s"):
        pipeline._select([_alpha_source_record()])

    assert runner.calls == 2
    assert (
        pipeline.state["stages"]["campaign.selection.alpha"]["status"] == "failed"
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
            cwd: Path | None = None,
        ) -> AgentRun:
            del prompt, schema_path, output_path, events_path
            self.calls += 1
            raise AgentOutputError(
                f"{role} output failed schema validation: missing field"
            )

    runner = ContractFailureRunner()
    pipeline = start_campaign(
        tmp_path,
        "retry-contract-failure",
        ["alpha"],
        {"retries": 2, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    with pytest.raises(AgentOutputError):
        pipeline._select([_alpha_source_record()])
    assert runner.calls == 1


def test_agent_validator_failures_are_not_retried(tmp_path: Path) -> None:
    class UnknownSourceKeyRunner:
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
            cwd: Path | None = None,
        ) -> AgentRun:
            del prompt, schema_path, output_path, events_path
            self.calls += 1
            return AgentRun(
                output={
                    "candidates": [
                        _selection_entry(
                            title="Alpha witness",
                            statement="Determine whether the alpha model admits the stated witness.",
                            source_key="lead:alpha:unknown",
                        )
                    ]
                },
                metadata={"exit_code": 0, "role": role},
            )

    runner = UnknownSourceKeyRunner()
    pipeline = start_campaign(
        tmp_path,
        "retry-validator-failure",
        ["alpha"],
        {"retries": 2, "retry_backoff_seconds": 0},
        agent_runner=runner,
    )

    with pytest.raises(CampaignError, match="unknown source_keys"):
        pipeline._select([_alpha_source_record()])
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
    config_path = _write_config(
        tmp_path, "invalid-governance", ["alpha"], agents_overrides=override
    )

    with pytest.raises(CampaignError, match="invalid campaign config"):
        CampaignPipeline.start(
            config_path,
            repository_root=repository_root,
            run_id="invalid-governance",
            agent_runner=FakeAgentRunner(),
            paper_collector=fake_collector,
        )
