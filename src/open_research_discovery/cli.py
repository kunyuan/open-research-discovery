from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .benchmark import (
    export_benchmark_inputs,
    score_benchmark,
    select_stratified_cases,
)
from .campaign import CampaignPipeline, resolve_run_dir


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
        description="Run resumable open-research discovery campaigns.",
    )
    root = parser.add_subparsers(dest="resource", required=True)

    campaign = root.add_parser("campaign")
    campaign_actions = campaign.add_subparsers(dest="action", required=True)
    run = campaign_actions.add_parser("run")
    run.add_argument("config", type=Path)
    run.add_argument("--run-id")

    resume = campaign_actions.add_parser("resume")
    _add_run_locator(resume)

    status = campaign_actions.add_parser("status")
    _add_run_locator(status)

    benchmark = root.add_parser("benchmark")
    benchmark_actions = benchmark.add_subparsers(dest="action", required=True)
    prepare = benchmark_actions.add_parser("prepare")
    prepare.add_argument("config", type=Path)
    prepare.add_argument("--run-id")
    prepare.add_argument("--triage-per-domain", type=int)
    resume_prepare = benchmark_actions.add_parser("resume-prepare")
    _add_run_locator(resume_prepare)
    resume_prepare.add_argument("--triage-per-domain", type=int)
    predict = benchmark_actions.add_parser("predict")
    _add_run_locator(predict)
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

    case = root.add_parser("case")
    case_actions = case.add_subparsers(dest="action", required=True)
    retry = case_actions.add_parser("retry")
    _add_run_locator(retry)
    retry.add_argument("candidate_id")
    retry.add_argument(
        "stage", choices=("triage", "research", "review", "compile")
    )
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = repository_root()
    if args.resource == "campaign" and args.action == "run":
        pipeline = CampaignPipeline.start(
            args.config, repository_root=repo, run_id=args.run_id
        )
        summary = pipeline.run()
        _print({"run_dir": str(pipeline.run_dir), "summary": summary})
        return 0
    if args.resource == "benchmark" and args.action == "prepare":
        pipeline = CampaignPipeline.start(
            args.config, repository_root=repo, run_id=args.run_id
        )
        summary = pipeline.prepare_benchmark(
            triage_per_domain=args.triage_per_domain
        )
        _print({"run_dir": str(pipeline.run_dir), "summary": summary})
        return 0
    if args.resource == "benchmark" and args.action == "score":
        report = score_benchmark(
            predictions_root=args.predictions,
            gold_root=args.gold,
            prediction_schema=repo
            / "schemas"
            / "benchmark"
            / "prediction.schema.json",
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
    if args.resource == "benchmark" and args.action == "predict":
        _print(
            {
                "run_dir": str(run_dir),
                "summary": pipeline.triage_all_for_benchmark(),
            }
        )
        return 0
    if args.resource == "benchmark" and args.action == "resume-prepare":
        _print(
            {
                "run_dir": str(run_dir),
                "summary": pipeline.prepare_benchmark(
                    triage_per_domain=args.triage_per_domain
                ),
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
                "summary": pipeline.retry(args.candidate_id, args.stage),
            }
        )
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
