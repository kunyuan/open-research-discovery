from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .agent import ClaudeRunner, CodexRunner, KimiRunner
from .campaign import CampaignPipeline, resolve_run_dir
from .common import dump_json, dump_yaml, slugify
from .quality import (
    build_quality_dataset,
    evaluate_quality,
    score_quality,
    validate_quality_dataset,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discovery",
        description="Generate audited research-problem repositories.",
    )
    root = parser.add_subparsers(dest="resource", required=True)

    campaign = root.add_parser(
        "campaign",
        help="default problem-generation workflow",
    )
    campaign_actions = campaign.add_subparsers(dest="action", required=True)
    init = campaign_actions.add_parser(
        "init", help="create a schema-v2 multi-source campaign from one or more topics"
    )
    init.add_argument(
        "--topic",
        dest="topics",
        action="append",
        required=True,
        help="topic title or research area; repeat for multiple topics",
    )
    init.add_argument("--out", type=Path, required=True)
    init.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing config file",
    )
    init.add_argument(
        "--source",
        dest="sources",
        action="append",
        choices=("lkm_open_questions", "topic_search"),
        help="source route; defaults to both and may be repeated",
    )
    run = campaign_actions.add_parser("run")
    run.add_argument("config", type=Path)
    run.add_argument("--run-id")

    resume = campaign_actions.add_parser("resume")
    _add_run_locator(resume)

    status = campaign_actions.add_parser("status")
    _add_run_locator(status)

    quality = root.add_parser(
        "quality",
        help="problem-quality benchmark over published problem manifests",
    )
    quality_actions = quality.add_subparsers(dest="action", required=True)
    q_build = quality_actions.add_parser("build")
    q_build.add_argument(
        "--run-dir",
        type=Path,
        help="campaign run directory; collects candidates/*/problem.yaml",
    )
    q_build.add_argument(
        "--pool",
        type=Path,
        help="pool repository; reads catalog.jsonl + problems/*.yaml",
    )
    q_build.add_argument(
        "--manifest",
        type=Path,
        dest="manifests",
        action="append",
        help="bare manifest file or directory; repeat for multiple",
    )
    q_build.add_argument("--out", type=Path, required=True)
    q_build.add_argument(
        "--cache-dir",
        type=Path,
        help="citation-metadata cache directory (default: <out>/.evidence-cache)",
    )
    q_build.add_argument(
        "--offline",
        action="store_true",
        help="skip metadata fetching (serve cache only, mark the rest skipped)",
    )
    q_build.add_argument(
        "--inputs-only",
        action="store_true",
        help="export the dataset as pending manual labeling",
    )
    q_validate = quality_actions.add_parser("validate")
    q_validate.add_argument("dataset", type=Path)
    q_validate.add_argument("--inputs-only", action="store_true")
    q_evaluate = quality_actions.add_parser("evaluate")
    q_evaluate.add_argument("dataset", type=Path)
    q_evaluate.add_argument("--out", type=Path, required=True)
    q_evaluate.add_argument("--workers", type=int, default=1)
    q_evaluate.add_argument("--codex-executable", default="codex")
    q_evaluate.add_argument(
        "--backend",
        choices=("codex", "kimi", "claude"),
        default="codex",
        help=(
            "headless agent backend; 'kimi' uses the Kimi Code CLI "
            "(kimi -p --output-format stream-json), 'claude' uses the "
            "Claude Code CLI (claude -p --output-format json); neither "
            "has sandbox isolation beyond environment sanitization"
        ),
    )
    q_evaluate.add_argument(
        "--kimi-executable",
        default="kimi",
        help="Kimi Code CLI executable used when --backend kimi",
    )
    q_evaluate.add_argument(
        "--claude-executable",
        default="claude",
        help="Claude Code CLI executable used when --backend claude",
    )
    q_evaluate.add_argument("--model", default="")
    q_evaluate.add_argument("--timeout-seconds", type=int, default=3600)
    q_evaluate.add_argument(
        "--case-id",
        action="append",
        help="evaluate only this case; repeat for multiple cases",
    )
    q_evaluate.add_argument(
        "--resume",
        action="store_true",
        help="reuse existing schema-valid predictions and retry missing cases",
    )
    q_score = quality_actions.add_parser("score")
    q_score.add_argument("--dataset", type=Path, required=True)
    q_score.add_argument("--predictions", type=Path)
    q_score.add_argument("--gold", type=Path)
    q_score.add_argument("--out", type=Path)

    case = root.add_parser("case")
    case_actions = case.add_subparsers(dest="action", required=True)
    retry = case_actions.add_parser("retry")
    _add_run_locator(retry)
    retry.add_argument("candidate_id")
    retry.add_argument(
        "stage", choices=("selection", "research", "problem-review", "compile")
    )
    retry.add_argument(
        "--defer",
        action="store_true",
        help=(
            "only invalidate the stage and mark the candidate retry_requested; "
            "a later campaign resume executes the retry in the parallel audit"
        ),
    )
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = repository_root()
    if args.resource == "campaign" and args.action == "init":
        if args.out.exists() and not args.force:
            raise SystemExit(
                f"config already exists: {args.out} (use --force to overwrite)"
            )
        sources = list(
            dict.fromkeys(args.sources or ["lkm_open_questions", "topic_search"])
        )
        topics = []
        used_ids: set[str] = set()
        for index, title in enumerate(args.topics, start=1):
            base = slugify(title, fallback_prefix="topic")
            topic_id = base
            if topic_id in used_ids:
                topic_id = f"{base}-{index}"
            used_ids.add(topic_id)
            topics.append(
                {
                    "id": topic_id,
                    "title": title,
                    "query": (
                        f"Find source-faithful, currently open research problems "
                        f"about {title}, preserving their natural generality and "
                        f"providing non-narrowing verification standards."
                    ),
                    "sources": sources,
                    "seed_papers": [],
                    "seed_references": [],
                }
            )
        # The pipeline resolves relative output paths against its runtime cwd;
        # pin them to the config file's directory so the generated config is
        # location-independent.
        config_dir = args.out.resolve().parent
        config = {
            "schema_version": 2,
            "name": f"{topics[0]['id']}-campaign",
            "topics": topics,
            "limits": {
                "papers_per_domain": 10,
                "questions_per_domain": 100,
                "leads_per_topic": 100,
                "lkm_timeout_seconds": 60,
            },
            "agents": {
                "model": "",
                "codex_executable": "codex",
                "claude_executable": "claude",
                "networked_sandbox": "workspace-write",
                "network_access": True,
                "workers": 32,
                "networked_workers": 32,
                "retries": 1,
                "retry_backoff_seconds": 5,
                "sandbox": "read-only",
                "timeout_seconds": 3600,
            },
            "outputs": {
                key: str((config_dir / value).resolve())
                for key, value in (
                    ("runs_root", "./work/runs"),
                    ("problem_root", "./work/solutions"),
                    ("pool_root", "./work/problem-pool"),
                )
            },
        }
        dump_yaml(args.out, config)
        _print({"config": str(args.out), "topics": [item["id"] for item in topics]})
        return 0
    if args.resource == "campaign" and args.action == "run":
        pipeline = CampaignPipeline.start(
            args.config, repository_root=repo, run_id=args.run_id
        )
        summary = pipeline.run()
        _print({"run_dir": str(pipeline.run_dir), "summary": summary})
        return 0
    if args.resource == "quality" and args.action == "build":
        _print(
            build_quality_dataset(
                out_dir=args.out.resolve(),
                input_schema=repo / "schemas" / "quality" / "input.schema.json",
                problem_schema=repo / "schemas" / "problem.schema.json",
                run_dir=args.run_dir.resolve() if args.run_dir else None,
                pool_root=args.pool.resolve() if args.pool else None,
                manifest_inputs=(
                    [path.resolve() for path in args.manifests]
                    if args.manifests
                    else None
                ),
                cache_dir=args.cache_dir.resolve() if args.cache_dir else None,
                offline=args.offline,
                inputs_only=args.inputs_only,
            )
        )
        return 0
    if args.resource == "quality" and args.action == "validate":
        _print(
            validate_quality_dataset(
                dataset_dir=args.dataset.resolve(),
                input_schema=repo / "schemas" / "quality" / "input.schema.json",
                gold_schema=repo / "schemas" / "quality" / "gold.schema.json",
                require_gold=not args.inputs_only,
            )
        )
        return 0
    if args.resource == "quality" and args.action == "evaluate":
        if args.backend == "kimi":
            quality_runner: CodexRunner | KimiRunner | ClaudeRunner = KimiRunner(
                repository_root=repo,
                executable=args.kimi_executable,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
            )
        elif args.backend == "claude":
            quality_runner = ClaudeRunner(
                repository_root=repo,
                executable=args.claude_executable,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            quality_runner = CodexRunner(
                repository_root=repo,
                executable=args.codex_executable,
                model=args.model,
                sandbox="read-only",
                networked_sandbox="read-only",
                network_access=False,
                timeout_seconds=args.timeout_seconds,
            )
        _print(
            evaluate_quality(
                dataset_dir=args.dataset.resolve(),
                out_dir=args.out.resolve(),
                input_schema=repo / "schemas" / "quality" / "input.schema.json",
                prediction_schema=repo
                / "schemas"
                / "quality"
                / "prediction.schema.json",
                runner=quality_runner,
                workers=args.workers,
                case_ids=set(args.case_id) if args.case_id else None,
                resume=args.resume,
            )
        )
        return 0
    if args.resource == "quality" and args.action == "score":
        report = score_quality(
            dataset_dir=args.dataset.resolve(),
            input_schema=repo / "schemas" / "quality" / "input.schema.json",
            prediction_schema=repo
            / "schemas"
            / "quality"
            / "prediction.schema.json",
            gold_schema=repo / "schemas" / "quality" / "gold.schema.json",
            predictions_root=(
                args.predictions.resolve() if args.predictions else None
            ),
            gold_root=args.gold.resolve() if args.gold else None,
        )
        if args.out:
            dump_json(args.out, report)
        summary = report["identifiers"]
        print(
            f"quality report ({report['mode']}): {report['case_count']} cases, "
            f"{report['invalid_count']} schema-invalid, "
            f"hallucination_rate={summary['hallucination_rate']:.2f}, "
            f"metadata_error_rate={summary['metadata_error_rate']:.2f}, "
            f"duplicate_suspects={len(report['duplicates']['suspect_pairs'])}"
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
