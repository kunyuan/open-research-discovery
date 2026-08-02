from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from open_research_discovery.agent import AgentRun
from open_research_discovery.gitlab_review_loop import (
    DraftSubmission,
    ReviewRecord,
    post_review_comment,
    review_draft_submission,
    revise_problem_contract_draft,
    revision_instruction,
    submit_problem_contract_draft,
    write_topic_readme,
)
from open_research_discovery.problem_contract import write_problem_contract_repository


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPOSITORY_ROOT / "schemas" / "problem-contract.schema.json"


def contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "problem_id": "ORP-TEST-0001",
        "parent_problem_id": None,
        "subproblem_ids": [],
        "title": "A finite counterexample to the example bound",
        "abstract": "Determine whether the bound has a finite counterexample.",
        "background": "Objects satisfying A and B are conjectured to obey C.",
        "references": ["Example et al. (2025), The example bound."],
        "previous_progress": ["The bound holds through size ten."],
        "problem_statement": "Find a larger object satisfying A and B but not C.",
        "scientific_significance": {
            "finite combinatorics": {
                "level": "high",
                "description": "A witness would invalidate a widely used bound.",
            }
        },
        "solution_difficulty": ["Preserve A and B outside the proved regime."],
        "verification_contract": {
            "counterexample": {
                "contract": "Submit an object satisfying A and B but not C.",
                "ci_contract": "Check A, B, and C using exact arithmetic.",
            }
        },
        "verification_difficulty": {
            "score": 0,
            "rationale": "Every acceptance condition is mechanical.",
        },
    }


class FakeReviewRunner:
    sandbox = "read-only"

    def __init__(self, verdict: str = "rewrite") -> None:
        self.verdict = verdict
        self.calls = 0
        self.prompt = ""

    def run(self, **kwargs: Any) -> AgentRun:
        self.calls += 1
        self.prompt = kwargs["prompt"]
        output = {
            "problem_id": "ORP-TEST-0001",
            "verdict": self.verdict,
            "concerns": ["Clarify the allowed representation."],
            "rationale": "The mathematical boundary is sound but underspecified.",
            "rewrite_prompt": "Specify the accepted object serialization.",
        }
        kwargs["output_path"].write_text(json.dumps(output), encoding="utf-8")
        kwargs["events_path"].write_text("{}\n", encoding="utf-8")
        return AgentRun(output=output, metadata={"fake": True})


def topic_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "topic"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def test_submit_adds_problem_to_existing_topic_repo_and_opens_draft_mr(
    tmp_path: Path,
) -> None:
    repo = topic_repo(tmp_path)
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command == ["git", "rev-parse", "HEAD"]:
            stdout = "commit-001\n"
        elif command[:4] == ["glab", "api", "--method", "POST"]:
            stdout = json.dumps(
                {"iid": 7, "web_url": "https://gitlab.example/topic/-/merge_requests/7"}
            )
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    submission = submit_problem_contract_draft(
        contract=contract(),
        schema_path=SCHEMA_PATH,
        repository_dir=repo,
        gitlab_project="science/topic",
        author_identity="topic-main-1",
        evidence_dossier={"source": "Exact source context."},
        command_runner=run,
    )

    problem_path = repo / "problems" / "ORP-TEST-0001" / "problem.json"
    assert problem_path.is_file()
    assert submission.problem_path == "problems/ORP-TEST-0001/problem.json"
    assert submission.commit_sha == "commit-001"
    assert submission.problem_sha256 == hashlib.sha256(problem_path.read_bytes()).hexdigest()
    evidence_file = repo / "evidence" / "ORP-TEST-0001.json"
    assert submission.evidence_path == "evidence/ORP-TEST-0001.json"
    assert submission.evidence_sha256 == hashlib.sha256(evidence_file.read_bytes()).hexdigest()
    assert ["git", "push", "-u", "origin", "problem/orp-test-0001"] in calls
    add_command = next(command for command in calls if command[:2] == ["git", "add"])
    assert "README.md" in add_command
    assert "evidence/ORP-TEST-0001.json" in add_command
    topic_readme = (repo / "README.md").read_text(encoding="utf-8")
    assert "problems/ORP-TEST-0001/README.md" in topic_readme
    assert "Merge these MRs serially" in topic_readme
    create = next(command for command in calls if command[:4] == ["glab", "api", "--method", "POST"])
    assert any(value.startswith("title=Draft: ") for value in create)


def submission_for(raw: bytes) -> DraftSubmission:
    return DraftSubmission(
        problem_id="ORP-TEST-0001",
        gitlab_project="science/topic",
        merge_request_iid=7,
        merge_request_url="https://gitlab.example/topic/-/merge_requests/7",
        source_branch="problem/orp-test-0001",
        target_branch="main",
        commit_sha="commit-001",
        problem_path="problems/ORP-TEST-0001/problem.json",
        problem_sha256=hashlib.sha256(raw).hexdigest(),
        author_identity="topic-main-1",
    )


def test_independent_review_reads_exact_blob_and_returns_anchored_record(
    tmp_path: Path,
) -> None:
    raw = (json.dumps(contract(), ensure_ascii=False, indent=2) + "\n").encode()
    submission = submission_for(raw)
    runner = FakeReviewRunner()

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if command[:2] == ["glab", "api"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"sha": "commit-001"}), ""
            )
        assert command == [
            "git",
            "show",
            "commit-001:problems/ORP-TEST-0001/problem.json",
        ]
        return subprocess.CompletedProcess(command, 0, raw, b"")

    record = review_draft_submission(
        submission=submission,
        reviewer_identity="independent-reviewer-1",
        topic_repository_dir=topic_repo(tmp_path),
        pipeline_repository_root=REPOSITORY_ROOT,
        runner=runner,
        output_path=tmp_path / "review.json",
        events_path=tmp_path / "review.events.jsonl",
        command_runner=run,
    )

    assert record.verdict == "rewrite"
    assert record.commit_sha == submission.commit_sha
    assert record.problem_sha256 == submission.problem_sha256
    assert len(record.review_prompt_sha256) == 64
    assert len(record.review_schema_sha256) == 64
    assert "Specify the accepted object serialization" in revision_instruction(record)


def test_review_rejects_self_review_and_blob_hash_mismatch(tmp_path: Path) -> None:
    raw = (json.dumps(contract()) + "\n").encode()
    submission = submission_for(raw)
    repo = topic_repo(tmp_path)
    with pytest.raises(ValueError, match="cannot review its own"):
        review_draft_submission(
            submission=submission,
            reviewer_identity="TOPIC-MAIN-1",
            topic_repository_dir=repo,
            pipeline_repository_root=REPOSITORY_ROOT,
            runner=FakeReviewRunner(),
            output_path=tmp_path / "review.json",
            events_path=tmp_path / "events.jsonl",
        )

    runner = FakeReviewRunner()

    def wrong_blob(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if command[:2] == ["glab", "api"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"sha": "commit-001"}), ""
            )
        return subprocess.CompletedProcess(command, 0, b"{}\n", b"")

    with pytest.raises(ValueError, match="does not match"):
        review_draft_submission(
            submission=submission,
            reviewer_identity="reviewer-2",
            topic_repository_dir=repo,
            pipeline_repository_root=REPOSITORY_ROOT,
            runner=runner,
            output_path=tmp_path / "review.json",
            events_path=tmp_path / "events.jsonl",
            command_runner=wrong_blob,
        )
    assert runner.calls == 0


def test_review_rejects_a_networked_runner_before_reading_git(tmp_path: Path) -> None:
    raw = (json.dumps(contract()) + "\n").encode()
    runner = FakeReviewRunner()
    runner.network_access = True
    with pytest.raises(ValueError, match="must not have network access"):
        review_draft_submission(
            submission=submission_for(raw),
            reviewer_identity="reviewer-2",
            topic_repository_dir=topic_repo(tmp_path),
            pipeline_repository_root=REPOSITORY_ROOT,
            runner=runner,
            output_path=tmp_path / "review.json",
            events_path=tmp_path / "events.jsonl",
        )
    assert runner.calls == 0


def test_review_does_not_start_if_mr_head_changed(tmp_path: Path) -> None:
    raw = (json.dumps(contract()) + "\n").encode()
    runner = FakeReviewRunner()
    calls: list[list[str]] = []
    repo = topic_repo(tmp_path)

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"sha": "newer-commit"}), ""
        )

    with pytest.raises(RuntimeError, match="before review"):
        review_draft_submission(
            submission=submission_for(raw),
            reviewer_identity="reviewer-2",
            topic_repository_dir=repo,
            pipeline_repository_root=REPOSITORY_ROOT,
            runner=runner,
            output_path=tmp_path / "review.json",
            events_path=tmp_path / "events.jsonl",
            command_runner=run,
        )
    assert runner.calls == 0
    assert len(calls) == 1


def test_topic_index_preserves_existing_content_and_lists_all_problems(
    tmp_path: Path,
) -> None:
    repo = topic_repo(tmp_path)
    existing = contract()
    existing["problem_id"] = "ORP-TEST-0000"
    existing["title"] = "Earlier problem"
    existing_dir = repo / "problems" / "ORP-TEST-0000"
    existing_dir.mkdir(parents=True)
    write_problem_contract_repository(
        contract=existing,
        schema_path=SCHEMA_PATH,
        out_dir=existing_dir,
    )
    (repo / "README.md").write_text(
        "# Manual Topic Title\n\nCurated introduction.\n", encoding="utf-8"
    )

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command == ["git", "rev-parse", "HEAD"]:
            stdout = "commit-001\n"
        elif command[:4] == ["glab", "api", "--method", "POST"]:
            stdout = json.dumps({"iid": 7, "web_url": "https://example/mr/7"})
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    submit_problem_contract_draft(
        contract=contract(),
        schema_path=SCHEMA_PATH,
        repository_dir=repo,
        gitlab_project="science/topic",
        author_identity="topic-main-1",
        command_runner=run,
    )
    first = (repo / "README.md").read_text(encoding="utf-8")
    write_topic_readme(repository_dir=repo, schema_path=SCHEMA_PATH)
    second = (repo / "README.md").read_text(encoding="utf-8")
    assert first == second
    assert "Curated introduction." in first
    assert first.index("ORP-TEST-0000") < first.index("ORP-TEST-0001")
    assert (repo / "problems" / "ORP-TEST-0000" / "problem.json").is_file()


def test_evidence_dossier_is_separately_anchored_and_passed_to_reviewer(
    tmp_path: Path,
) -> None:
    raw = (json.dumps(contract(), ensure_ascii=False, indent=2) + "\n").encode()
    dossier = {"exact_excerpt": "A source excerpt unique to this dossier."}
    dossier_raw = (json.dumps(dossier, ensure_ascii=False, indent=2) + "\n").encode()
    submission = replace(
        submission_for(raw),
        evidence_path="evidence/ORP-TEST-0001.json",
        evidence_sha256=hashlib.sha256(dossier_raw).hexdigest(),
    )
    runner = FakeReviewRunner()

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if command[:2] == ["glab", "api"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"sha": "commit-001"}), ""
            )
        if command[-1].endswith("evidence/ORP-TEST-0001.json"):
            return subprocess.CompletedProcess(command, 0, dossier_raw, b"")
        return subprocess.CompletedProcess(command, 0, raw, b"")

    record = review_draft_submission(
        submission=submission,
        reviewer_identity="reviewer-2",
        topic_repository_dir=topic_repo(tmp_path),
        pipeline_repository_root=REPOSITORY_ROOT,
        runner=runner,
        output_path=tmp_path / "review.json",
        events_path=tmp_path / "events.jsonl",
        command_runner=run,
    )
    assert record.evidence_sha256 == submission.evidence_sha256
    assert dossier["exact_excerpt"] in runner.prompt


def review_record(verdict: str = "accept") -> ReviewRecord:
    return ReviewRecord(
        problem_id="ORP-TEST-0001",
        gitlab_project="science/topic",
        merge_request_iid=7,
        merge_request_url="https://gitlab.example/topic/-/merge_requests/7",
        source_branch="problem/orp-test-0001",
        commit_sha="commit-001",
        problem_path="problems/ORP-TEST-0001/problem.json",
        problem_sha256="a" * 64,
        author_identity="topic-main-1",
        reviewer_identity="reviewer-1",
        verdict=verdict,
        concerns=("One concern.",),
        rationale="Independent rationale.",
        rewrite_prompt="Rewrite this boundary." if verdict == "rewrite" else "",
    )


def test_review_comment_is_posted_only_for_current_mr_head(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:2] == ["glab", "api"] and "--method" not in command:
            stdout = json.dumps({"sha": "commit-001"})
        else:
            stdout = json.dumps({"id": 99})
        return subprocess.CompletedProcess(command, 0, stdout, "")

    result = post_review_comment(
        review=review_record(),
        repository_dir=tmp_path,
        command_runner=run,
    )
    assert result["verdict"] == "accept"
    assert len(calls) == 3
    status_rendered = " ".join(calls[1])
    assert "statuses/commit-001" in status_rendered
    assert "state=success" in status_rendered
    rendered = " ".join(calls[2])
    assert "Problem Contract Review: ACCEPT" in rendered
    assert "git push" not in rendered
    assert "approve" not in rendered


def test_stale_review_cannot_be_posted(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"sha": "newer-commit"}), ""
        )

    with pytest.raises(RuntimeError, match="stale"):
        post_review_comment(
            review=review_record(),
            repository_dir=tmp_path,
            command_runner=run,
        )
    assert len(calls) == 1


def test_rewrite_review_sets_failed_commit_status(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "--method" not in command:
            stdout = json.dumps({"sha": "commit-001"})
        else:
            stdout = json.dumps({"id": 100})
        return subprocess.CompletedProcess(command, 0, stdout, "")

    post_review_comment(
        review=review_record("rewrite"),
        repository_dir=tmp_path,
        command_runner=run,
    )
    assert "state=failed" in calls[1]
    assert all("approve" not in command for call in calls for command in call)


def test_rewrite_review_allows_original_topic_agent_to_update_same_mr(
    tmp_path: Path,
) -> None:
    repo = topic_repo(tmp_path)
    problem_dir = repo / "problems" / "ORP-TEST-0001"
    problem_dir.mkdir(parents=True)
    raw = (json.dumps(contract(), ensure_ascii=False, indent=2) + "\n").encode()
    problem_file = problem_dir / "problem.json"
    problem_file.write_bytes(raw)
    (problem_dir / "README.md").write_text("old\n", encoding="utf-8")
    submission = submission_for(raw)
    review = ReviewRecord(
        **{
            **review_record("rewrite").to_dict(),
            "problem_sha256": submission.problem_sha256,
            "concerns": tuple(review_record("rewrite").concerns),
        }
    )
    rev_parse_calls = 0

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal rev_parse_calls
        if command[:2] == ["glab", "api"]:
            stdout = json.dumps({"sha": "commit-001"})
        elif command == ["git", "rev-parse", "HEAD"]:
            rev_parse_calls += 1
            stdout = "commit-001\n" if rev_parse_calls == 1 else "commit-002\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    revised_contract = contract()
    revised_contract["abstract"] = "A clarified abstract after review."
    revised = revise_problem_contract_draft(
        submission=submission,
        review=review,
        contract=revised_contract,
        schema_path=SCHEMA_PATH,
        repository_dir=repo,
        author_identity="topic-main-1",
        command_runner=run,
    )
    assert revised.commit_sha == "commit-002"
    assert revised.merge_request_iid == submission.merge_request_iid
    assert json.loads(problem_file.read_text())["abstract"] == revised_contract["abstract"]
    assert revised.problem_sha256 != submission.problem_sha256
