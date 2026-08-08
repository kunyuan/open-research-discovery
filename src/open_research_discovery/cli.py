from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .agent import CodexRunner, KimiRunner
from .campaign import CampaignPipeline, resolve_run_dir
from .common import dump_yaml, slugify
from .contract_agents import review_problem_contract, rewrite_problem_contract
from .gitlab_publication import publish_problem_contract_to_gitlab
from .problem_contract import (
    load_problem_contract,
    render_problem_contract_readme,
    require_valid_problem_contract,
    validate_problem_contract,
)
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
    init = campaign_actions.add_parser(
        "init", help="create a multi-source campaign from one or more topics"
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

    benchmark = root.add_parser(
        "benchmark",
        help="blind quality benchmark over completed Problem Contracts",
    )
    benchmark_actions = benchmark.add_subparsers(dest="action", required=True)
    q_build = benchmark_actions.add_parser("build")
    q_build.add_argument(
        "--run-dir",
        type=Path,
        help="campaign run directory; collects candidates/*/problem.json",
    )
    q_build.add_argument(
        "--pool",
        type=Path,
        help="pool repository; reads catalog.jsonl + problems/*.json",
    )
    q_build.add_argument(
        "--manifest",
        type=Path,
        dest="manifests",
        action="append",
        help="problem.json file or directory; repeat for multiple",
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
    q_validate = benchmark_actions.add_parser("validate")
    q_validate.add_argument("dataset", type=Path)
    q_validate.add_argument("--inputs-only", action="store_true")
    q_evaluate = benchmark_actions.add_parser("evaluate")
    q_evaluate.add_argument("dataset", type=Path)
    q_evaluate.add_argument("--out", type=Path, required=True)
    q_evaluate.add_argument("--workers", type=int, default=1)
    q_evaluate.add_argument("--codex-executable", default="codex")
    q_evaluate.add_argument(
        "--backend",
        choices=("codex", "kimi"),
        default="codex",
        help=(
            "headless agent backend; 'kimi' uses the Kimi Code CLI "
            "(kimi -p --output-format stream-json) and has no sandbox "
            "isolation beyond environment sanitization"
        ),
    )
    q_evaluate.add_argument(
        "--kimi-executable",
        default="kimi",
        help="Kimi Code CLI executable used when --backend kimi",
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
    q_score = benchmark_actions.add_parser("score")
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
    if args.resource == "contract":
        schema_path = repo / "schemas" / "problem.schema.json"
        problem = load_problem_contract(args.problem.resolve())
        if args.action == "validate":
            errors = validate_problem_contract(problem, schema_path)
            _print({"valid": not errors, "errors": errors})
            return 0 if not errors else 1
        require_valid_problem_contract(problem, schema_path)
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
                    schema_path=schema_path,
                    out_dir=args.out_dir.resolve(),
                    gitlab_project=args.gitlab_project,
                    gitlab_host=args.gitlab_host,
                    visibility=args.visibility,
                )
            )
            return 0
        raise AssertionError("unreachable")
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
                        f"Find scientifically sound, currently open research "
                        f"problems about {title}. Preserve source attribution, "
                        f"allow motivated derived generalizations, and require "
                        f"a determinate non-narrowing verification standard."
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
                "networked_sandbox": "workspace-write",
                "network_access": True,
                "workers": 4,
                "networked_workers": 4,
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
    if args.resource == "benchmark" and args.action == "build":
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
    if args.resource == "benchmark" and args.action == "validate":
        _print(
            validate_quality_dataset(
                dataset_dir=args.dataset.resolve(),
                input_schema=repo / "schemas" / "quality" / "input.schema.json",
                gold_schema=repo / "schemas" / "quality" / "gold.schema.json",
                require_gold=not args.inputs_only,
            )
        )
        return 0
    if args.resource == "benchmark" and args.action == "evaluate":
        if args.backend == "kimi":
            quality_runner: CodexRunner | KimiRunner = KimiRunner(
                repository_root=repo,
                executable=args.kimi_executable,
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
    if args.resource == "benchmark" and args.action == "score":
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
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
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
