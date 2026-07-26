from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .agent import AgentRun, CodexRunner, file_sha256
from .common import (
    dump_json,
    dump_yaml,
    load_yaml,
    pool_snapshot_paths,
    problem_manifest_paths,
    slugify,
    today,
    utc_now,
)
from .lkm import PAPER_GRAPH_URL, collect_paper_open_questions
from .pool import normalize_text, problem_to_record, text_tokens
from .problem_repo import create_problem_repo
from .ranking import rank_records
from .validation import validate_problem


PIPELINE_VERSION = 1
SKILL_NAME = "research-evidence-search"
STAGE_ORDER = ("triage", "research", "review", "compile")


class CampaignError(RuntimeError):
    """A campaign cannot safely proceed."""


def _json_sha256(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise CampaignError(f"expected JSON object: {path}")
    return value


def _schema_errors(instance: Any, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return [
        f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda item: list(item.absolute_path),
        )
    ]


def _skill_hash(skill_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in skill_dir.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(skill_dir)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _tool_version(command: list[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"unavailable: {type(error).__name__}"
    rendered = (completed.stdout or completed.stderr).strip()
    return rendered or f"exit={completed.returncode}"


def _source_key(question: dict[str, Any]) -> str:
    for field in ("global_id", "id"):
        value = question.get(field)
        if value not in (None, ""):
            return f"{field}:{value}"
    return "sha256:" + hashlib.sha256(
        str(question.get("content") or "").encode("utf-8")
    ).hexdigest()


def _candidate_id(cluster: dict[str, Any]) -> str:
    identity = {
        "statement": normalize_text(str(cluster["canonical_statement"])),
        "sources": sorted(cluster["source_keys"]),
    }
    return "CAN-" + _json_sha256(identity)[:12].upper()


def _choose_identifier(paper: dict[str, Any]) -> dict[str, str]:
    identifiers = _paper_identifiers(paper)
    if identifiers:
        return identifiers[0]
    raise ValueError("candidate paper has no paper_id, DOI, or title")


def _paper_identifiers(paper: dict[str, Any]) -> list[dict[str, str]]:
    identifiers: list[dict[str, str]] = []
    for field in ("paper_id", "doi", "title"):
        value = str(paper.get(field) or "").strip()
        if value:
            identifiers.append({field: value})
    return identifiers


def _paper_key(paper: dict[str, Any]) -> str:
    identifier = _choose_identifier(paper)
    field, value = next(iter(identifier.items()))
    return f"{field}:{normalize_text(value)}"


def _merge_papers(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for paper in group:
            try:
                key = _paper_key(paper)
            except ValueError:
                continue
            merged.setdefault(key, paper)
    return list(merged.values())


def _heuristic_relations(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for index, left in enumerate(questions):
        left_text = str(left.get("content") or "")
        left_normal = normalize_text(left_text)
        left_tokens = text_tokens(left_text)
        for right in questions[index + 1 :]:
            right_text = str(right.get("content") or "")
            right_tokens = text_tokens(right_text)
            union = left_tokens | right_tokens
            jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
            exact = bool(left_normal) and left_normal == normalize_text(right_text)
            if exact or jaccard >= 0.72:
                suggestions.append(
                    {
                        "left": left["source_key"],
                        "right": right["source_key"],
                        "exact_normalized": exact,
                        "token_jaccard": round(jaccard, 6),
                    }
                )
    return suggestions


@dataclass
class Produced:
    output: dict[str, Any]
    metadata: dict[str, Any]


class StageLedger:
    def __init__(self, run_dir: Path, state: dict[str, Any]) -> None:
        self.run_dir = run_dir
        self.state = state

    def save(self) -> None:
        dump_json(self.run_dir / "state.json", self.state)

    def invalidate(self, predicate: Callable[[str], bool]) -> None:
        stages = self.state.setdefault("stages", {})
        for key, record in stages.items():
            if predicate(key):
                record["status"] = "invalidated"
                record["invalidated_at"] = utc_now()
        self.save()

    def execute(
        self,
        *,
        key: str,
        inputs: dict[str, Any],
        output_path: Path,
        producer: Callable[[], Produced],
        schema_path: Path | None = None,
    ) -> dict[str, Any]:
        input_sha = _json_sha256(inputs)
        stages = self.state.setdefault("stages", {})
        previous = stages.get(key) or {}
        if (
            previous.get("status") == "completed"
            and previous.get("input_sha256") == input_sha
            and output_path.is_file()
            and previous.get("output_sha256") == file_sha256(output_path)
        ):
            return _load_json(output_path)

        attempt = int(previous.get("attempt") or 0) + 1
        record = {
            "status": "running",
            "attempt": attempt,
            "input_sha256": input_sha,
            "pipeline_version": inputs.get("pipeline_version", PIPELINE_VERSION),
            "skill": inputs.get("skill", ""),
            "skill_sha256": inputs.get("skill_sha256", ""),
            "tool_versions": inputs.get("tool_versions", {}),
            "output": _relative(output_path, self.run_dir),
            "schema": _relative(schema_path, self.run_dir) if schema_path else "",
            "schema_sha256": file_sha256(schema_path) if schema_path else "",
            "started_at": utc_now(),
        }
        stages[key] = record
        self.save()
        try:
            produced = producer()
            if schema_path:
                errors = _schema_errors(produced.output, schema_path)
                if errors:
                    raise CampaignError(
                        f"{key} output failed schema validation: {'; '.join(errors[:8])}"
                    )
            dump_json(output_path, produced.output)
            record.update(produced.metadata)
            record.update(
                {
                    "status": "completed",
                    "exit_code": int(produced.metadata.get("exit_code", 0)),
                    "output_sha256": file_sha256(output_path),
                    "completed_at": utc_now(),
                }
            )
            self.save()
            return produced.output
        except Exception as error:
            record.update(
                {
                    "status": "failed",
                    "exit_code": int(record.get("exit_code", 1)),
                    "error": f"{type(error).__name__}: {error}",
                    "completed_at": utc_now(),
                }
            )
            self.state["status"] = "failed"
            self.state["error"] = record["error"]
            self.save()
            raise


PaperCollector = Callable[..., dict[str, Any]]


class CampaignPipeline:
    def __init__(
        self,
        *,
        repository_root: Path,
        run_dir: Path,
        config: dict[str, Any],
        agent_runner: Any | None = None,
        paper_collector: PaperCollector | None = None,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.run_dir = run_dir.resolve()
        self.config = config
        self.schemas = self.repository_root / "schemas"
        self.skill_dir = (
            self.repository_root / ".agents" / "skills" / SKILL_NAME
        )
        self.skill_sha256 = _skill_hash(self.skill_dir)
        agent_config = config["agents"]
        self.agent_runner = agent_runner or CodexRunner(
            repository_root=self.repository_root,
            executable=agent_config["codex_executable"],
            model=agent_config["model"],
            sandbox=agent_config["sandbox"],
            networked_sandbox=agent_config.get(
                "networked_sandbox", "workspace-write"
            ),
            network_access=agent_config.get("network_access", True),
            timeout_seconds=agent_config["timeout_seconds"],
        )
        version_method = getattr(self.agent_runner, "version", None)
        codex_version = version_method() if callable(version_method) else "unreported"
        self.tool_versions = {
            "python": sys.version.split()[0],
            "gaia": _tool_version(
                ["gaia", "--version"], cwd=Path(tempfile.gettempdir())
            ),
            "codex": codex_version,
        }
        self.paper_collector = paper_collector or collect_paper_open_questions
        self.state = _load_json(self.run_dir / "state.json")
        self.ledger = StageLedger(self.run_dir, self.state)
        self.problem_root = Path(config["outputs"]["problem_root"]).resolve()
        pool_root = str(config["outputs"]["pool_root"] or "")
        self.pool_root = Path(pool_root).resolve() if pool_root else None

    @classmethod
    def start(
        cls,
        config_path: Path,
        *,
        repository_root: Path,
        run_id: str | None = None,
        agent_runner: Any | None = None,
        paper_collector: PaperCollector | None = None,
    ) -> "CampaignPipeline":
        raw = load_yaml(config_path)
        schema_path = repository_root / "schemas" / "campaign.schema.json"
        errors = _schema_errors(raw, schema_path)
        if errors:
            raise CampaignError("invalid campaign config: " + "; ".join(errors))
        config = json.loads(json.dumps(raw))
        base = config_path.resolve().parent
        for field in ("runs_root", "problem_root", "pool_root"):
            value = str(config["outputs"][field] or "")
            if value and not Path(value).is_absolute():
                config["outputs"][field] = str((base / value).resolve())
        if run_id is None:
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            run_id = f"{slugify(config['name'])}-{timestamp}"
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", run_id):
            raise CampaignError("run_id contains unsupported characters")
        run_dir = Path(config["outputs"]["runs_root"]) / run_id
        if run_dir.exists():
            raise FileExistsError(f"campaign already exists: {run_dir}")
        run_dir.mkdir(parents=True)
        dump_yaml(run_dir / "campaign.yaml", config)
        state = {
            "schema_version": 1,
            "pipeline_version": PIPELINE_VERSION,
            "run_id": run_id,
            "status": "created",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "campaign_sha256": file_sha256(run_dir / "campaign.yaml"),
            "stages": {},
            "candidates": {},
        }
        dump_json(run_dir / "state.json", state)
        return cls(
            repository_root=repository_root,
            run_dir=run_dir,
            config=config,
            agent_runner=agent_runner,
            paper_collector=paper_collector,
        )

    @classmethod
    def resume(
        cls,
        run_dir: Path,
        *,
        repository_root: Path,
        agent_runner: Any | None = None,
        paper_collector: PaperCollector | None = None,
    ) -> "CampaignPipeline":
        config = load_yaml(run_dir / "campaign.yaml")
        if file_sha256(run_dir / "campaign.yaml") != _load_json(
            run_dir / "state.json"
        ).get("campaign_sha256"):
            raise CampaignError(
                "campaign.yaml changed after creation; start a new run or restore it"
            )
        return cls(
            repository_root=repository_root,
            run_dir=run_dir,
            config=config,
            agent_runner=agent_runner,
            paper_collector=paper_collector,
        )

    def _base_inputs(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "pipeline_version": PIPELINE_VERSION,
            "skill": SKILL_NAME,
            "skill_sha256": self.skill_sha256,
            "tool_versions": self.tool_versions,
            "value": value,
        }

    def _agent(
        self,
        *,
        stage_key: str,
        role: str,
        prompt: str,
        schema_name: str,
        output_path: Path,
        events_path: Path,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        schema_path = self.schemas / "stages" / schema_name

        def produce() -> Produced:
            result: AgentRun = self.agent_runner.run(
                role=role,
                prompt=prompt,
                schema_path=schema_path,
                output_path=output_path,
                events_path=events_path,
            )
            return Produced(result.output, result.metadata)

        return self.ledger.execute(
            key=stage_key,
            inputs=self._base_inputs(
                {
                    "role": role,
                    "prompt_sha256": hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest(),
                    "schema_sha256": file_sha256(schema_path),
                    "model": self.config["agents"]["model"] or "configured-default",
                    "payload": inputs,
                }
            ),
            output_path=output_path,
            producer=produce,
            schema_path=schema_path,
        )

    def run(self) -> dict[str, Any]:
        self.state["status"] = "running"
        self.state["error"] = ""
        self.state["updated_at"] = utc_now()
        self.ledger.save()
        try:
            discovered = self._discover()
            questions = self._ingest(discovered)
            candidates = self._canonicalize(questions)
            accepted: list[str] = []
            low_priority: list[dict[str, Any]] = []
            for candidate in candidates:
                candidate_id = candidate["candidate_id"]
                triage = self._triage(candidate)
                if not self._passes_gate(triage):
                    self.state["candidates"][candidate_id]["status"] = "low_priority"
                    low_priority.append(
                        {
                            "candidate_id": candidate_id,
                            "canonical_title": candidate["canonical_title"],
                            "triage": triage,
                        }
                    )
                    self.ledger.save()
                    continue
                verdict, assessment = self._research_and_review(candidate, triage)
                if verdict["verdict"] == "accept":
                    compiled = self._compile(candidate, triage, assessment, verdict)
                    accepted.append(compiled["problem_id"])
                    self.state["candidates"][candidate_id]["status"] = "accepted"
                elif verdict["verdict"] == "reject":
                    self.state["candidates"][candidate_id]["status"] = "rejected"
                else:
                    self.state["candidates"][candidate_id]["status"] = "needs_revision"
                self.ledger.save()
            self._write_low_priority(low_priority)
            ranking = self._sync_and_rank(accepted)
            self.state.update(
                {
                    "status": "completed",
                    "updated_at": utc_now(),
                    "summary": {
                        "source_open_questions": len(questions),
                        "canonical_candidates": len(candidates),
                        "accepted_problem_ids": accepted,
                        "low_priority_count": len(low_priority),
                        "ranked_problem_count": len(ranking),
                    },
                }
            )
            self.ledger.save()
            return self.state["summary"]
        except Exception:
            self.state["status"] = "failed"
            self.state["updated_at"] = utc_now()
            self.ledger.save()
            raise

    def triage_all_for_benchmark(self) -> dict[str, Any]:
        """Produce baseline screening predictions without status research."""

        source_path = self.run_dir / "source-open-questions.json"
        canonical_path = self.run_dir / "canonicalization.json"
        if not source_path.is_file() or not canonical_path.is_file():
            raise CampaignError(
                "benchmark triage requires completed ingestion and canonicalization"
            )
        questions_document = _load_json(source_path)
        questions = list(questions_document.get("open_questions") or [])
        self.state["status"] = "benchmark_triaging"
        self.state["error"] = ""
        self.state["updated_at"] = utc_now()
        self.ledger.save()
        try:
            candidates = self._materialize_candidates(
                _load_json(canonical_path), questions
            )
            predictions: list[dict[str, Any]] = []
            for candidate in candidates:
                candidate_id = candidate["candidate_id"]
                triage_path = (
                    self.run_dir
                    / "candidates"
                    / candidate_id
                    / "triage.json"
                )
                triage_schema = (
                    self.schemas / "stages" / "triage.schema.json"
                )
                triage: dict[str, Any]
                if triage_path.is_file():
                    existing = _load_json(triage_path)
                    errors = _schema_errors(existing, triage_schema)
                    if errors:
                        triage = self._triage(candidate)
                    else:
                        triage = existing
                        stage = self.state.get("stages", {}).get(
                            f"candidate.{candidate_id}.triage"
                        )
                        if stage and stage.get("status") == "running":
                            stage.update(
                                {
                                    "status": "interrupted",
                                    "completed_at": utc_now(),
                                    "error": (
                                        "interrupted invocation; benchmark reused "
                                        "the pre-existing schema-valid prediction"
                                    ),
                                }
                            )
                else:
                    triage = self._triage(candidate)
                passed = self._passes_gate(triage)
                self.state["candidates"][candidate_id][
                    "benchmark_triage_status"
                ] = "pass" if passed else "fail"
                predictions.append(
                    {
                        "candidate_id": candidate_id,
                        "domain": candidate["domain"],
                        "canonical_title": candidate["canonical_title"],
                        "prediction_path": _relative(
                            self.run_dir
                            / "candidates"
                            / candidate_id
                            / "triage.json",
                            self.run_dir,
                        ),
                        "gate": triage["gate"],
                        "importance_level": triage["importance_level"],
                        "verification_mode": triage["verification_mode"],
                        "verification_ease": triage["verification_ease"],
                        "review_scope": triage["review_scope"],
                        "ci_feasibility": triage["ci_feasibility"],
                        "passes_pipeline_gate": passed,
                    }
                )
                self.ledger.save()
            summary = {
                "schema_version": 1,
                "candidate_count": len(predictions),
                "pass_count": sum(
                    item["passes_pipeline_gate"] for item in predictions
                ),
                "fail_count": sum(
                    not item["passes_pipeline_gate"] for item in predictions
                ),
                "predictions": predictions,
            }
            dump_json(self.run_dir / "benchmark-triage-summary.json", summary)
            self.state["status"] = "benchmark_triaged"
            self.state["updated_at"] = utc_now()
            self.state["benchmark_triage_summary"] = {
                "candidate_count": summary["candidate_count"],
                "pass_count": summary["pass_count"],
                "fail_count": summary["fail_count"],
            }
            self.ledger.save()
            return summary
        except Exception:
            self.state["status"] = "failed"
            self.state["updated_at"] = utc_now()
            self.ledger.save()
            raise

    def _discover(self) -> dict[str, dict[str, Any]]:
        outputs: dict[str, dict[str, Any]] = {}
        limit = self.config["limits"]["papers_per_domain"]
        for domain in self.config["domains"]:
            domain_id = domain["id"]
            domain_dir = self.run_dir / "domains" / domain_id
            prompt = f"""
You are the Discovery Agent for one research-problem campaign.
Use ${SKILL_NAME}. Search LKM and/or the web in whichever order gives broad,
source-grounded recall. Return candidate papers only; do not create or infer
open questions. The deterministic pipeline will query each paper through the
direct LKM papers/graph API and will accept only its dedicated open_questions.
Do not modify workspace files; return the structured result only.

Domain id: {domain_id}
Campaign query:
{domain["query"]}

Seed papers are hints, not mandatory conclusions:
{json.dumps(domain["seed_papers"], ensure_ascii=False, indent=2)}

Return at most {limit} papers. Each paper must have at least one non-empty
paper_id, DOI, or exact title. Tag every evidence item by actual content level.
""".strip()
            output = self._agent(
                stage_key=f"campaign.discovery.{domain_id}",
                role="discovery",
                prompt=prompt,
                schema_name="discovery.schema.json",
                output_path=domain_dir / "source-papers.agent.json",
                events_path=domain_dir / "events" / "discovery.jsonl",
                inputs={"domain": domain, "limit": limit},
            )
            if output["domain_id"] != domain_id:
                raise CampaignError(
                    f"Discovery Agent returned domain_id={output['domain_id']!r}, "
                    f"expected {domain_id!r}"
                )
            invalid = [
                paper
                for paper in [*domain["seed_papers"], *output["papers"]]
                if not any(
                    str(paper.get(field) or "").strip()
                    for field in ("paper_id", "doi", "title")
                )
            ]
            if invalid:
                raise CampaignError(
                    "every candidate paper needs a paper_id, DOI, or exact title"
                )
            papers = _merge_papers(
                domain["seed_papers"], output["papers"]
            )[:limit]
            source_papers = {
                "schema_version": 1,
                "domain_id": domain_id,
                "papers": papers,
                "search_summary": output["search_summary"],
            }
            dump_json(domain_dir / "source-papers.json", source_papers)
            outputs[domain_id] = source_papers
        return outputs

    def _ingest(
        self, discovered: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        all_questions: list[dict[str, Any]] = []
        limit = self.config["limits"]["questions_per_domain"]
        timeout = self.config["limits"]["lkm_timeout_seconds"]
        for domain_id, source in discovered.items():
            domain_dir = self.run_dir / "domains" / domain_id
            output_path = domain_dir / "source-open-questions.json"

            def produce(
                domain_id: str = domain_id,
                source: dict[str, Any] = source,
                domain_dir: Path = domain_dir,
            ) -> Produced:
                questions: list[dict[str, Any]] = []
                papers: list[dict[str, Any]] = []
                failures: list[dict[str, Any]] = []
                raw_dir = domain_dir / "evidence" / "lkm"
                for index, paper in enumerate(source["papers"], start=1):
                    raw_path: Path | None = None
                    result: dict[str, Any] | None = None
                    successful_identifier: dict[str, str] | None = None
                    extract_path: Path | None = None
                    attempts: list[dict[str, Any]] = []
                    identifiers = _paper_identifiers(paper)
                    if not identifiers:
                        failures.append(
                            {
                                "paper": paper,
                                "attempts": [],
                                "error": "ValueError: candidate paper has no paper_id, DOI, or title",
                            }
                        )
                        continue
                    for attempt_index, identifier in enumerate(identifiers, start=1):
                        suffix = (
                            ""
                            if attempt_index == 1
                            else f"-attempt-{attempt_index}"
                        )
                        raw_path = (
                            raw_dir / f"paper-{index:03d}{suffix}-graph.json"
                        )
                        extract_path = (
                            raw_dir
                            / f"paper-{index:03d}{suffix}-open-questions.json"
                        )
                        try:
                            result = self.paper_collector(
                                **identifier,
                                raw_out=raw_path,
                                out=extract_path,
                                timeout=timeout,
                            )
                        except Exception as error:
                            attempts.append(
                                {
                                    "identifier": identifier,
                                    "raw_response": (
                                        _relative(raw_path, self.run_dir)
                                        if raw_path.is_file()
                                        else ""
                                    ),
                                    "error": f"{type(error).__name__}: {error}",
                                }
                            )
                            continue
                        successful_identifier = identifier
                        attempts.append(
                            {
                                "identifier": identifier,
                                "raw_response": _relative(raw_path, self.run_dir),
                                "status": "success",
                            }
                        )
                        break
                    if result is None or successful_identifier is None:
                        failures.append(
                            {
                                "paper": paper,
                                "attempts": attempts,
                                "error": (
                                    attempts[-1]["error"]
                                    if attempts
                                    else "no usable paper identifier"
                                ),
                            }
                        )
                        continue
                    papers.append(
                        {
                            "identifier": successful_identifier,
                            "identifier_attempts": attempts,
                            "trace_id": result.get("trace_id"),
                            "raw_response": _relative(raw_path, self.run_dir),
                            "extraction": _relative(extract_path, self.run_dir),
                            "open_question_count": int(result.get("count") or 0),
                        }
                    )
                    for question in result.get("open_questions") or []:
                        enriched = {
                            **question,
                            "domain_id": domain_id,
                        }
                        enriched["source_key"] = _source_key(enriched)
                        questions.append(enriched)
                        if len(questions) >= limit:
                            break
                    if len(questions) >= limit:
                        break
                if source["papers"] and not papers:
                    raise CampaignError(
                        f"all direct LKM papers/graph requests failed for {domain_id}"
                    )
                return Produced(
                    {
                        "schema_version": 1,
                        "endpoint": PAPER_GRAPH_URL,
                        "source_path": "data.papers[].open_questions",
                        "domain_id": domain_id,
                        "papers": papers,
                        "failures": failures,
                        "count": len(questions),
                        "open_questions": questions,
                    },
                    {
                        "exit_code": 0,
                        "tool": "direct-lkm-papers-graph-api",
                        "endpoint": PAPER_GRAPH_URL,
                    },
                )

            output = self.ledger.execute(
                key=f"campaign.ingest.{domain_id}",
                inputs=self._base_inputs(
                    {
                        "source_papers": source,
                        "limit": limit,
                        "timeout": timeout,
                        "endpoint": PAPER_GRAPH_URL,
                    }
                ),
                output_path=output_path,
                producer=produce,
            )
            all_questions.extend(output["open_questions"])
        unique_questions: dict[str, dict[str, Any]] = {}
        for question in all_questions:
            key = question["source_key"]
            if key not in unique_questions:
                unique_questions[key] = {
                    **question,
                    "domain_ids": [question["domain_id"]],
                }
            elif question["domain_id"] not in unique_questions[key]["domain_ids"]:
                unique_questions[key]["domain_ids"].append(question["domain_id"])
        all_questions = list(unique_questions.values())
        dump_json(
            self.run_dir / "source-open-questions.json",
            {
                "schema_version": 1,
                "count": len(all_questions),
                "open_questions": all_questions,
            },
        )
        return all_questions

    def _canonicalize(
        self, questions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        output_path = self.run_dir / "canonicalization.json"
        if not questions:
            dump_json(output_path, {"clusters": []})
            return []
        heuristic = _heuristic_relations(questions)
        prompt = f"""
Canonicalize source-grounded open-question records into semantic problem
clusters. Programmatic normalization has supplied only heuristic pair hints;
make the semantic decision yourself. Every input source_key must appear
exactly once across the clusters. Merge equivalent formulations, but do not
merge merely related problems. Do not audit current status in this stage.

Open-question records (all came strictly from
data.papers[].open_questions):
{json.dumps(questions, ensure_ascii=False, indent=2)}

Heuristic possible-duplicate pairs:
{json.dumps(heuristic, ensure_ascii=False, indent=2)}
""".strip()
        output = self._agent(
            stage_key="campaign.canonicalization",
            role="canonicalization",
            prompt=prompt,
            schema_name="canonicalization.schema.json",
            output_path=output_path,
            events_path=self.run_dir / "events" / "canonicalization.jsonl",
            inputs={"questions": questions, "heuristic_relations": heuristic},
        )
        return self._materialize_candidates(output, questions)

    def _materialize_candidates(
        self,
        output: dict[str, Any],
        questions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        expected = {question["source_key"] for question in questions}
        assigned = [
            key for cluster in output["clusters"] for key in cluster["source_keys"]
        ]
        if set(assigned) != expected or len(assigned) != len(set(assigned)):
            raise CampaignError(
                "canonicalization must assign every source_key exactly once"
            )
        by_key = {question["source_key"]: question for question in questions}
        candidates: list[dict[str, Any]] = []
        for cluster in output["clusters"]:
            candidate_id = _candidate_id(cluster)
            candidate = {
                **cluster,
                "candidate_id": candidate_id,
                "source_open_questions": [
                    by_key[key] for key in cluster["source_keys"]
                ],
            }
            candidate_dir = self.run_dir / "candidates" / candidate_id
            papers = {
                (
                    str(question.get("paper_id") or ""),
                    str(question.get("paper_doi") or ""),
                    str(question.get("paper_title") or ""),
                )
                for question in candidate["source_open_questions"]
            }
            dump_json(
                candidate_dir / "source-papers.json",
                {
                    "schema_version": 1,
                    "papers": [
                        {"paper_id": item[0], "doi": item[1], "title": item[2]}
                        for item in sorted(papers)
                    ],
                },
            )
            dump_json(
                candidate_dir / "source-open-questions.json",
                {
                    "schema_version": 1,
                    "open_questions": candidate["source_open_questions"],
                },
            )
            dump_json(candidate_dir / "canonicalization.json", candidate)
            self.state.setdefault("candidates", {}).setdefault(
                candidate_id,
                {
                    "status": "canonicalized",
                    "canonical_title": candidate["canonical_title"],
                    "directory": _relative(candidate_dir, self.run_dir),
                },
            )
            candidates.append(candidate)
        active_candidate_ids = {
            candidate["candidate_id"] for candidate in candidates
        }
        self.state["active_candidate_ids"] = sorted(active_candidate_ids)
        for candidate_id, candidate_state in self.state.get(
            "candidates", {}
        ).items():
            candidate_state["canonicalization_active"] = (
                candidate_id in active_candidate_ids
            )
        self.ledger.save()
        return sorted(candidates, key=lambda item: item["candidate_id"])

    def _triage(self, candidate: dict[str, Any]) -> dict[str, Any]:
        candidate_id = candidate["candidate_id"]
        candidate_dir = self.run_dir / "candidates" / candidate_id
        prompt = f"""
You are the Triage Agent. Apply the $rank-open-problems policy and judge the
intrinsic source-era problem before any
expensive later-literature audit. We care about scientific importance and the
cost and boundary of independent review, not how difficult the problem is to
solve. Searchability, expected solve time, compute, feedback density, and
success probability must not affect the gate.

Pass a candidate only when importance is concrete (high or medium) and there
is an operational machine, bounded-LLM, hybrid, or expert review boundary.
CI may be pseudocode in principle; it need not already be implemented. Mark
whether review needs only the submitted result, the result plus derivation, or
expert-intensive judgment. Return a problem-specific verification protocol
and CI pseudocode.

Candidate:
{json.dumps(candidate, ensure_ascii=False, indent=2)}
""".strip()
        output = self._agent(
            stage_key=f"candidate.{candidate_id}.triage",
            role="triage",
            prompt=prompt,
            schema_name="triage.schema.json",
            output_path=candidate_dir / "triage.json",
            events_path=candidate_dir / "events" / "triage.jsonl",
            inputs={"candidate": candidate},
        )
        if output["candidate_id"] != candidate_id:
            raise CampaignError("Triage Agent returned the wrong candidate_id")
        return output

    @staticmethod
    def _passes_gate(triage: dict[str, Any]) -> bool:
        return (
            triage["gate"] == "pass"
            and triage["importance_level"] in {"high", "medium"}
            and triage["verification_mode"] != "unclassified"
            and triage["review_scope"] != "unclassified"
            and triage["ci_feasibility"] != "blocked"
        )

    def _research_and_review(
        self, candidate: dict[str, Any], triage: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        candidate_id = candidate["candidate_id"]
        candidate_dir = self.run_dir / "candidates" / candidate_id
        feedback: list[str] = []
        max_rounds = self.config["limits"]["revision_rounds"]
        last_assessment: dict[str, Any] = {}
        last_verdict: dict[str, Any] = {}
        for round_index in range(max_rounds + 1):
            prompt = f"""
You are the Research Agent. Use ${SKILL_NAME} to reconstruct what later
literature says about this exact candidate. Choose LKM and web routes
adaptively. After retrieval, directly produce the status, major-progress
assessment, precise surviving core, and reviewer/CI contracts in the required
schema. Do not send control back to the Discovery Agent and do not write to a
problem pool or workspace files.

An absence of a found solution is not enough for still_open. Inspect how later
work treats the same core. If major progress narrows or reframes it, reassess
the surviving core's importance and verification profile from scratch.
Evidence content levels must state what was actually inspected. Retrieval
score is not confidence. Mark coverage systematic_literature only when you
actually reconstructed a sufficiently broad later-literature chain; otherwise
mark it lkm_only and keep uncertainty visible.

Candidate:
{json.dumps(candidate, ensure_ascii=False, indent=2)}

Intrinsic triage:
{json.dumps(triage, ensure_ascii=False, indent=2)}

Independent reviewer revision instructions from the previous round:
{json.dumps(feedback, ensure_ascii=False, indent=2)}
""".strip()
            assessment = self._agent(
                stage_key=f"candidate.{candidate_id}.research.{round_index}",
                role="research",
                prompt=prompt,
                schema_name="assessment.schema.json",
                output_path=candidate_dir / f"assessment-r{round_index}.json",
                events_path=candidate_dir
                / "events"
                / f"research-{round_index}.jsonl",
                inputs={
                    "candidate": candidate,
                    "triage": triage,
                    "feedback": feedback,
                    "round": round_index,
                },
            )
            if assessment["candidate_id"] != candidate_id:
                raise CampaignError("Research Agent returned the wrong candidate_id")
            review_prompt = f"""
You are an independent Reviewer Agent. Audit the Research Agent's structured
assessment against the source open-question records, intrinsic triage, and its
cited evidence. Check the status conclusion, major-progress classification,
surviving core, scientific importance, content-level honesty, bounded reviewer
contract, and problem-specific CI pseudocode. Do not solve the problem and do
not mutate any pool or repository.

Return accept only if every load-bearing judgment is supported and the
verification boundary is operational. Return revise with concrete instructions
when correction or more evidence could repair it. Return reject when the
candidate should not proceed.

Source candidate:
{json.dumps(candidate, ensure_ascii=False, indent=2)}

Triage:
{json.dumps(triage, ensure_ascii=False, indent=2)}

Research assessment:
{json.dumps(assessment, ensure_ascii=False, indent=2)}
""".strip()
            verdict = self._agent(
                stage_key=f"candidate.{candidate_id}.review.{round_index}",
                role="reviewer",
                prompt=review_prompt,
                schema_name="review.schema.json",
                output_path=candidate_dir
                / f"reviewer-verdict-r{round_index}.json",
                events_path=candidate_dir
                / "events"
                / f"review-{round_index}.jsonl",
                inputs={
                    "candidate": candidate,
                    "triage": triage,
                    "assessment": assessment,
                    "round": round_index,
                },
            )
            if verdict["candidate_id"] != candidate_id:
                raise CampaignError("Reviewer Agent returned the wrong candidate_id")
            last_assessment, last_verdict = assessment, verdict
            for source in ("lkm", "web"):
                items = [
                    item for item in assessment["evidence"] if item["source"] == source
                ]
                dump_json(
                    candidate_dir
                    / "evidence"
                    / source
                    / f"research-evidence-r{round_index}.json",
                    {
                        "schema_version": 1,
                        "candidate_id": candidate_id,
                        "round": round_index,
                        "evidence": items,
                    },
                )
            self.state["candidates"][candidate_id].update(
                {
                    "research_round": round_index,
                    "review_verdict": verdict["verdict"],
                }
            )
            self.ledger.save()
            if verdict["verdict"] != "revise":
                break
            feedback = verdict["revision_instructions"]
        dump_json(candidate_dir / "assessment.json", last_assessment)
        dump_json(candidate_dir / "reviewer-verdict.json", last_verdict)
        return last_verdict, last_assessment

    def _allocate_problem_id(self, candidate_id: str) -> str:
        candidate_state = self.state["candidates"][candidate_id]
        if candidate_state.get("problem_id"):
            return str(candidate_state["problem_id"])
        numbers = []
        for path in problem_manifest_paths(self.problem_root):
            identifier = str(load_yaml(path).get("id") or "")
            match = re.fullmatch(r"ORP-(\d+)", identifier)
            if match:
                numbers.append(int(match.group(1)))
        if self.pool_root:
            for path in pool_snapshot_paths(self.pool_root / "pool" / "problems"):
                identifier = str(load_yaml(path).get("id") or "")
                match = re.fullmatch(r"ORP-(\d+)", identifier)
                if match:
                    numbers.append(int(match.group(1)))
        problem_id = f"ORP-{(max(numbers, default=0) + 1):04d}"
        candidate_state["problem_id"] = problem_id
        self.ledger.save()
        return problem_id

    def _compile(
        self,
        candidate: dict[str, Any],
        triage: dict[str, Any],
        assessment: dict[str, Any],
        verdict: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_id = candidate["candidate_id"]
        candidate_dir = self.run_dir / "candidates" / candidate_id
        problem_id = self._allocate_problem_id(candidate_id)
        slug = slugify(assessment["canonical_title"])[:72].strip("-")
        recorded_repo = str(
            self.state["candidates"][candidate_id].get("problem_repo") or ""
        )
        repo_dir = (
            Path(recorded_repo)
            if recorded_repo
            else self.problem_root / f"{problem_id}-{slug}"
        )
        output_path = candidate_dir / "compile.json"
        compile_key = f"candidate.{candidate_id}.compile"
        if output_path.is_file() and not repo_dir.is_dir():
            self.ledger.invalidate(lambda key: key == compile_key)
        elif repo_dir.is_dir():
            if not output_path.is_file():
                raise CampaignError(
                    f"refusing to overwrite untracked problem repository: {repo_dir}"
                )
            previous_compile = _load_json(output_path)
            manifest_path = repo_dir / "problem.yaml"
            expected_hash = str(previous_compile.get("manifest_sha256") or "")
            if (
                not manifest_path.is_file()
                or not expected_hash
                or file_sha256(manifest_path) != expected_hash
            ):
                raise CampaignError(
                    f"refusing to overwrite modified problem repository: {repo_dir}"
                )

        def produce() -> Produced:
            if not repo_dir.exists():
                self.problem_root.mkdir(parents=True, exist_ok=True)
                create_problem_repo(
                    self.repository_root / "template",
                    repo_dir,
                    schema_path=self.schemas / "problem.schema.json",
                    problem_id=problem_id,
                    title=assessment["canonical_title"],
                    slug=slug,
                )
            problem = self._problem_manifest(
                problem_id, candidate, triage, assessment
            )
            dump_yaml(repo_dir / "problem.yaml", problem)
            dump_json(
                repo_dir / "evidence" / "source-open-questions.json",
                {
                    "schema_version": 1,
                    "open_questions": candidate["source_open_questions"],
                },
            )
            dump_json(
                repo_dir / "evidence" / "research-assessment.json", assessment
            )
            dump_json(
                repo_dir / "evidence" / "reviewer-verdict.json", verdict
            )
            (repo_dir / "verifier" / "review.md").write_text(
                self._render_review(problem, assessment), encoding="utf-8"
            )
            (repo_dir / "verifier" / "ci.md").write_text(
                self._render_ci(problem, assessment), encoding="utf-8"
            )
            errors = validate_problem(
                repo_dir / "problem.yaml", self.schemas / "problem.schema.json"
            )
            if errors:
                raise CampaignError(
                    f"compiled problem {problem_id} is invalid: {'; '.join(errors)}"
                )
            return Produced(
                {
                    "schema_version": 1,
                    "candidate_id": candidate_id,
                    "problem_id": problem_id,
                    "problem_repo": str(repo_dir),
                    "manifest_sha256": file_sha256(repo_dir / "problem.yaml"),
                },
                {"exit_code": 0, "compiler": f"pipeline-v{PIPELINE_VERSION}"},
            )

        compiled = self.ledger.execute(
            key=compile_key,
            inputs=self._base_inputs(
                {
                    "candidate": candidate,
                    "triage": triage,
                    "assessment": assessment,
                    "verdict": verdict,
                    "problem_id": problem_id,
                }
            ),
            output_path=output_path,
            producer=produce,
        )
        self.state["candidates"][candidate_id].update(
            {
                "problem_id": problem_id,
                "problem_repo": str(repo_dir),
            }
        )
        self.ledger.save()
        return compiled

    def _problem_manifest(
        self,
        problem_id: str,
        candidate: dict[str, Any],
        triage: dict[str, Any],
        assessment: dict[str, Any],
    ) -> dict[str, Any]:
        open_current = (
            assessment["resolution_status"] in {"still_open", "partially_resolved"}
            and assessment["resolution_conclusion"]
            in {"confirmed_open", "likely_open"}
        )
        dispatch_ready = (
            open_current
            and assessment["importance_level"] in {"high", "medium"}
            and assessment["review_scope"] == "result-only"
            and assessment["ci_status"]
            in {"implemented", "partial", "pseudocode", "reviewer-only"}
            and bool(assessment["surviving_open_core"])
            and bool(assessment["success_condition"])
        )
        operational_ready = dispatch_ready and (
            (
                assessment["verification_mode"] == "machine-checkable"
                and assessment["ci_status"] == "implemented"
            )
            or (
                assessment["verification_mode"] == "hybrid"
                and assessment["ci_status"] in {"implemented", "partial"}
            )
            or (
                assessment["verification_mode"] == "llm-reviewable"
                and assessment["ci_status"]
                in {"implemented", "partial", "reviewer-only"}
            )
        )
        if assessment["resolution_status"] == "resolved":
            status = "resolved-externally"
        elif assessment["resolution_status"] == "refuted":
            status = "refuted-externally"
        elif assessment["resolution_status"] == "uncertain":
            status = "uncertain"
        elif operational_ready:
            status = "ready"
        elif dispatch_ready or assessment["ci_status"] == "blocked":
            status = "needs-verifier"
        else:
            status = "resolution-audited"
        mode_route = {
            "machine-checkable": "candidate-machine",
            "llm-reviewable": "candidate-llm",
            "hybrid": "candidate-hybrid",
            "expert-review": "manual-review",
            "unclassified": "reformulation",
        }
        route = (
            "closed"
            if status in {"resolved-externally", "refuted-externally"}
            else "status-audit"
            if status == "uncertain"
            else mode_route[assessment["verification_mode"]]
        )
        if status in {"resolved-externally", "refuted-externally"}:
            post_priority = "closed"
        elif assessment["importance_level"] == "high":
            post_priority = "high"
        elif assessment["importance_level"] == "medium":
            post_priority = "medium"
        else:
            post_priority = "hold"
        sources = []
        for source in candidate["source_open_questions"]:
            sources.append(
                {
                    "node_id": str(source.get("global_id") or source.get("id") or ""),
                    "paper_id": str(source.get("paper_id") or ""),
                    "local_id": str(source.get("id") or ""),
                    "exact_text": str(source.get("content") or ""),
                    "publication_date": "",
                    "paper_title": str(source.get("paper_title") or ""),
                    "paper_doi": str(source.get("paper_doi") or ""),
                    "source_path": "data.papers[].open_questions",
                }
            )
        return {
            "schema_version": 1,
            "id": problem_id,
            "title": assessment["canonical_title"],
            "domain": candidate["domain"],
            "status": status,
            "question": {
                "canonical_statement": assessment["canonical_statement"],
                "definitions": assessment["definitions"],
                "scope": assessment["scope"],
                "aliases": assessment["aliases"],
            },
            "source_open_questions": sources,
            "resolution_audit": {
                "checked_at": today(),
                "checked_through": assessment["checked_through"],
                "status": assessment["resolution_status"],
                "coverage": assessment["coverage"],
                "surviving_open_core": assessment["surviving_open_core"],
                "conclusion": {
                    "label": assessment["resolution_conclusion"],
                    "confidence": assessment["resolution_confidence"],
                    "rationale": assessment["status_rationale"],
                    "literature_treatment": assessment["literature_treatment"],
                },
                "evidence": assessment["evidence"],
                "progress_assessment": {
                    "major_progress_found": assessment["major_progress_found"],
                    "effect": assessment["major_progress_effect"],
                    "surviving_core_reassessed": True,
                    "importance_reassessed": True,
                    "verification_reassessed": True,
                    "decision": assessment["post_progress_decision"],
                    "derived_problem_ids": [],
                },
            },
            "importance": {
                "motivation": assessment["importance_motivation"],
                "consequences_of_progress": assessment["consequences_of_progress"],
                "current_best_result": assessment["current_best_result"],
            },
            "research_triage": {
                "reviewed_at": today(),
                "importance_level": assessment["importance_level"],
                "audit_priority": (
                    "high"
                    if triage["importance_level"] == "high"
                    else "medium"
                    if triage["importance_level"] == "medium"
                    else "hold"
                ),
                "post_audit_priority": post_priority,
                "route": route,
                "rationale": triage["rationale"],
            },
            "discovery_contract": {
                "artifact_type": assessment["artifact_type"],
                "candidate_format": assessment["candidate_format"],
                "verifier_command": "make verify",
                "success_condition": assessment["success_condition"],
                "partial_progress_metrics": assessment["partial_progress_metrics"],
                "verification_profile": {
                    "mode": assessment["verification_mode"],
                    "ease": assessment["verification_ease"],
                    "protocol": (
                        "verifier/review.md"
                        if assessment["verification_mode"]
                        in {"llm-reviewable", "hybrid"}
                        else assessment["verification_protocol"]
                    ),
                    "rationale": assessment["verification_rationale"],
                },
            },
            "reviewer_contract": {
                "scope": assessment["review_scope"],
                "difficulty": assessment["review_difficulty"],
                "checklist": "verifier/review.md",
                "estimated_review_time": assessment["estimated_review_time"],
                "acceptance_boundary": assessment["acceptance_boundary"],
            },
            "ci_contract": {
                "status": assessment["ci_status"],
                "workflow": ".github/workflows/verify.yml",
                "driver": "tools/ci_verify.py",
                "pseudocode": "verifier/ci.md",
                "runner": assessment["ci_runner"],
                "estimated_runtime": assessment["ci_estimated_runtime"],
                "timeout_minutes": assessment["ci_timeout_minutes"],
            },
            "compute": assessment["compute"],
        }

    @staticmethod
    def _render_review(
        problem: dict[str, Any], assessment: dict[str, Any]
    ) -> str:
        lines = [
            "# Reviewer-agent acceptance protocol",
            "",
            "This protocol checks only the submitted result under the exact local",
            "claim. Current openness and novelty remain separate literature judgments.",
            "",
            f"- Problem: `{problem['id']}`",
            f"- Scope: `{assessment['review_scope']}`",
            f"- Expected time: {assessment['estimated_review_time']}",
            f"- Acceptance boundary: {assessment['acceptance_boundary']}",
            "",
            "## Ordered checks",
            "",
        ]
        lines.extend(
            f"{index}. {item}"
            for index, item in enumerate(assessment["review_checklist"], start=1)
        )
        lines.extend(
            [
                "",
                "## Verdict",
                "",
                "Return `accept-local`, `reject`, `needs-expert`, or",
                "`protocol-incomplete`, with checks run and failed checks.",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _render_ci(problem: dict[str, Any], assessment: dict[str, Any]) -> str:
        lines = [
            "# Problem-specific CI contract",
            "",
            f"- Status: `{assessment['ci_status']}`",
            f"- Runner: {assessment['ci_runner']}",
            f"- Estimated runtime: {assessment['ci_estimated_runtime']}",
            f"- Hard timeout: {assessment['ci_timeout_minutes']} minutes",
            f"- Acceptance condition: {assessment['success_condition']}",
            "",
            "## Pseudocode",
            "",
            "```text",
            *assessment["ci_pseudocode"],
            "```",
            "",
            "A pseudocode contract is sufficient for research dispatch but does not",
            "authorize automatic acceptance until the substantive checker is implemented.",
            "",
        ]
        return "\n".join(lines)

    def _write_low_priority(self, records: list[dict[str, Any]]) -> None:
        payload = {
            "schema_version": 1,
            "run_id": self.state["run_id"],
            "count": len(records),
            "candidates": records,
        }
        dump_json(self.run_dir / "low-priority.json", payload)
        if self.pool_root:
            destination = (
                self.pool_root
                / "inbox"
                / self.state["run_id"]
                / "low-priority.json"
            )
            dump_json(destination, payload)

    def _sync_and_rank(self, accepted: list[str]) -> list[dict[str, Any]]:
        manifests = problem_manifest_paths(self.problem_root)
        manifest_hashes = [
            {
                "path": str(path),
                "sha256": file_sha256(path),
            }
            for path in manifests
        ]
        output_path = self.run_dir / "ranking.json"
        stage_key = "campaign.sync-and-rank"
        if (
            self.pool_root
            and output_path.is_file()
            and not (self.pool_root / "pool" / "catalog.jsonl").is_file()
        ):
            self.ledger.invalidate(lambda key: key == stage_key)

        def produce() -> Produced:
            records: list[dict[str, Any]]
            metadata: dict[str, Any] = {"exit_code": 0}
            if self.pool_root:
                pool_out = self.pool_root / "pool"
                command = [
                    sys.executable,
                    str(self.repository_root / "scripts" / "sync_pool.py"),
                    str(self.problem_root),
                    "--out",
                    str(pool_out),
                ]
                completed = subprocess.run(
                    command,
                    cwd=self.repository_root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if completed.returncode != 0:
                    raise CampaignError(
                        f"pool sync failed: {completed.stderr or completed.stdout}"
                    )
                records = [
                    json.loads(line)
                    for line in (pool_out / "catalog.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line.strip()
                ]
                metadata.update(
                    {
                        "command": command,
                        "stdout": completed.stdout,
                        "pool": str(pool_out),
                    }
                )
            else:
                records = []
                for manifest in problem_manifest_paths(self.problem_root):
                    problem = load_yaml(manifest)
                    records.append(
                        problem_to_record(problem, manifest.parent.name)
                    )
            ranking = rank_records(records)
            return Produced(
                {
                    "schema_version": 1,
                    "run_id": self.state["run_id"],
                    "accepted_problem_ids": accepted,
                    "ranking": ranking,
                },
                metadata,
            )

        result = self.ledger.execute(
            key=stage_key,
            inputs=self._base_inputs(
                {
                    "accepted_problem_ids": accepted,
                    "problem_manifests": manifest_hashes,
                    "pool_root": str(self.pool_root or ""),
                }
            ),
            output_path=output_path,
            producer=produce,
        )
        return result["ranking"]

    def retry(self, candidate_id: str, stage: str) -> dict[str, Any]:
        if candidate_id not in self.state.get("candidates", {}):
            raise CampaignError(f"unknown candidate: {candidate_id}")
        if stage not in STAGE_ORDER:
            raise CampaignError(f"stage must be one of: {', '.join(STAGE_ORDER)}")
        start = STAGE_ORDER.index(stage)
        downstream = set(STAGE_ORDER[start:])

        def should_remove(key: str) -> bool:
            prefix = f"candidate.{candidate_id}."
            if not key.startswith(prefix):
                return False
            suffix = key[len(prefix) :]
            return any(suffix == name or suffix.startswith(f"{name}.") for name in downstream)

        self.ledger.invalidate(should_remove)
        self.state["candidates"][candidate_id]["status"] = "retry_requested"
        self.state["status"] = "created"
        self.ledger.save()
        return self.run()


def resolve_run_dir(value: str, runs_root: Path | None = None) -> Path:
    candidate = Path(value)
    if candidate.is_dir():
        return candidate.resolve()
    if runs_root is None:
        raise CampaignError("pass a campaign directory or provide --runs-root")
    resolved = (runs_root / value).resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"campaign not found: {resolved}")
    return resolved
