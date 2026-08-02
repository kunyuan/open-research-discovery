from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from open_research_discovery import cli
from open_research_discovery.gitlab_review_loop import ReviewRecord


def test_topic_run_cli_reports_contract_and_companion_dossier(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    topic_dir = tmp_path / "state" / "topic-123"

    class FakeOrchestrator:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def run(self, **kwargs: Any) -> Any:
            assert kwargs["sources"] == ["lkm", "web"]
            return SimpleNamespace(
                topic_id="topic-1",
                thread_id="00000000-0000-4000-8000-000000000001",
                dossier_path=topic_dir / "topic-session-dossier.json",
                ledger_path=topic_dir / "evidence-ledger.json",
                reused_search_briefs=["brief-1"],
                contracts=[{"problem_id": "ORP-123"}],
            )

    monkeypatch.setattr(cli, "CodexTopicSession", lambda **kwargs: object())
    monkeypatch.setattr(cli, "CodexRunner", lambda **kwargs: object())
    monkeypatch.setattr(cli, "TopicOrchestrator", FakeOrchestrator)

    assert (
        cli.main(
            [
                "topic",
                "run",
                "topic-1",
                "A scientific topic",
                "--state-root",
                str(tmp_path / "state"),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["thread_id"].endswith("0001")
    assert output["contracts"][0]["problem"].endswith("contracts/ORP-123.json")
    assert output["contracts"][0]["evidence"].endswith(
        "contracts/ORP-123.dossier.json"
    )


def test_review_mr_cli_uses_isolated_runner_and_posts_anchored_result(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    submission = {
        "problem_id": "ORP-123",
        "gitlab_project": "group/topic",
        "merge_request_iid": 7,
        "merge_request_url": "https://gitlab.example/group/topic/-/merge_requests/7",
        "source_branch": "problem/orp-123",
        "target_branch": "main",
        "commit_sha": "commit-1",
        "problem_path": "problems/ORP-123/problem.json",
        "problem_sha256": "a" * 64,
        "author_identity": "topic-main",
        "evidence_path": None,
        "evidence_sha256": None,
    }
    submission_path = tmp_path / "submission.json"
    submission_path.write_text(json.dumps(submission), encoding="utf-8")
    repository_dir = tmp_path / "topic-repo"
    repository_dir.mkdir()
    out = tmp_path / "review.json"
    runner_options: dict[str, Any] = {}

    def fake_runner(**kwargs: Any) -> object:
        runner_options.update(kwargs)
        return object()

    record = ReviewRecord(
        problem_id="ORP-123",
        gitlab_project="group/topic",
        merge_request_iid=7,
        merge_request_url=submission["merge_request_url"],
        source_branch="problem/orp-123",
        commit_sha="commit-1",
        problem_path="problems/ORP-123/problem.json",
        problem_sha256="a" * 64,
        author_identity="topic-main",
        reviewer_identity="reviewer-1",
        verdict="accept",
        concerns=(),
        rationale="Ready.",
        rewrite_prompt="",
        review_prompt_sha256="b" * 64,
        review_schema_sha256="c" * 64,
    )
    posted: list[ReviewRecord] = []
    monkeypatch.setattr(cli, "CodexRunner", fake_runner)
    monkeypatch.setattr(cli, "review_draft_submission", lambda **kwargs: record)
    monkeypatch.setattr(
        cli,
        "post_review_comment",
        lambda **kwargs: posted.append(kwargs["review"]) or {"verdict": "accept"},
    )

    assert (
        cli.main(
            [
                "contract",
                "review-mr",
                str(submission_path),
                "--repository-dir",
                str(repository_dir),
                "--reviewer-identity",
                "reviewer-1",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert runner_options["sandbox"] == "read-only"
    assert runner_options["network_access"] is False
    assert runner_options["ignore_rules"] is True
    assert runner_options["isolate_review_credentials"] is True
    assert posted == [record]
    assert json.loads(out.read_text(encoding="utf-8"))["commit_sha"] == "commit-1"
    assert json.loads(capsys.readouterr().out)["gitlab"]["verdict"] == "accept"
