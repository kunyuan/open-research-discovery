from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

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
    predict = benchmark_actions.add_parser("predict")
    _add_run_locator(predict)

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

    run_dir = resolve_run_dir(args.run, args.runs_root)
    if args.resource == "campaign" and args.action == "status":
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        _print(state)
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
