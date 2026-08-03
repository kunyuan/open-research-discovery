from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from .benchmark import (
    evaluate_benchmark,
    score_benchmark,
    validate_benchmark_dataset,
)
from .agent import CodexRunner
from .campaign import CampaignPipeline, resolve_run_dir
from .contract_agents import review_problem_contract, rewrite_problem_contract
from .gitlab_review_loop import (
    DraftSubmission,
    ReviewRecord,
    post_review_comment,
    review_draft_submission,
    revise_problem_contract_draft,
    submit_problem_contract_draft,
)
from .gitlab_publication import publish_problem_contract_to_gitlab
from .problem_contract import (
    load_problem_contract,
    render_problem_contract_readme,
    require_valid_problem_contract,
    validate_problem_contract,
)
from .topic_orchestrator import CodexTopicSession, TopicOrchestrator


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _add_run_locator(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run", help="campaign directory or run id")
    parser.add_argument(
        "--runs-root",
        type=Path,
        help="required when RUN is an id rather than a directory",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discovery",
        description=(
            "Generate audited research-problem repositories. "
            "Benchmark subcommands are separate and explicit."
        ),
    )
    root = parser.add_subparsers(dest="resource", required=True)

    campaign = root.add_parser(
        "campaign",
        help="default problem-generation workflow",
    )
    campaign_actions = campaign.add_subparsers(dest="action", required=True)
    run = campaign_actions.add_parser("run")
    run.add_argument("config", type=Path)
    run.add_argument("--run-id")

    resume = campaign_actions.add_parser("resume")
    _add_run_locator(resume)

    status = campaign_actions.add_parser("status")
    _add_run_locator(status)

    benchmark = root.add_parser(
        "benchmark",
        help="offline, field-level Problem Contract review benchmark",
    )
    benchmark_actions = benchmark.add_subparsers(dest="action", required=True)
    score = benchmark_actions.add_parser("score")
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--gold", type=Path, required=True)
    score.add_argument("--out", type=Path)
    evaluate = benchmark_actions.add_parser("evaluate")
    evaluate.add_argument("dataset", type=Path)
    evaluate.add_argument("--out", type=Path, required=True)
    evaluate.add_argument("--workers", type=int, default=1)
    evaluate.add_argument("--codex-executable", default="codex")
    evaluate.add_argument("--model", default="")
    evaluate.add_argument("--timeout-seconds", type=int, default=3600)
    evaluate.add_argument(
        "--case-id",
        action="append",
        help="evaluate only this case; repeat for multiple cases",
    )
    evaluate.add_argument(
        "--resume",
        action="store_true",
        help="reuse existing schema-valid predictions and retry missing cases",
    )
    validate = benchmark_actions.add_parser("validate")
    validate.add_argument("dataset", type=Path)
    validate.add_argument("--inputs-only", action="store_true")

    case = root.add_parser("case")
    case_actions = case.add_subparsers(dest="action", required=True)
    retry = case_actions.add_parser("retry")
    _add_run_locator(retry)
    retry.add_argument("candidate_id")
    retry.add_argument(
        "stage", choices=("triage", "research", "problem-review", "compile")
    )
    retry.add_argument(
        "--defer",
        action="store_true",
        help=(
            "only invalidate the stage and mark the candidate retry_requested; "
            "a later campaign resume executes the retry in the parallel audit"
        ),
    )

    topic = root.add_parser(
        "topic",
        help="run or resume one persistent Topic Main Agent",
    )
    topic_actions = topic.add_subparsers(dest="action", required=True)
    topic_run = topic_actions.add_parser("run")
    topic_run.add_argument("topic_id")
    topic_run.add_argument("topic")
    topic_run.add_argument("--state-root", type=Path, required=True)
    topic_run.add_argument(
        "--source",
        dest="sources",
        action="append",
        choices=("lkm", "web"),
        help="allowed evidence source; repeat to enable both (default: both)",
    )
    topic_run.add_argument("--search-groups", type=int, default=4)
    topic_run.add_argument("--max-contracts", type=int, default=6)
    topic_run.add_argument("--workers", type=int, default=4)
    topic_run.add_argument("--codex-executable", default="codex")
    topic_run.add_argument("--model", default="")
    topic_run.add_argument("--timeout-seconds", type=int, default=3600)

    topic_revise = topic_actions.add_parser("revise")
    topic_revise.add_argument("topic_id")
    topic_revise.add_argument("problem", type=Path)
    topic_revise.add_argument("review", type=Path)
    topic_revise.add_argument("--state-root", type=Path, required=True)
    topic_revise.add_argument("--out", type=Path, required=True)
    topic_revise.add_argument("--codex-executable", default="codex")
    topic_revise.add_argument("--model", default="")
    topic_revise.add_argument("--timeout-seconds", type=int, default=3600)
    contract = root.add_parser(
        "contract",
        help="validate, render, review, rewrite, or publish a Problem Contract",
    )
    contract_actions = contract.add_subparsers(dest="action", required=True)

    contract_validate = contract_actions.add_parser("validate")
    contract_validate.add_argument("problem", type=Path)

    render = contract_actions.add_parser("render")
    render.add_argument("problem", type=Path)
    render.add_argument("--out", type=Path, required=True)

    review = contract_actions.add_parser("review")
    review.add_argument("problem", type=Path)
    review.add_argument("--out", type=Path, required=True)
    review.add_argument("--codex-executable", default="codex")
    review.add_argument("--model", default="")
    review.add_argument("--timeout-seconds", type=int, default=3600)

    rewrite = contract_actions.add_parser("rewrite")
    rewrite.add_argument("problem", type=Path)
    instruction = rewrite.add_mutually_exclusive_group(required=True)
    instruction.add_argument("--prompt")
    instruction.add_argument("--prompt-file", type=Path)
    rewrite.add_argument("--out", type=Path, required=True)
    rewrite.add_argument("--codex-executable", default="codex")
    rewrite.add_argument("--model", default="")
    rewrite.add_argument("--timeout-seconds", type=int, default=3600)

    publish = contract_actions.add_parser("publish")
    publish.add_argument("problem", type=Path)
    publish.add_argument("--out-dir", type=Path, required=True)
    publish.add_argument("--gitlab-project", required=True)
    publish.add_argument("--gitlab-host", default="")
    publish.add_argument(
        "--visibility",
        choices=("private", "internal", "public"),
        default="private",
    )

    submit = contract_actions.add_parser(
        "submit",
        help="submit a contract to an existing topic repo as a Draft MR",
    )
    submit.add_argument("problem", type=Path)
    submit.add_argument("--repository-dir", type=Path, required=True)
    submit.add_argument("--gitlab-project", required=True)
    submit.add_argument("--author-identity", required=True)
    submit.add_argument("--evidence", type=Path)
    submit.add_argument("--topic-title", default="")
    submit.add_argument("--target-branch", default="main")
    submit.add_argument("--source-branch", default="")
    submit.add_argument("--gitlab-host", default="")
    submit.add_argument("--out", type=Path, required=True)

    review_mr = contract_actions.add_parser(
        "review-mr",
        help="independently review the exact contract at a Draft MR head",
    )
    review_mr.add_argument("submission", type=Path)
    review_mr.add_argument("--repository-dir", type=Path, required=True)
    review_mr.add_argument("--reviewer-identity", required=True)
    review_mr.add_argument("--gitlab-host", default="")
    review_mr.add_argument("--out", type=Path, required=True)
    review_mr.add_argument("--codex-executable", default="codex")
    review_mr.add_argument("--model", default="")
    review_mr.add_argument("--timeout-seconds", type=int, default=3600)

    update_draft = contract_actions.add_parser(
        "update-draft",
        help="push a Topic Main Agent revision to the same Draft MR",
    )
    update_draft.add_argument("submission", type=Path)
    update_draft.add_argument("review", type=Path)
    update_draft.add_argument("problem", type=Path)
    update_draft.add_argument("--repository-dir", type=Path, required=True)
    update_draft.add_argument("--author-identity", required=True)
    update_draft.add_argument("--gitlab-host", default="")
    update_draft.add_argument("--out", type=Path, required=True)
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _load_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _load_submission(path: Path) -> DraftSubmission:
    return DraftSubmission(**_load_json_object(path))


def _load_review_record(path: Path) -> ReviewRecord:
    value = _load_json_object(path)
    concerns = value.get("concerns")
    if not isinstance(concerns, list) or not all(
        isinstance(item, str) for item in concerns
    ):
        raise ValueError("review concerns must be a JSON string array")
    return ReviewRecord(**{**value, "concerns": tuple(concerns)})


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = repository_root()
    contract_schema = repo / "schemas" / "problem-contract.schema.json"
    if args.resource == "topic":
        session = CodexTopicSession(
            repository_root=repo,
            executable=args.codex_executable,
            model=args.model,
            sandbox="read-only",
            timeout_seconds=args.timeout_seconds,
        )
        orchestrator = TopicOrchestrator(
            repository_root=repo,
            state_root=args.state_root.resolve(),
            session=session,
            search_runner=CodexRunner(
                repository_root=repo,
                executable=args.codex_executable,
                model=args.model,
                sandbox="read-only",
                networked_sandbox="workspace-write",
                network_access=True,
                timeout_seconds=args.timeout_seconds,
            ),
            workers=getattr(args, "workers", 1),
        )
        if args.action == "run":
            result = orchestrator.run(
                topic_id=args.topic_id,
                topic=args.topic,
                search_groups=args.search_groups,
                sources=args.sources or ["lkm", "web"],
                max_contracts=args.max_contracts,
            )
            topic_dir = result.dossier_path.parent
            _print(
                {
                    "topic_id": result.topic_id,
                    "thread_id": result.thread_id,
                    "dossier": str(result.dossier_path),
                    "evidence_ledger": str(result.ledger_path),
                    "reused_search_briefs": result.reused_search_briefs,
                    "contracts": [
                        {
                            "problem_id": contract["problem_id"],
                            "problem": str(
                                topic_dir
                                / "contracts"
                                / f"{contract['problem_id']}.json"
                            ),
                            "evidence": str(
                                topic_dir
                                / "contracts"
                                / f"{contract['problem_id']}.dossier.json"
                            ),
                        }
                        for contract in result.contracts
                    ],
                }
            )
            return 0
        contract_path = args.problem.resolve()
        problem = load_problem_contract(contract_path)
        review_record = _load_review_record(args.review.resolve())
        if review_record.verdict != "rewrite":
            raise ValueError("only a rewrite review can resume the Topic Main Agent")
        if review_record.problem_id != problem["problem_id"]:
            raise ValueError("review problem_id does not match the contract")
        if hashlib.sha256(contract_path.read_bytes()).hexdigest() != review_record.problem_sha256:
            raise ValueError("review is not anchored to this exact problem.json")
        revised = orchestrator.revise_contract(
            topic_id=args.topic_id,
            contract=problem,
            review_delta=review_record.to_dict(),
        )
        _write_json(args.out.resolve(), revised)
        _print({"problem_id": revised["problem_id"], "problem": str(args.out)})
        return 0
    if args.resource == "contract":
        if args.action == "review-mr":
            submission = _load_submission(args.submission.resolve())
            runner = CodexRunner(
                repository_root=repo,
                executable=args.codex_executable,
                model=args.model,
                sandbox="read-only",
                networked_sandbox="read-only",
                network_access=False,
                timeout_seconds=args.timeout_seconds,
                ignore_rules=True,
                isolate_review_credentials=True,
            )
            output = args.out.resolve()
            record = review_draft_submission(
                submission=submission,
                reviewer_identity=args.reviewer_identity,
                topic_repository_dir=args.repository_dir.resolve(),
                pipeline_repository_root=repo,
                runner=runner,
                output_path=output.with_suffix(".agent.json"),
                events_path=output.with_suffix(".events.jsonl"),
                gitlab_host=args.gitlab_host,
            )
            _write_json(output, record.to_dict())
            posted = post_review_comment(
                review=record,
                repository_dir=args.repository_dir.resolve(),
                gitlab_host=args.gitlab_host,
            )
            _print({"review": record.to_dict(), "gitlab": posted})
            return 0
        if args.action == "update-draft":
            submission = _load_submission(args.submission.resolve())
            review_record = _load_review_record(args.review.resolve())
            problem = load_problem_contract(args.problem.resolve())
            revised_submission = revise_problem_contract_draft(
                submission=submission,
                review=review_record,
                contract=problem,
                schema_path=contract_schema,
                repository_dir=args.repository_dir.resolve(),
                author_identity=args.author_identity,
                gitlab_host=args.gitlab_host,
            )
            _write_json(args.out.resolve(), revised_submission.to_dict())
            _print(revised_submission.to_dict())
            return 0
        problem = load_problem_contract(args.problem.resolve())
        if args.action == "validate":
            errors = validate_problem_contract(problem, contract_schema)
            _print({"valid": not errors, "errors": errors})
            return 0 if not errors else 1
        require_valid_problem_contract(problem, contract_schema)
        if args.action == "render":
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                render_problem_contract_readme(problem), encoding="utf-8"
            )
            _print({"problem_id": problem["problem_id"], "readme": str(args.out)})
            return 0
        if args.action in {"review", "rewrite"}:
            runner = CodexRunner(
                repository_root=repo,
                executable=args.codex_executable,
                model=args.model,
                sandbox="read-only",
                networked_sandbox="read-only",
                network_access=False,
                timeout_seconds=args.timeout_seconds,
                ignore_rules=args.action == "review",
                isolate_review_credentials=args.action == "review",
            )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            events_path = args.out.with_suffix(".events.jsonl")
            if args.action == "review":
                result = review_problem_contract(
                    contract=problem,
                    repository_root=repo,
                    runner=runner,
                    output_path=args.out,
                    events_path=events_path,
                )
            else:
                instruction_text = (
                    args.prompt
                    if args.prompt is not None
                    else args.prompt_file.read_text(encoding="utf-8")
                )
                result = rewrite_problem_contract(
                    contract=problem,
                    instruction=instruction_text,
                    repository_root=repo,
                    runner=runner,
                    agent_output_path=args.out.with_suffix(".agent.json"),
                    events_path=events_path,
                    output_path=args.out,
                )
            _print(result)
            return 0
        if args.action == "publish":
            _print(
                publish_problem_contract_to_gitlab(
                    contract=problem,
                    schema_path=contract_schema,
                    out_dir=args.out_dir.resolve(),
                    gitlab_project=args.gitlab_project,
                    gitlab_host=args.gitlab_host,
                    visibility=args.visibility,
                )
            )
            return 0
        if args.action == "submit":
            submission = submit_problem_contract_draft(
                contract=problem,
                schema_path=contract_schema,
                repository_dir=args.repository_dir.resolve(),
                gitlab_project=args.gitlab_project,
                author_identity=args.author_identity,
                target_branch=args.target_branch,
                source_branch=args.source_branch,
                topic_title=args.topic_title,
                evidence_dossier=args.evidence.resolve() if args.evidence else None,
                gitlab_host=args.gitlab_host,
            )
            _write_json(args.out.resolve(), submission.to_dict())
            _print(submission.to_dict())
            return 0
        raise AssertionError("unreachable")
    if args.resource == "campaign" and args.action == "run":
        pipeline = CampaignPipeline.start(
            args.config, repository_root=repo, run_id=args.run_id
        )
        summary = pipeline.run()
        _print({"run_dir": str(pipeline.run_dir), "summary": summary})
        return 0
    if args.resource == "benchmark" and args.action == "evaluate":
        runner = CodexRunner(
            repository_root=repo,
            executable=args.codex_executable,
            model=args.model,
            sandbox="read-only",
            networked_sandbox="read-only",
            network_access=False,
            timeout_seconds=args.timeout_seconds,
        )
        _print(
            evaluate_benchmark(
                dataset_dir=args.dataset.resolve(),
                out_dir=args.out.resolve(),
                input_schema=repo / "schemas" / "benchmark" / "input.schema.json",
                prediction_schema=repo
                / "schemas"
                / "benchmark"
                / "prediction.schema.json",
                problem_schema=repo
                / "schemas"
                / "problem-contract.schema.json",
                runner=runner,
                workers=args.workers,
                case_ids=set(args.case_id) if args.case_id else None,
                resume=args.resume,
            )
        )
        return 0
    if args.resource == "benchmark" and args.action == "validate":
        _print(
            validate_benchmark_dataset(
                dataset_dir=args.dataset.resolve(),
                input_schema=repo / "schemas" / "benchmark" / "input.schema.json",
                prediction_schema=repo
                / "schemas"
                / "benchmark"
                / "prediction.schema.json",
                gold_schema=repo / "schemas" / "benchmark" / "gold.schema.json",
                problem_schema=repo
                / "schemas"
                / "problem-contract.schema.json",
                require_gold=not args.inputs_only,
            )
        )
        return 0
    if args.resource == "benchmark" and args.action == "score":
        report = score_benchmark(
            predictions_root=args.predictions,
            gold_root=args.gold,
            prediction_schema=repo / "schemas" / "benchmark" / "prediction.schema.json",
            gold_schema=repo / "schemas" / "benchmark" / "gold.schema.json",
        )
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        _print(report)
        return 0

    run_dir = resolve_run_dir(args.run, args.runs_root)
    if args.resource == "campaign" and args.action == "status":
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        _print(state)
        return 0
    pipeline = CampaignPipeline.resume(run_dir, repository_root=repo)
    if args.resource == "campaign" and args.action == "resume":
        _print({"run_dir": str(run_dir), "summary": pipeline.run()})
        return 0
    if args.resource == "case" and args.action == "retry":
        _print(
            {
                "run_dir": str(run_dir),
                "summary": pipeline.retry(
                    args.candidate_id, args.stage, defer=args.defer
                ),
            }
        )
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
