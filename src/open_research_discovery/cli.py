from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .benchmark import (
    evaluate_benchmark,
    export_benchmark_inputs,
    score_benchmark,
    select_stratified_cases,
    validate_benchmark_dataset,
)
from .agent import CodexRunner
from .campaign import CampaignPipeline, resolve_run_dir
from .contract_agents import review_problem_contract, rewrite_problem_contract
from .gitlab_publication import publish_problem_contract_to_gitlab
from .problem_contract import (
    load_problem_contract,
    render_problem_contract_readme,
    require_valid_problem_contract,
    validate_problem_contract,
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _add_run_locator(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run", help="campaign directory or run id")
    parser.add_argument(
        "--runs-root",
        type=Path,
        help="required when RUN is an id rather than a directory",
    )


def _add_benchmark_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--workers", type=int, default=1)


def _add_benchmark_resume_args(parser: argparse.ArgumentParser) -> None:
    _add_run_locator(parser)
    parser.add_argument("--workers", type=int, default=1)


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
        help="explicit benchmark construction or evaluation workflow",
    )
    benchmark_actions = benchmark.add_subparsers(dest="action", required=True)
    prepare = benchmark_actions.add_parser("prepare")
    _add_benchmark_build_args(prepare)
    build = benchmark_actions.add_parser("build")
    _add_benchmark_build_args(build)
    resume_prepare = benchmark_actions.add_parser("resume-prepare")
    _add_benchmark_resume_args(resume_prepare)
    refresh = benchmark_actions.add_parser("refresh")
    _add_benchmark_resume_args(refresh)
    predict = benchmark_actions.add_parser("predict")
    _add_run_locator(predict)
    predict.add_argument("--workers", type=int, default=1)
    provisional = benchmark_actions.add_parser("provisional-triage")
    _add_run_locator(provisional)
    provisional.add_argument("--workers", type=int, default=1)
    export = benchmark_actions.add_parser("export")
    _add_run_locator(export)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--selection", type=Path)
    select = benchmark_actions.add_parser("select")
    _add_run_locator(select)
    select.add_argument("--per-domain", type=int, default=5)
    select.add_argument(
        "--domain",
        dest="domains",
        action="append",
        help="include only this domain; repeat for multiple domains",
    )
    select.add_argument("--out", type=Path, required=True)
    score = benchmark_actions.add_parser("score")
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--gold", type=Path, required=True)
    score.add_argument("--out", type=Path)
    score.add_argument(
        "--run",
        type=Path,
        help=(
            "optional campaign directory retained for report provenance; "
            "verification difficulty is scored but never used as a gate"
        ),
    )
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
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = repository_root()
    contract_schema = repo / "schemas" / "problem-contract.schema.json"
    if args.resource == "contract":
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
        raise AssertionError("unreachable")
    if args.resource == "campaign" and args.action == "run":
        pipeline = CampaignPipeline.start(
            args.config, repository_root=repo, run_id=args.run_id
        )
        summary = pipeline.run()
        _print({"run_dir": str(pipeline.run_dir), "summary": summary})
        return 0
    if args.resource == "benchmark" and args.action in {"prepare", "build"}:
        pipeline = CampaignPipeline.start(
            args.config, repository_root=repo, run_id=args.run_id
        )
        summary = pipeline.prepare_benchmark(workers=args.workers)
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
                gold_schema=repo / "schemas" / "benchmark" / "gold.schema.json",
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
            run_dir=args.run,
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
    if args.resource == "benchmark" and args.action == "export":
        _print(
            export_benchmark_inputs(
                run_dir=run_dir,
                out_dir=args.out,
                schema_path=repo / "schemas" / "benchmark" / "input.schema.json",
                selection_path=args.selection,
            )
        )
        return 0
    if args.resource == "benchmark" and args.action == "select":
        _print(
            select_stratified_cases(
                run_dir=run_dir,
                per_domain=args.per_domain,
                domains=args.domains,
                out_path=args.out,
            )
        )
        return 0

    pipeline = CampaignPipeline.resume(run_dir, repository_root=repo)
    if args.resource == "benchmark" and args.action in {
        "predict",
        "provisional-triage",
    }:
        _print(
            {
                "run_dir": str(run_dir),
                "summary": pipeline.triage_all_for_benchmark(workers=args.workers),
            }
        )
        return 0
    if args.resource == "benchmark" and args.action in {
        "resume-prepare",
        "refresh",
    }:
        _print(
            {
                "run_dir": str(run_dir),
                "summary": pipeline.prepare_benchmark(workers=args.workers),
            }
        )
        return 0
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
