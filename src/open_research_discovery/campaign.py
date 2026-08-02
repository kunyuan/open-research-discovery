from __future__ import annotations

import difflib
import fcntl
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .agent import (
    AgentOutputError,
    AgentRun,
    CodexRunner,
    file_sha256,
)
from .common import (
    candidate_identity_text,
    dump_json,
    dump_json_atomic,
    dump_yaml,
    load_yaml,
    pool_snapshot_paths,
    slugify,
    utc_now,
)
from .lkm import PAPER_GRAPH_URL, collect_paper_open_questions
from .pool import normalize_text, problem_to_record, text_tokens
from .problem_contract import (
    materialize_problem_contract_repository,
    problem_contract_from_assessment,
    validate_problem_contract,
    validate_problem_contract_readme,
    write_problem_contract_repository,
)
from .ranking import (
    VERIFICATION_DIFFICULTY_RUBRIC,
    rank_records,
)
from .strategies import (
    EXPLICIT_OPEN_QUESTIONS,
    TOPIC_DECOMPOSITION,
    CandidateSeed,
    DiscoveryStrategy,
    STRATEGY_REGISTRY,
    configured_strategies,
)
from .validation import READY_RESOLUTION_STATUSES, validate_problem


PIPELINE_VERSION = 12
SKILL_NAME = "research-evidence-search"
STAGE_ORDER = ("triage", "research", "problem-review", "compile")


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
    return (
        "sha256:"
        + hashlib.sha256(str(question.get("content") or "").encode("utf-8")).hexdigest()
    )


def _candidate_id(cluster: dict[str, Any]) -> str:
    identity = {
        "statement": normalize_text(str(cluster["canonical_statement"])),
        "sources": sorted(cluster["source_keys"]),
    }
    return "CAN-" + _json_sha256(identity)[:12].upper()


def _exact_candidate_id(cluster: dict[str, Any]) -> str:
    identity = {
        "statement": candidate_identity_text(str(cluster["canonical_statement"])),
        "sources": sorted(cluster["source_keys"]),
    }
    return "CAN-" + _json_sha256(identity)[:12].upper()


def _candidate_ids(clusters: list[dict[str, Any]]) -> list[str]:
    candidate_ids: set[str] = set()
    exact_candidate_ids: set[str] = set()
    resolved: list[str] = []
    for cluster in clusters:
        candidate_id = _candidate_id(cluster)
        exact_candidate_id = _exact_candidate_id(cluster)
        if candidate_id in candidate_ids:
            if exact_candidate_id in exact_candidate_ids:
                raise CampaignError(
                    "canonicalization produced duplicate candidate_id "
                    f"{candidate_id}; merge duplicate clusters before triage"
                )
            candidate_id = exact_candidate_id
            if candidate_id in candidate_ids:
                raise CampaignError(
                    "canonicalization produced an unresolved candidate_id "
                    f"collision for {candidate_id}"
                )
        candidate_ids.add(candidate_id)
        exact_candidate_ids.add(exact_candidate_id)
        resolved.append(candidate_id)
    return resolved


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


EXCERPT_REPAIR_MIN_RATIO = 0.98
_EXCERPT_ANCHOR_MIN = 6
_EXCERPT_WINDOW_SLACK = 6
_UNICODE_DASHES = frozenset("‐‑‒–—―−")


def _excerpt_alignment_form(text: str) -> str:
    """Map text one-to-one for alignment: casefold, dashes to ``-``, space."""

    chars: list[str] = []
    for char in text:
        if char in _UNICODE_DASHES:
            chars.append("-")
        elif char.isspace():
            chars.append(" ")
        else:
            lowered = char.lower()
            chars.append(lowered if len(lowered) == 1 else char)
    return "".join(chars)


def _align_excerpt(excerpt: str, content: str) -> tuple[str, float, bool] | None:
    """Locate the unique best source-content window for a non-exact excerpt.

    Returns ``(raw_source_span, similarity, unique)`` or ``None`` when the
    excerpt shares no usable anchor with the content. Similarity is computed
    on the per-character alignment form, whose indices map back to the raw
    content one-to-one; ``unique`` is False when two disjoint windows tie at
    the top similarity.
    """

    needle = _excerpt_alignment_form(excerpt.strip())
    haystack = _excerpt_alignment_form(content)
    if not needle or not haystack:
        return None
    matcher = difflib.SequenceMatcher(None, needle, haystack, autojunk=False)
    anchor = matcher.find_longest_match(0, len(needle), 0, len(haystack))
    if anchor.size < min(_EXCERPT_ANCHOR_MIN, len(needle)):
        return None
    anchor_text = needle[anchor.a : anchor.a + anchor.size]
    occurrences: list[int] = []
    position = haystack.find(anchor_text)
    while position != -1:
        occurrences.append(position)
        position = haystack.find(anchor_text, position + 1)
    base = len(needle)
    scored: dict[tuple[int, int], float] = {}
    for position in occurrences:
        approx = position - anchor.a
        start_lo = max(0, approx - _EXCERPT_WINDOW_SLACK)
        start_hi = min(len(haystack) - 1, approx + _EXCERPT_WINDOW_SLACK)
        for start in range(start_lo, start_hi + 1):
            end_lo = start + max(1, base - _EXCERPT_WINDOW_SLACK)
            end_hi = min(len(haystack), start + base + _EXCERPT_WINDOW_SLACK)
            for end in range(end_lo, end_hi + 1):
                if (start, end) in scored:
                    continue
                scored[(start, end)] = difflib.SequenceMatcher(
                    None, needle, haystack[start:end]
                ).ratio()
    best_ratio = max(scored.values())
    best_windows = sorted(
        window for window, ratio in scored.items() if ratio >= best_ratio - 1e-9
    )
    unique = not any(
        first[1] <= second[0]
        for index, first in enumerate(best_windows)
        for second in best_windows[index + 1 :]
    )
    start, end = min(
        best_windows, key=lambda window: (abs(window[1] - window[0] - base), window)
    )
    while start < end and content[start].isspace():
        start += 1
    while end > start and content[end - 1].isspace():
        end -= 1
    return content[start:end], best_ratio, unique


def _excerpt_canonical_form(text: str) -> str:
    chars: list[str] = []
    for char in text:
        if char == "$":
            continue
        if char in _UNICODE_DASHES:
            chars.append("-")
        elif char.isspace():
            chars.append(" ")
        else:
            chars.append(char)
    return re.sub(r" +", " ", "".join(chars))


def _excerpt_diff_is_benign(excerpt: str, span: str) -> bool:
    """True when excerpt vs span differ only by whitelisted transcription
    noise: first-letter case, added/removed LaTeX ``$`` delimiters,
    leading/trailing whitespace, and Unicode whitespace/dash equivalents."""

    left = excerpt.strip()
    right = span.strip()
    if not left or not right:
        return False
    if left[0] != right[0]:
        if left[0].isalpha() and left[0].lower() == right[0].lower():
            left = left[0].lower() + left[1:]
            right = right[0].lower() + right[1:]
        else:
            return False
    return _excerpt_canonical_form(left) == _excerpt_canonical_form(right)


@dataclass
class Produced:
    output: dict[str, Any]
    metadata: dict[str, Any]


class StageLedger:
    def __init__(self, run_dir: Path, state: dict[str, Any]) -> None:
        self.run_dir = run_dir
        self.state = state
        self._lock = threading.RLock()

    def save(self) -> None:
        with self._lock:
            dump_json_atomic(self.run_dir / "state.json", self.state)

    def invalidate(self, predicate: Callable[[str], bool]) -> None:
        with self._lock:
            stages = self.state.setdefault("stages", {})
            for key, record in stages.items():
                if predicate(key):
                    record["status"] = "invalidated"
                    record["invalidated_at"] = utc_now()
            self.save()

    def stage_record(self, key: str) -> dict[str, Any]:
        with self._lock:
            return dict(self.state.get("stages", {}).get(key, {}))

    def update_candidate(self, candidate_id: str, values: dict[str, Any]) -> None:
        with self._lock:
            self.state.setdefault("candidates", {}).setdefault(candidate_id, {}).update(
                values
            )
            self.save()

    def execute(
        self,
        *,
        key: str,
        inputs: dict[str, Any],
        output_path: Path,
        producer: Callable[[], Produced],
        schema_path: Path | None = None,
        output_validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        input_sha = _json_sha256(inputs)
        with self._lock:
            stages = self.state.setdefault("stages", {})
            previous = stages.get(key) or {}
            if (
                previous.get("status") == "completed"
                and previous.get("input_sha256") == input_sha
                and output_path.is_file()
                and previous.get("output_sha256") == file_sha256(output_path)
            ):
                cached = _load_json(output_path)
                if output_validator is None:
                    return cached
                try:
                    output_validator(cached)
                except Exception:
                    pass
                else:
                    return cached

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
                "schema": (_relative(schema_path, self.run_dir) if schema_path else ""),
                "schema_sha256": file_sha256(schema_path) if schema_path else "",
                "started_at": utc_now(),
            }
            stages[key] = record
            self.save()
        try:
            produced = producer()
            if output_validator is not None:
                output_validator(produced.output)
            if schema_path:
                errors = _schema_errors(produced.output, schema_path)
                if errors:
                    raise CampaignError(
                        f"{key} output failed schema validation: {'; '.join(errors[:8])}"
                    )
            dump_json(output_path, produced.output)
            with self._lock:
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
            with self._lock:
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
        self.skill_dir = self.repository_root / ".agents" / "skills" / SKILL_NAME
        self.skill_sha256 = _skill_hash(self.skill_dir)
        agent_config = config["agents"]
        workers = agent_config.get("workers")
        self.workers = 1 if workers is None else int(workers)
        networked_workers = agent_config.get("networked_workers")
        self.networked_workers = (
            self.workers if networked_workers is None else int(networked_workers)
        )
        retries = agent_config.get("retries")
        self.retries = 1 if retries is None else int(retries)
        backoff = agent_config.get("retry_backoff_seconds")
        self.retry_backoff_seconds = 5.0 if backoff is None else float(backoff)
        if not 1 <= self.workers <= 16:
            raise CampaignError("agents.workers must be between 1 and 16")
        if not 1 <= self.networked_workers <= 16:
            raise CampaignError("agents.networked_workers must be between 1 and 16")
        if not 0 <= self.retries <= 5:
            raise CampaignError("agents.retries must be between 0 and 5")
        if self.retry_backoff_seconds < 0:
            raise CampaignError("agents.retry_backoff_seconds must be non-negative")
        # One semaphore shared by every parallel region (domain discovery,
        # candidate triage, audit chains) so the number of
        # concurrent networked roles stays bounded campaign-wide.
        self._networked_semaphore = threading.Semaphore(self.networked_workers)
        self.agent_runner = agent_runner or CodexRunner(
            repository_root=self.repository_root,
            executable=agent_config["codex_executable"],
            model=agent_config["model"],
            sandbox=agent_config["sandbox"],
            networked_sandbox=agent_config.get("networked_sandbox", "workspace-write"),
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
        pipeline = cls(
            repository_root=repository_root,
            run_dir=run_dir,
            config=config,
            agent_runner=agent_runner,
            paper_collector=paper_collector,
        )
        interrupted = False
        for record in pipeline.state.get("stages", {}).values():
            if record.get("status") == "running":
                record["status"] = "interrupted"
                record["interrupted_at"] = utc_now()
                interrupted = True
        if interrupted:
            pipeline.state["status"] = "interrupted"
            pipeline.state["updated_at"] = utc_now()
            pipeline.ledger.save()
        return pipeline

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
        output_validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        schema_path = self.schemas / "stages" / schema_name

        def produce() -> Produced:
            return self._invoke_agent(
                role=role,
                prompt=prompt,
                schema_path=schema_path,
                output_path=output_path,
                events_path=events_path,
            )

        return self.ledger.execute(
            key=stage_key,
            inputs=self._base_inputs(
                {
                    "role": role,
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "schema_sha256": file_sha256(schema_path),
                    "model": self.config["agents"]["model"] or "configured-default",
                    "payload": inputs,
                }
            ),
            output_path=output_path,
            producer=produce,
            schema_path=schema_path,
            output_validator=output_validator,
        )

    def _invoke_agent(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> Produced:
        """Run one agent call under the shared governance policy.

        Networked roles (discovery, research) must hold a permit from the
        campaign-wide semaphore so concurrent network agents never exceed
        ``agents.networked_workers``; non-networked roles are unlimited.
        Invocation failures (nonzero exit, missing output, timeout,
        transport errors) are retried up to ``agents.retries`` times with
        exponential backoff ``retry_backoff_seconds * 2**attempt``. Contract
        failures are not retried: an ``AgentOutputError`` means the call
        completed but returned unusable structured output, and output
        validators or schema checks run outside this wrapper in
        ``StageLedger.execute``; replaying those would waste agent budget on
        an outcome the pipeline must reject anyway. Cached ledger hits never
        reach this method.
        """
        networked = role in CodexRunner.NETWORKED_ROLES
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(self.retry_backoff_seconds * 2 ** (attempt - 1))
            if networked:
                self._networked_semaphore.acquire()
            try:
                result: AgentRun = self.agent_runner.run(
                    role=role,
                    prompt=prompt,
                    schema_path=schema_path,
                    output_path=output_path,
                    events_path=events_path,
                )
                return Produced(result.output, result.metadata)
            except AgentOutputError:
                raise
            except Exception as error:
                last_error = error
            finally:
                if networked:
                    self._networked_semaphore.release()
        assert last_error is not None
        raise last_error

    def run(self) -> dict[str, Any]:
        self.state["status"] = "running"
        self.state["error"] = ""
        self.state["updated_at"] = utc_now()
        self.ledger.save()
        try:
            seeds = self._discover_candidate_seeds()
            candidates = self._canonicalize(seeds)
            workers = self.workers
            triage_by_id = self._triage_candidates(
                candidates,
                workers=workers,
            )
            accepted: list[str] = []
            triage_deferred: list[dict[str, Any]] = []
            audit_candidates: list[dict[str, Any]] = []
            for candidate in candidates:
                candidate_id = candidate["candidate_id"]
                triage = triage_by_id[candidate_id]
                candidate_state = self.state["candidates"][candidate_id]
                if not self._passes_audit_gate(triage):
                    candidate_state["status"] = "triage_deferred"
                    triage_deferred.append(
                        {
                            "candidate_id": candidate_id,
                            "canonical_title": candidate["canonical_title"],
                            "triage": triage,
                        }
                    )
                    self.ledger.save()
                    continue
                audit_candidates.append(candidate)

            preselection_count = len(audit_candidates)
            shortlist_limit = self._portfolio_limit(shortlist=True)
            shortlisted = self._select_quality_diverse(
                audit_candidates,
                scores={
                    candidate["candidate_id"]: self._scientific_significance(
                        triage_by_id[candidate["candidate_id"]]
                    )
                    for candidate in audit_candidates
                },
                limit=shortlist_limit,
            )
            shortlisted_ids = {
                candidate["candidate_id"] for candidate in shortlisted
            }
            for candidate in audit_candidates:
                if candidate["candidate_id"] not in shortlisted_ids:
                    self.state["candidates"][candidate["candidate_id"]]["status"] = (
                        "shortlist_deferred"
                    )
            audit_candidates = shortlisted
            self.ledger.save()

            # Candidates whose Research retry was deferred (retry_requested
            # with the research stage invalidated) re-enter the parallel audit
            # here; their applied-feedback snapshot is advanced again so the
            # rerun addresses every accumulated reviewer concern. Deferred
            # candidates that no longer pass the importance gate were diverted to
            # triage_deferred above and are skipped with the reason recorded.
            deferred_retry_ids = frozenset(
                candidate["candidate_id"]
                for candidate in audit_candidates
                if self._is_deferred_research_retry(candidate["candidate_id"])
            )
            audits_by_id = self._audit_candidates(
                audit_candidates,
                triage_by_id,
                workers=workers,
                apply_pending_review_feedback_ids=deferred_retry_ids,
            )
            publication_candidates: list[dict[str, Any]] = []
            for candidate in audit_candidates:
                verdict, assessment = audits_by_id[candidate["candidate_id"]]
                if verdict["verdict"] == "accept" and self._passes_publication_gate(
                    assessment
                ):
                    publication_candidates.append(candidate)
            final_candidates = self._select_quality_diverse(
                publication_candidates,
                scores={
                    candidate["candidate_id"]: self._scientific_significance(
                        audits_by_id[candidate["candidate_id"]][1]
                    )
                    for candidate in publication_candidates
                },
                limit=self._portfolio_limit(shortlist=False),
            )
            final_ids = {candidate["candidate_id"] for candidate in final_candidates}
            for candidate in audit_candidates:
                candidate_id = candidate["candidate_id"]
                triage = triage_by_id[candidate_id]
                verdict, assessment = audits_by_id[candidate_id]
                candidate_state = self.state["candidates"][candidate_id]
                candidate_state["problem_review_verdict"] = verdict["verdict"]
                if candidate_id in final_ids:
                    compiled = self._compile(candidate, triage, assessment, verdict)
                    accepted.append(compiled["problem_id"])
                    candidate_state["status"] = "accepted"
                elif verdict["verdict"] == "accept" and self._passes_publication_gate(
                    assessment
                ):
                    candidate_state["status"] = "portfolio_deferred"
                elif verdict["verdict"] == "accept":
                    candidate_state["status"] = "audited_out"
                elif verdict["verdict"] == "reject":
                    candidate_state["status"] = "rejected"
                else:
                    candidate_state["status"] = "needs_revision"
                self.ledger.save()
            dump_json(
                self.run_dir / "portfolio-selection.json",
                {
                    "schema_version": 1,
                    "eligible_before_shortlist": preselection_count,
                    "shortlist_limit": shortlist_limit,
                    "shortlisted_candidate_ids": [
                        candidate["candidate_id"] for candidate in audit_candidates
                    ],
                    "final_limit": self._portfolio_limit(shortlist=False),
                    "selected_candidate_ids": [
                        candidate["candidate_id"] for candidate in final_candidates
                    ],
                },
            )
            self._write_triage_deferred(triage_deferred)
            ranking = self._sync_and_rank(accepted)
            self.state.update(
                {
                    "status": "completed",
                    "updated_at": utc_now(),
                    "summary": {
                        "source_open_questions": sum(
                            seed["origin_class"] == "explicit_source_question"
                            for seed in seeds
                        ),
                        "candidate_seeds": len(seeds),
                        "canonical_candidates": len(candidates),
                        "accepted_problem_ids": accepted,
                        "triage_deferred_count": len(triage_deferred),
                        "ranked_problem_count": len(ranking),
                    },
                }
            )
            self.ledger.save()
            return self.state["summary"]
        except Exception as error:
            self.state["status"] = "failed"
            self.state["error"] = f"{type(error).__name__}: {error}"
            self.state["updated_at"] = utc_now()
            self.ledger.save()
            raise

    def _is_deferred_research_retry(self, candidate_id: str) -> bool:
        """A candidate parked by ``retry(..., defer=True)`` for Research.

        The operator asked for a Research re-audit (status retry_requested)
        and the research stage was invalidated but has not completed since,
        so the next resume must audit the candidate with the accumulated
        reviewer feedback applied.
        """
        return (
            self.state.get("candidates", {}).get(candidate_id, {}).get("status")
            == "retry_requested"
            and self.ledger.stage_record(f"candidate.{candidate_id}.research").get(
                "status"
            )
            != "completed"
        )

    def prepare_benchmark(
        self,
        *,
        workers: int = 1,
    ) -> dict[str, Any]:
        """Recall, atomize, and triage candidates without status research."""

        self.state["status"] = "benchmark_preparing"
        self.state["error"] = ""
        self.state["updated_at"] = utc_now()
        self.ledger.save()
        try:
            seeds = self._discover_candidate_seeds()
            candidates = self._canonicalize(seeds)
            triage = self.triage_all_for_benchmark(
                candidate_ids=[candidate["candidate_id"] for candidate in candidates],
                workers=workers,
            )
            summary = {
                "schema_version": 3,
                "source_open_questions": sum(
                    seed["origin_class"] == "explicit_source_question"
                    for seed in seeds
                ),
                "atomic_candidates": len(candidates),
                "triaged_candidates": len(candidates),
                "candidate_count": triage["candidate_count"],
                "pass_count": triage["pass_count"],
                "fail_count": triage["fail_count"],
            }
            self.state["benchmark_prepare_summary"] = summary
            self.ledger.save()
            return summary
        except Exception:
            self.state["status"] = "failed"
            self.state["updated_at"] = utc_now()
            self.ledger.save()
            raise

    def triage_all_for_benchmark(
        self,
        *,
        candidate_ids: list[str] | None = None,
        workers: int = 1,
    ) -> dict[str, Any]:
        """Produce baseline screening predictions without status research."""

        if workers < 1 or workers > 16:
            raise CampaignError("workers must be between 1 and 16")
        source_path = self.run_dir / "candidate-seeds.json"
        canonical_path = self.run_dir / "canonicalization.json"
        if not source_path.is_file() or not canonical_path.is_file():
            raise CampaignError(
                "benchmark triage requires completed ingestion and canonicalization"
            )
        seeds_document = _load_json(source_path)
        seeds = list(seeds_document.get("candidate_seeds") or [])
        self.state["status"] = "benchmark_triaging"
        self.state["error"] = ""
        self.state["updated_at"] = utc_now()
        self.ledger.save()
        try:
            candidates = self._materialize_candidates(_load_json(canonical_path), seeds)
            requested_ids = set(
                candidate_ids
                or self.state.get("triage_candidate_ids")
                or [candidate["candidate_id"] for candidate in candidates]
            )
            known_ids = {candidate["candidate_id"] for candidate in candidates}
            unknown_ids = sorted(requested_ids - known_ids)
            if unknown_ids:
                raise CampaignError(
                    "triage requested unknown candidate IDs: " + ", ".join(unknown_ids)
                )
            candidates = [
                candidate
                for candidate in candidates
                if candidate["candidate_id"] in requested_ids
            ]
            triage_by_id = self._triage_candidates(candidates, workers=workers)

            predictions: list[dict[str, Any]] = []
            for candidate in candidates:
                candidate_id = candidate["candidate_id"]
                triage = triage_by_id[candidate_id]
                passed = self._passes_triage_publication_gate(triage)
                self.state["candidates"][candidate_id]["benchmark_triage_status"] = (
                    "pass" if passed else "fail"
                )
                predictions.append(
                    {
                        "candidate_id": candidate_id,
                        "domain": candidate["domain"],
                        "canonical_title": candidate["canonical_title"],
                        "prediction_path": _relative(
                            self.run_dir / "candidates" / candidate_id / "triage.json",
                            self.run_dir,
                        ),
                        "gate": "pass" if passed else "deferred",
                        "importance_level": triage["importance_level"],
                        "expected_result": triage["expected_result"],
                        "verification_difficulty": triage["verification_difficulty"],
                        "ci_status": triage["ci_status"],
                        "passes_pipeline_gate": passed,
                    }
                )
                self.ledger.save()
            summary = {
                "schema_version": 2,
                "candidate_pool_count": len(known_ids),
                "candidate_count": len(predictions),
                "pass_count": sum(item["passes_pipeline_gate"] for item in predictions),
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

    def _triage_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        workers: int,
    ) -> dict[str, dict[str, Any]]:
        if workers < 1 or workers > 16:
            raise CampaignError("workers must be between 1 and 16")
        if workers == 1 or len(candidates) < 2:
            return {
                candidate["candidate_id"]: self._triage(candidate)
                for candidate in candidates
            }

        triage_by_id: dict[str, dict[str, Any]] = {}
        errors: list[tuple[str, Exception]] = []
        with ThreadPoolExecutor(
            max_workers=min(workers, len(candidates)),
            thread_name_prefix="triage",
        ) as executor:
            future_to_candidate = {
                executor.submit(self._triage, candidate): candidate
                for candidate in candidates
            }
            for future in as_completed(future_to_candidate):
                candidate = future_to_candidate[future]
                candidate_id = candidate["candidate_id"]
                try:
                    triage_by_id[candidate_id] = future.result()
                except Exception as error:
                    errors.append((candidate_id, error))
        if errors:
            rendered = "; ".join(
                f"{candidate_id}: {type(error).__name__}: {error}"
                for candidate_id, error in sorted(errors)
            )
            raise CampaignError(
                f"{len(errors)} parallel triage worker(s) failed: {rendered}"
            )
        return triage_by_id

    def _audit_candidates(
        self,
        candidates: list[dict[str, Any]],
        triage_by_id: dict[str, dict[str, Any]],
        *,
        workers: int,
        apply_pending_review_feedback_ids: frozenset[str] = frozenset(),
    ) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
        if workers < 1 or workers > 16:
            raise CampaignError("workers must be between 1 and 16")

        def audit(
            candidate: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            candidate_id = candidate["candidate_id"]
            kwargs: dict[str, Any] = {}
            if candidate_id in apply_pending_review_feedback_ids:
                kwargs["apply_pending_review_feedback"] = True
            return self._research_and_problem_review(
                candidate,
                triage_by_id[candidate_id],
                **kwargs,
            )

        if workers == 1 or len(candidates) < 2:
            return {
                candidate["candidate_id"]: audit(candidate) for candidate in candidates
            }

        audits_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        errors: list[tuple[str, Exception]] = []
        with ThreadPoolExecutor(
            max_workers=min(workers, len(candidates)),
            thread_name_prefix="candidate-audit",
        ) as executor:
            future_to_candidate = {
                executor.submit(audit, candidate): candidate for candidate in candidates
            }
            for future in as_completed(future_to_candidate):
                candidate = future_to_candidate[future]
                candidate_id = candidate["candidate_id"]
                try:
                    audits_by_id[candidate_id] = future.result()
                except Exception as error:
                    errors.append((candidate_id, error))
        if errors:
            rendered = "; ".join(
                f"{candidate_id}: {type(error).__name__}: {error}"
                for candidate_id, error in sorted(errors)
            )
            raise CampaignError(
                f"{len(errors)} parallel candidate audit worker(s) failed: {rendered}"
            )
        return {
            candidate["candidate_id"]: audits_by_id[candidate["candidate_id"]]
            for candidate in candidates
        }

    def _discover_candidate_seeds(self) -> list[dict[str, Any]]:
        """Run configured seed producers and persist their common contract."""

        seeds: list[CandidateSeed] = []
        strategy_ids: list[str] = []
        for strategy_config in configured_strategies(self.config):
            strategy_id = str(strategy_config["type"])
            strategy = STRATEGY_REGISTRY.get(strategy_id)
            if strategy is None:
                raise CampaignError(f"unknown discovery strategy: {strategy_id}")
            if strategy_id in strategy_ids:
                raise CampaignError(
                    f"discovery strategy may be configured only once: {strategy_id}"
                )
            strategy_ids.append(strategy_id)
            seeds.extend(strategy.discover(self, strategy_config))

        unique: dict[str, CandidateSeed] = {}
        for seed in seeds:
            previous = unique.get(seed.source_key)
            if previous is not None and previous != seed:
                raise CampaignError(
                    f"discovery strategies produced conflicting source_key {seed.source_key}"
                )
            unique.setdefault(seed.source_key, seed)
        materialized = [seed.to_dict() for seed in unique.values()]
        seed_schema = self.schemas / "candidate-seed.schema.json"
        seed_errors = [
            f"{seed['source_key']}: {error}"
            for seed in materialized
            for error in _schema_errors(seed, seed_schema)
        ]
        if seed_errors:
            raise CampaignError(
                "discovery strategy produced invalid candidate seeds: "
                + "; ".join(seed_errors)
            )
        dump_json(
            self.run_dir / "candidate-seeds.json",
            {
                "schema_version": 1,
                "strategies": strategy_ids,
                "count": len(materialized),
                "candidate_seeds": materialized,
            },
        )
        return materialized

    @staticmethod
    def _explicit_question_seed(
        question: dict[str, Any], strategy: DiscoveryStrategy
    ) -> CandidateSeed:
        content = str(question.get("content") or "").strip()
        if not content:
            raise CampaignError("explicit open-question seed has empty content")
        domain_ids = list(question.get("domain_ids") or [question["domain_id"]])
        return CandidateSeed(
            # Preserve the v10 source key so default-strategy candidate IDs and
            # resumable artifacts remain stable across the strategy migration.
            source_key=str(question["source_key"]),
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.version,
            origin_class="explicit_source_question",
            domain_ids=domain_ids,
            title=str(question.get("paper_title") or "Explicit LKM open question"),
            content=content,
            source_records=[question],
            origin={
                "source_path": "data.papers[].open_questions",
                "source_key": question["source_key"],
                "global_id": str(question.get("global_id") or ""),
                "local_id": str(question.get("id") or ""),
                "paper_id": str(question.get("paper_id") or ""),
                "paper_title": str(question.get("paper_title") or ""),
                "paper_doi": str(question.get("paper_doi") or ""),
            },
            provenance={"domain_ids": domain_ids},
        )

    def _discover_topic_decomposition(
        self,
        strategy_config: dict[str, Any],
        strategy: DiscoveryStrategy,
    ) -> list[CandidateSeed]:
        domains = list(self.config["domains"])
        if self.workers == 1 or len(domains) < 2:
            return [
                seed
                for domain in domains
                for seed in self._discover_topic_domain(
                    domain, strategy_config, strategy
                )
            ]
        results: dict[str, list[CandidateSeed]] = {}
        errors: list[tuple[str, Exception]] = []
        with ThreadPoolExecutor(
            max_workers=min(self.workers, len(domains)),
            thread_name_prefix="topic-decomposition",
        ) as executor:
            future_to_domain = {
                executor.submit(
                    self._discover_topic_domain, domain, strategy_config, strategy
                ): domain
                for domain in domains
            }
            for future in as_completed(future_to_domain):
                domain_id = future_to_domain[future]["id"]
                try:
                    results[domain_id] = future.result()
                except Exception as error:
                    errors.append((domain_id, error))
        if errors:
            rendered = "; ".join(
                f"{domain_id}: {type(error).__name__}: {error}"
                for domain_id, error in sorted(errors)
            )
            raise CampaignError(
                f"{len(errors)} topic-decomposition domain worker(s) failed: {rendered}"
            )
        return [seed for domain in domains for seed in results[domain["id"]]]

    def _discover_topic_domain(
        self,
        domain: dict[str, Any],
        strategy_config: dict[str, Any],
        strategy: DiscoveryStrategy,
    ) -> list[CandidateSeed]:
        domain_id = domain["id"]
        domain_dir = self.run_dir / "domains" / domain_id / "topic-decomposition"
        search_groups = int(strategy_config.get("search_groups", 4))
        sources = list(strategy_config.get("sources") or ["lkm", "web"])
        max_candidates = int(
            strategy_config.get(
                "max_candidates_per_domain",
                self.config["limits"]["questions_per_domain"],
            )
        )
        plan_prompt = f"""
You are the topic-decomposition planner. Turn the broad scientific topic below
into exactly {search_groups} independent search briefs. Use CDQ-style
operators to force distinct routes: gap/tension, analogy/transfer,
boundary/counterfactual, failure-routing, and measurement/reframing. Each
brief must name its coverage axis, positive queries, and disconfirming queries
that could reveal the alleged gap is already closed. Do not propose final
research questions and do not claim openness.

Domain id: {domain_id}
Topic: {domain["query"]}
Allowed sources: {json.dumps(sources)}
Seed papers: {json.dumps(domain["seed_papers"], ensure_ascii=False, indent=2)}
""".strip()
        plan = self._agent(
            stage_key=f"campaign.topic-plan.{domain_id}",
            role="strategy-planner",
            prompt=plan_prompt,
            schema_name="discovery-plan.schema.json",
            output_path=domain_dir / "search-plan.json",
            events_path=domain_dir / "events" / "search-plan.jsonl",
            inputs={
                "domain": domain,
                "strategy": strategy_config,
                "search_groups": search_groups,
            },
            output_validator=lambda value: self._validate_topic_plan(
                value, domain_id, search_groups
            ),
        )

        def search(brief: dict[str, Any]) -> dict[str, Any]:
            brief_id = brief["brief_id"]
            prompt = f"""
You are one independent evidence-search worker. Use ${SKILL_NAME} and search
only the assigned brief. Search the allowed LKM/web sources, inspect enough
context to avoid extracting a sentence out of context, and run the listed
disconfirming/freshness searches. Return evidence and possible gap anchors,
not polished research questions. An anchor may be an explicit gap, tension,
method failure, missing transfer, boundary case, or measurement gap. Every
anchor must cite source_ids present in this packet. Quote exact excerpts and
include surrounding context. If evidence is insufficient, return empty
anchors instead of inventing one.

Domain: {domain_id}
Broad topic: {domain["query"]}
Allowed sources: {json.dumps(sources)}
Assigned brief:
{json.dumps(brief, ensure_ascii=False, indent=2)}
""".strip()
            return self._agent(
                stage_key=f"campaign.topic-search.{domain_id}.{brief_id}",
                role="strategy-search",
                prompt=prompt,
                schema_name="evidence-packet.schema.json",
                output_path=domain_dir / "briefs" / brief_id / "evidence-packet.json",
                events_path=domain_dir / "briefs" / brief_id / "events.jsonl",
                inputs={"domain": domain, "brief": brief, "sources": sources},
                output_validator=lambda value: self._validate_evidence_packet(
                    value, domain_id, brief_id, sources
                ),
            )

        briefs = list(plan["briefs"])
        if self.workers == 1 or len(briefs) < 2:
            packets = [search(brief) for brief in briefs]
        else:
            packets_by_id: dict[str, dict[str, Any]] = {}
            with ThreadPoolExecutor(
                max_workers=min(self.workers, len(briefs)),
                thread_name_prefix=f"topic-search-{domain_id}",
            ) as executor:
                future_to_brief = {
                    executor.submit(search, brief): brief for brief in briefs
                }
                for future in as_completed(future_to_brief):
                    brief = future_to_brief[future]
                    packets_by_id[brief["brief_id"]] = future.result()
            packets = [packets_by_id[brief["brief_id"]] for brief in briefs]

        packet_source_ids = [
            source["source_id"] for packet in packets for source in packet["sources"]
        ]
        packet_anchor_ids = [
            anchor["anchor_id"] for packet in packets for anchor in packet["anchors"]
        ]
        if len(packet_source_ids) != len(set(packet_source_ids)):
            raise CampaignError("topic evidence source_id values must be unique per domain")
        if len(packet_anchor_ids) != len(set(packet_anchor_ids)):
            raise CampaignError("topic evidence anchor_id values must be unique per domain")

        synthesis_prompt = f"""
You are the evidence-grounded question constructor. Convert the independent
search packets into at most {max_candidates} atomic research-question seeds.
Do not infer a final problem from a catchy sentence. Preserve the source
context, distinguish a source-explicit question from your evidence-derived
question, and state the closest known result plus the precise falsifiable
delta. Each question must cite existing anchor_ids and source_ids. Do not add
constraints merely to make verification easy. The answer type may be anything;
the verification hint must explain what an unambiguous acceptance contract
could inspect. If a broad target has no clear contract, split it into atomic
subquestions. Prefer a diverse set across mechanisms, regimes, observables,
and answer types; never fill a quota with weak evidence.

Domain: {domain_id}
Topic: {domain["query"]}
Evidence packets:
{json.dumps(packets, ensure_ascii=False, indent=2)}
""".strip()
        questions = self._agent(
            stage_key=f"campaign.topic-synthesis.{domain_id}",
            role="strategy-synthesis",
            prompt=synthesis_prompt,
            schema_name="question-candidates.schema.json",
            output_path=domain_dir / "question-candidates.json",
            events_path=domain_dir / "events" / "question-candidates.jsonl",
            inputs={"domain": domain, "packets": packets, "limit": max_candidates},
            output_validator=lambda value: self._validate_topic_questions(
                value, domain_id, packets, max_candidates
            ),
        )
        sources_by_id = {
            source["source_id"]: {**source, "brief_id": packet["brief_id"]}
            for packet in packets
            for source in packet["sources"]
        }
        anchors_by_id = {
            anchor["anchor_id"]: {**anchor, "brief_id": packet["brief_id"]}
            for packet in packets
            for anchor in packet["anchors"]
        }
        seeds: list[CandidateSeed] = []
        for question in questions["questions"]:
            identity = {
                "strategy": strategy.strategy_id,
                "domain": domain_id,
                "statement": normalize_text(question["statement"]),
                "sources": sorted(question["source_ids"]),
            }
            source_key = (
                f"{strategy.strategy_id}:sha256:{_json_sha256(identity)}"
            )
            seeds.append(
                CandidateSeed(
                    source_key=source_key,
                    strategy_id=strategy.strategy_id,
                    strategy_version=strategy.version,
                    origin_class="derived_from_evidence",
                    domain_ids=[domain_id],
                    title=question["title"],
                    content=question["statement"],
                    source_records=[
                        sources_by_id[source_id]
                        for source_id in question["source_ids"]
                    ],
                    origin={
                        "anchor_type": question["anchor_type"],
                        "anchors": [
                            anchors_by_id[anchor_id]
                            for anchor_id in question["anchor_ids"]
                        ],
                        "closest_prior": question["closest_prior"],
                        "falsifiable_delta": question["falsifiable_delta"],
                        "answer_type_hint": question["answer_type_hint"],
                        "verification_hint": question["verification_hint"],
                        "derivation_rationale": question["derivation_rationale"],
                    },
                    provenance={
                        "domain_id": domain_id,
                        "brief_ids": sorted(
                            {
                                sources_by_id[source_id]["brief_id"]
                                for source_id in question["source_ids"]
                            }
                        ),
                    },
                )
            )
        return seeds

    @staticmethod
    def _validate_topic_plan(
        output: dict[str, Any], domain_id: str, search_groups: int
    ) -> None:
        if output["domain_id"] != domain_id:
            raise CampaignError("topic plan returned the wrong domain_id")
        briefs = output["briefs"]
        if len(briefs) != search_groups:
            raise CampaignError(
                f"topic plan must return exactly {search_groups} search briefs"
            )
        brief_ids = [brief["brief_id"] for brief in briefs]
        if len(brief_ids) != len(set(brief_ids)):
            raise CampaignError("topic plan brief_id values must be unique")
        axes = [normalize_text(brief["coverage_axis"]) for brief in briefs]
        if len(axes) != len(set(axes)):
            raise CampaignError("topic plan coverage axes must be distinct")

    @staticmethod
    def _validate_evidence_packet(
        output: dict[str, Any],
        domain_id: str,
        brief_id: str,
        allowed_sources: list[str],
    ) -> None:
        if output["domain_id"] != domain_id or output["brief_id"] != brief_id:
            raise CampaignError("evidence packet returned the wrong domain or brief")
        source_ids = [source["source_id"] for source in output["sources"]]
        if len(source_ids) != len(set(source_ids)):
            raise CampaignError("evidence packet source_id values must be unique")
        if any(source["source"] not in allowed_sources for source in output["sources"]):
            raise CampaignError("evidence packet used a disabled source")
        if any(
            source["exact_excerpt"] not in source["surrounding_context"]
            for source in output["sources"]
        ):
            raise CampaignError(
                "evidence exact_excerpt must be present in surrounding_context"
            )
        known_sources = set(source_ids)
        anchor_ids = [anchor["anchor_id"] for anchor in output["anchors"]]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise CampaignError("evidence packet anchor_id values must be unique")
        if any(
            not set(anchor["source_ids"]).issubset(known_sources)
            for anchor in output["anchors"]
        ):
            raise CampaignError("evidence anchor cites an unknown source_id")

    @staticmethod
    def _validate_topic_questions(
        output: dict[str, Any],
        domain_id: str,
        packets: list[dict[str, Any]],
        limit: int,
    ) -> None:
        if output["domain_id"] != domain_id:
            raise CampaignError("topic synthesis returned the wrong domain_id")
        if len(output["questions"]) > limit:
            raise CampaignError("topic synthesis exceeded max_candidates_per_domain")
        source_ids = {
            source["source_id"] for packet in packets for source in packet["sources"]
        }
        anchors_by_id = {
            anchor["anchor_id"]: anchor
            for packet in packets
            for anchor in packet["anchors"]
        }
        anchor_ids = set(anchors_by_id)
        statements: set[str] = set()
        for question in output["questions"]:
            if not set(question["source_ids"]).issubset(source_ids):
                raise CampaignError("topic question cites an unknown source_id")
            if not set(question["anchor_ids"]).issubset(anchor_ids):
                raise CampaignError("topic question cites an unknown anchor_id")
            cited_anchors = [
                anchors_by_id[anchor_id] for anchor_id in question["anchor_ids"]
            ]
            anchor_sources = {
                source_id
                for anchor in cited_anchors
                for source_id in anchor["source_ids"]
            }
            if not set(question["source_ids"]).issubset(anchor_sources):
                raise CampaignError(
                    "topic question source_ids must support its cited anchors"
                )
            if question["anchor_type"] not in {
                anchor["anchor_type"] for anchor in cited_anchors
            }:
                raise CampaignError(
                    "topic question anchor_type must match a cited anchor"
                )
            normalized = normalize_text(question["statement"])
            if normalized in statements:
                raise CampaignError("topic synthesis returned duplicate questions")
            statements.add(normalized)

    def _discover(self) -> dict[str, dict[str, Any]]:
        domains = list(self.config["domains"])
        limit = self.config["limits"]["papers_per_domain"]
        workers = self.workers
        if not 1 <= workers <= 16:
            raise CampaignError("workers must be between 1 and 16")
        if workers == 1 or len(domains) < 2:
            outputs: dict[str, dict[str, Any]] = {}
            for domain in domains:
                domain_id, source_papers = self._discover_domain(domain, limit)
                outputs[domain_id] = source_papers
            return outputs

        results: dict[str, dict[str, Any]] = {}
        errors: list[tuple[str, Exception]] = []
        with ThreadPoolExecutor(
            max_workers=min(workers, len(domains)),
            thread_name_prefix="discovery",
        ) as executor:
            future_to_domain = {
                executor.submit(self._discover_domain, domain, limit): domain
                for domain in domains
            }
            for future in as_completed(future_to_domain):
                domain_id = future_to_domain[future]["id"]
                try:
                    _, source_papers = future.result()
                    results[domain_id] = source_papers
                except Exception as error:
                    errors.append((domain_id, error))
        if errors:
            rendered = "; ".join(
                f"{domain_id}: {type(error).__name__}: {error}"
                for domain_id, error in sorted(errors)
            )
            raise CampaignError(
                f"{len(errors)} parallel discovery worker(s) failed: {rendered}"
            )
        # Merge strictly in configured domain order so completion timing can
        # never change the downstream ingestion order.
        return {domain["id"]: results[domain["id"]] for domain in domains}

    def _discover_domain(
        self, domain: dict[str, Any], limit: int
    ) -> tuple[str, dict[str, Any]]:
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
        papers = _merge_papers(domain["seed_papers"], output["papers"])[:limit]
        source_papers = {
            "schema_version": 1,
            "domain_id": domain_id,
            "papers": papers,
        }
        if output.get("search_summary"):
            source_papers["search_summary"] = output["search_summary"]
        dump_json(domain_dir / "source-papers.json", source_papers)
        return domain_id, source_papers

    def _ingest(self, discovered: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
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
                            "" if attempt_index == 1 else f"-attempt-{attempt_index}"
                        )
                        raw_path = raw_dir / f"paper-{index:03d}{suffix}-graph.json"
                        extract_path = (
                            raw_dir / f"paper-{index:03d}{suffix}-open-questions.json"
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

    def _canonicalize(self, seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output_path = self.run_dir / "canonicalization.json"
        if not seeds:
            dump_json(output_path, {"clusters": []})
            return []
        heuristic = _heuristic_relations(seeds)
        prompt = f"""
Canonicalize strategy-neutral, source-grounded candidate seeds into atomic
semantic problem candidates. Programmatic normalization has supplied only
heuristic pair hints; make the semantic decision yourself. A seed with
origin_class explicit_source_question is a literal LKM open question. A seed
with origin_class derived_from_evidence was constructed from cited gap anchors
and must never be attributed to the source as an explicitly asked question.

Split one source record when it explicitly contains separable open questions
or research targets. Each candidate must express one acceptance target rather
than a conjunctive research program. A source_key may therefore support more
than one atomic candidate, but every input source_key must support at least
one candidate. Merge equivalent formulations, but do not merge merely related
problems.

When a record names a concrete finite target and then appends an open-ended
class such as "and related cases", make the concrete target its own candidate.
Do not leave the open-ended phrase attached to that candidate. Preserve the
broader class as a separate candidate only if the source gives it a coherent
acceptance target; otherwise keep the source wording but do not manufacture a
class-wide claim.

For every source_key in a candidate, copy one exact non-empty excerpt from
that source record into source_support. The excerpt must directly support the
atomic statement. Treat exact_excerpt as a byte-for-byte copy/paste field:
preserve capitalization, LaTeX delimiters, parentheses, and punctuation; do
not repair grammar, paraphrase, or trim words from the copied span. When the
supporting text starts mid-sentence in the source, copy it exactly as it
appears, including a lowercase first letter; never capitalize, normalize
whitespace, or substitute characters (for example keep the original hyphens
and dashes). A programmatic check rejects any excerpt that is not an exact
substring of its candidate seed, so copy character by character rather than
retyping. Do not manufacture a sharper conjecture, benchmark, threshold, or
success criterion that is absent from the source record. Do not audit current
status in this stage. Do not add restrictions merely to make verification
easy. For famous named problems, keep the statement aligned with the cited
literature. Assign a compact scope_signature for later portfolio diversity;
it must describe the object family, mechanism, regime, and likely verification
mode without changing the question.

Candidate seeds:
{json.dumps(seeds, ensure_ascii=False, indent=2)}

Heuristic possible-duplicate pairs:
{json.dumps(heuristic, ensure_ascii=False, indent=2)}
""".strip()
        repairs: list[dict[str, Any]] = []
        output = self._agent(
            stage_key="campaign.canonicalization",
            role="canonicalization",
            prompt=prompt,
            schema_name="canonicalization.schema.json",
            output_path=output_path,
            events_path=self.run_dir / "events" / "canonicalization.jsonl",
            inputs={"candidate_seeds": seeds, "heuristic_relations": heuristic},
            output_validator=lambda value: self._validate_canonicalization(
                value, seeds, repairs
            ),
        )
        if repairs:
            dump_json(
                self.run_dir / "canonicalization-repairs.json",
                {"schema_version": 1, "repairs": repairs},
            )
        return self._materialize_candidates(output, seeds)

    @staticmethod
    def _validate_canonicalization(
        output: dict[str, Any],
        seeds: list[dict[str, Any]],
        repairs: list[dict[str, Any]] | None = None,
    ) -> None:
        expected = {seed["source_key"] for seed in seeds}
        assigned = {
            key for cluster in output["clusters"] for key in cluster["source_keys"]
        }
        if assigned != expected:
            raise CampaignError(
                "canonicalization must cover every source_key and no unknown keys"
            )
        by_key = {seed["source_key"]: seed for seed in seeds}
        for cluster in output["clusters"]:
            source_keys = list(cluster["source_keys"])
            if len(source_keys) != len(set(source_keys)):
                raise CampaignError(
                    "canonicalization candidate source_keys must be unique"
                )
            supports = list(cluster["source_support"])
            support_keys = [support["source_key"] for support in supports]
            if set(support_keys) != set(source_keys) or len(support_keys) != len(
                set(support_keys)
            ):
                raise CampaignError(
                    "canonicalization source_support must contain exactly one "
                    "entry per candidate source_key"
                )
            for support in supports:
                content = str(by_key[support["source_key"]].get("content") or "")
                excerpt = str(support["exact_excerpt"])
                if excerpt in content:
                    continue
                aligned = _align_excerpt(excerpt, content)
                if aligned is not None:
                    span, ratio, unique = aligned
                    if (
                        unique
                        and ratio >= EXCERPT_REPAIR_MIN_RATIO
                        and _excerpt_diff_is_benign(excerpt, span)
                    ):
                        support["exact_excerpt"] = span
                        if repairs is not None and not any(
                            repair["source_key"] == support["source_key"]
                            and repair["original_excerpt"] == excerpt
                            for repair in repairs
                        ):
                            repairs.append(
                                {
                                    "source_key": support["source_key"],
                                    "canonical_title": str(
                                        cluster.get("canonical_title") or ""
                                    ),
                                    "original_excerpt": excerpt,
                                    "repaired_excerpt": span,
                                    "similarity": round(ratio, 6),
                                }
                            )
                        continue
                message = (
                    "canonicalization source_support exact_excerpt is not "
                    "an exact substring of its source record"
                )
                if aligned is not None:
                    span, ratio, unique = aligned
                    message += (
                        f"; closest source span (similarity {ratio:.3f}"
                        + ("" if unique else ", ambiguous alignment")
                        + f"): {span[:160]!r}"
                    )
                raise CampaignError(message)
        _candidate_ids(output["clusters"])

    def _materialize_candidates(
        self,
        output: dict[str, Any],
        seeds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seeds = [self._normalize_seed_record(seed) for seed in seeds]
        self._validate_canonicalization(output, seeds)
        by_key = {seed["source_key"]: seed for seed in seeds}
        candidates: list[dict[str, Any]] = []
        resolved_ids = _candidate_ids(output["clusters"])
        for cluster, candidate_id in zip(output["clusters"], resolved_ids, strict=True):
            candidate = {
                **cluster,
                "candidate_id": candidate_id,
                "source_records": [by_key[key] for key in cluster["source_keys"]],
            }
            candidate["origins"] = [
                {
                    "source_key": seed["source_key"],
                    "strategy_id": seed["strategy_id"],
                    "origin_class": seed["origin_class"],
                    "origin": seed["origin"],
                    "provenance": seed["provenance"],
                }
                for seed in candidate["source_records"]
            ]
            candidate["source_open_questions"] = [
                record
                for seed in candidate["source_records"]
                if seed["origin_class"] == "explicit_source_question"
                for record in seed["source_records"]
            ]
            candidate_dir = self.run_dir / "candidates" / candidate_id
            papers = {
                (
                    str(record.get("paper_id") or ""),
                    str(record.get("paper_doi") or ""),
                    str(record.get("paper_title") or ""),
                )
                for record in candidate["source_open_questions"]
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
            dump_json(
                candidate_dir / "candidate-origins.json",
                {
                    "schema_version": 1,
                    "source_records": candidate["source_records"],
                    "origins": candidate["origins"],
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
        active_candidate_ids = {candidate["candidate_id"] for candidate in candidates}
        self.state["active_candidate_ids"] = sorted(active_candidate_ids)
        for candidate_id, candidate_state in self.state.get("candidates", {}).items():
            candidate_state["canonicalization_active"] = (
                candidate_id in active_candidate_ids
            )
        self.ledger.save()
        return sorted(candidates, key=lambda item: item["candidate_id"])

    @staticmethod
    def _normalize_seed_record(seed: dict[str, Any]) -> dict[str, Any]:
        """Read v10 cached open-question records as v11 explicit seeds."""

        if seed.get("strategy_id"):
            return seed
        domain_ids = list(seed.get("domain_ids") or [])
        if not domain_ids and seed.get("domain_id"):
            domain_ids = [str(seed["domain_id"])]
        source_key = str(seed.get("source_key") or _source_key(seed))
        return {
            "source_key": source_key,
            "strategy_id": EXPLICIT_OPEN_QUESTIONS,
            "strategy_version": 1,
            "origin_class": "explicit_source_question",
            "domain_ids": domain_ids,
            "title": str(seed.get("paper_title") or "Explicit LKM open question"),
            "content": str(seed.get("content") or ""),
            "source_records": [seed],
            "origin": {
                "source_path": "data.papers[].open_questions",
                "source_key": source_key,
                "global_id": str(seed.get("global_id") or ""),
                "local_id": str(seed.get("id") or ""),
                "paper_id": str(seed.get("paper_id") or ""),
                "paper_title": str(seed.get("paper_title") or ""),
                "paper_doi": str(seed.get("paper_doi") or ""),
            },
            "provenance": {"domain_ids": domain_ids},
        }

    def _triage(self, candidate: dict[str, Any]) -> dict[str, Any]:
        candidate_id = candidate["candidate_id"]
        candidate_dir = self.run_dir / "candidates" / candidate_id
        prompt = f"""
You are the Triage Agent. Apply the $rank-open-problems policy to the intrinsic
source-grounded problem before any expensive later-literature audit. We care about
scientific importance and future Solution Review, not how difficult the problem
is to solve. Expected solve time, compute, feedback density, and success
probability must not affect the gate. Give scientific_significance an explicit
0-10 score and justify it in importance_rationale using field-level scientific
consequences rather than fame alone.

Do not propose a method for solving the problem. Describe in expected_result
what a correct final submission would contain, preserving the answer format
requested by an explicit source question or naturally committed to by an
evidence-derived candidate. In
verification_difficulty_rationale, explain why that result genuinely answers
the candidate, what limits remain, and exactly which load-bearing
derivations a Reviewer must inspect.

Use this exact verification-difficulty rubric:
{VERIFICATION_DIFFICULTY_RUBRIC}

Score 0 when every load-bearing claim is discharged by mechanical checks,
replay, or certificates and specification fidelity is trivial, even when a
human Reviewer performs the fixed procedure. Typical score-0 results include
an explicit counterexample, an exact solution checked by substitution and
boundary conditions, a finite construction, a complete closed-form spectrum
checked against its defining equations, a fixed code-to-experiment comparison,
or a required Lean/Coq/Isabelle proof whose statement the contract pins and
whose kernel accepts it. Do not require machine CI for 0. An essential claim
that cannot be decomposed into independently checkable units, such as a
natural-language argument reviewed as a whole, is 10. Give intermediate scores
for the residual: a few independent local reasoning units are 1-3, connected
derivations or substantial specification-fidelity reconstruction are 4-6, and
long, fragile, or novel chains are 7-9.

Score an exact solution as 2 when its practical acceptance path relies
primarily on independent numerical reproduction of the original finite-size
model. The light residual is checking model and convention fidelity,
precision and tolerances, representative size/parameter coverage, and
exceptional cases. Do not count the difficulty of discovering the solution.

Candidates with high or medium importance proceed to the later-literature
Research audit regardless of verification difficulty. Verification difficulty
is a diagnostic 0-10 score, never a publication threshold. CI is a bonus, not
a gate, and never lowers the structural score: its status records how much of
the delegable checking has been automated. Record only its status; detailed CI
contracts are produced later by the Research Agent.

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
            output_validator=lambda value: self._validate_candidate_output(
                candidate, value, candidate_id, "Triage Agent"
            ),
        )
        if output["candidate_id"] != candidate_id:
            raise CampaignError("Triage Agent returned the wrong candidate_id")
        return output

    @staticmethod
    def _validate_candidate_id(
        output: dict[str, Any], expected: str, role: str
    ) -> None:
        if output.get("candidate_id") != expected:
            raise CampaignError(f"{role} returned the wrong candidate_id")

    @classmethod
    def _validate_candidate_output(
        cls,
        candidate: dict[str, Any],
        output: dict[str, Any],
        expected: str,
        role: str,
    ) -> None:
        cls._validate_candidate_id(output, expected, role)

    @staticmethod
    def _passes_audit_gate(triage: dict[str, Any]) -> bool:
        """Select scientifically important candidates for status Research."""

        return triage["importance_level"] in {"high", "medium"}

    def _passes_triage_publication_gate(self, triage: dict[str, Any]) -> bool:
        """Predict publication eligibility before the status audit."""

        return self._passes_audit_gate(triage)

    def _passes_publication_gate(self, assessment: dict[str, Any]) -> bool:
        """Post-audit prerequisites for compiling a publishable problem.

        Mirrors the assessment-backed ready checks of ``validate_problem``
        so a schema-valid but semantically incomplete assessment is
        audited out here instead of failing the whole run at compile time.
        """
        return (
            assessment["resolution_status"] in READY_RESOLUTION_STATUSES
            and assessment["resolution_conclusion"] in {"confirmed_open", "likely_open"}
            and assessment["post_progress_decision"]
            in {"continue", "rewrite-core", "new-derived-problem"}
            and assessment["importance_level"] in {"high", "medium"}
            and bool(str(assessment["surviving_open_core"]).strip())
            and bool(str(assessment["checked_through"]).strip())
            and bool(assessment["evidence"])
            and (
                assessment["resolution_status"] != "partially_resolved"
                or assessment["major_progress_found"]
            )
            and bool(str(assessment["importance_motivation"]).strip())
            and bool(str(assessment["consequences_of_progress"]).strip())
            and bool(str(assessment["current_best_result"]).strip())
        )

    def _portfolio_limit(self, *, shortlist: bool) -> int | None:
        selection = self.config.get("selection")
        if not selection:
            return None
        target = int(selection["target_problem_count"])
        if shortlist:
            return target * int(selection["shortlist_multiplier"])
        return target

    @staticmethod
    def _scientific_significance(record: dict[str, Any]) -> int:
        if "scientific_significance" in record:
            return int(record["scientific_significance"])
        return {"high": 9, "medium": 6, "low": 2, "unassessed": 0}.get(
            str(record.get("importance_level") or "unassessed"), 0
        )

    @staticmethod
    def _select_quality_diverse(
        candidates: list[dict[str, Any]],
        *,
        scores: dict[str, int],
        limit: int | None,
    ) -> list[dict[str, Any]]:
        """Greedy quality-diversity selection with deterministic tie breaks."""

        if limit is None:
            return list(candidates)
        ordered = sorted(candidates, key=lambda item: item["candidate_id"])
        if len(ordered) <= limit:
            return ordered
        dimensions = ("object_family", "mechanism", "regime", "verification_mode")
        covered: dict[str, set[str]] = {dimension: set() for dimension in dimensions}
        selected: list[dict[str, Any]] = []
        remaining = list(ordered)
        while remaining and len(selected) < limit:
            ranked: list[tuple[int, int, str, dict[str, Any]]] = []
            for candidate in remaining:
                signature = candidate["scope_signature"]
                novelty = sum(
                    normalize_text(str(signature[dimension]))
                    not in covered[dimension]
                    for dimension in dimensions
                )
                ranked.append(
                    (
                        -novelty,
                        -int(scores[candidate["candidate_id"]]),
                        candidate["candidate_id"],
                        candidate,
                    )
                )
            _, _, _, chosen = min(ranked)
            selected.append(chosen)
            remaining.remove(chosen)
            for dimension in dimensions:
                covered[dimension].add(
                    normalize_text(str(chosen["scope_signature"][dimension]))
                )
        return selected

    @staticmethod
    def _deduplicate_review_feedback(
        items: Any, *, field: str = "feedback"
    ) -> list[str]:
        if not isinstance(items, list):
            raise CampaignError(f"{field} must be a list of strings")
        deduplicated: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, str):
                raise CampaignError(f"{field} must be a list of strings")
            rendered = item.strip()
            if rendered and rendered not in seen:
                seen.add(rendered)
                deduplicated.append(rendered)
        return deduplicated

    def _load_problem_review_feedback(
        self, candidate_id: str, candidate_dir: Path
    ) -> dict[str, Any]:
        history_path = candidate_dir / "problem-review-feedback-history.json"
        history: dict[str, Any]
        if history_path.is_file():
            history = _load_json(history_path)
            if history.get("schema_version") != 1:
                raise CampaignError(
                    "Problem Reviewer feedback history has an unsupported "
                    "schema_version"
                )
            if history.get("candidate_id") != candidate_id:
                raise CampaignError(
                    "Problem Reviewer feedback history has the wrong candidate_id"
                )
            revisions = history.get("revisions")
            if not isinstance(revisions, list):
                raise CampaignError(
                    "Problem Reviewer feedback history revisions must be a list"
                )
        else:
            revisions = []

        normalized_revisions: list[dict[str, Any]] = []
        feedback_ids: set[str] = set()
        concerns: list[str] = []
        accumulated_revision_instructions: list[str] = []
        for revision in revisions:
            if not isinstance(revision, dict):
                raise CampaignError(
                    "Problem Reviewer feedback history contains an invalid revision"
                )
            attempt_value = revision.get("problem_review_attempt", 0)
            if isinstance(attempt_value, bool) or not isinstance(attempt_value, int):
                raise CampaignError(
                    "Problem Reviewer feedback attempt must be an integer"
                )
            attempt = attempt_value
            feedback_id_value = revision.get("feedback_id")
            if not isinstance(feedback_id_value, str):
                raise CampaignError(
                    "Problem Reviewer feedback requires a string feedback_id"
                )
            feedback_id = feedback_id_value.strip()
            if not feedback_id:
                raise CampaignError(
                    "seeded Problem Reviewer feedback requires a stable feedback_id"
                )
            if feedback_id in feedback_ids:
                raise CampaignError(
                    f"duplicate Problem Reviewer feedback_id: {feedback_id}"
                )
            feedback_ids.add(feedback_id)
            source_value = revision.get("source")
            if not isinstance(source_value, str):
                raise CampaignError(
                    "Problem Reviewer feedback requires a string source"
                )
            source = source_value.strip()
            if source not in {"manual-seed", "problem-review"}:
                raise CampaignError(
                    "Problem Reviewer feedback source must be manual-seed "
                    "or problem-review"
                )
            verdict_sha_value = revision.get("verdict_sha256", "")
            if not isinstance(verdict_sha_value, str):
                raise CampaignError(
                    "Problem Reviewer feedback verdict_sha256 must be a string"
                )
            verdict_sha = verdict_sha_value.strip()
            if verdict_sha and not re.fullmatch(r"[0-9a-f]{64}", verdict_sha):
                raise CampaignError(
                    "Problem Reviewer feedback verdict_sha256 must be "
                    "a lowercase SHA-256"
                )
            if source == "manual-seed":
                if attempt != 0:
                    raise CampaignError(
                        "manual-seed feedback must use problem_review_attempt 0"
                    )
                if feedback_id.startswith("auto-problem-review-"):
                    raise CampaignError(
                        "manual-seed feedback_id uses a reserved prefix"
                    )
            else:
                if attempt < 1 or not verdict_sha:
                    raise CampaignError(
                        "problem-review feedback requires a positive attempt "
                        "and verdict_sha256"
                    )
                expected_feedback_id = (
                    f"auto-problem-review-{attempt}-{verdict_sha[:16]}"
                )
                if feedback_id != expected_feedback_id:
                    raise CampaignError(
                        "problem-review feedback_id does not match its "
                        "attempt and verdict_sha256"
                    )
            revision_concerns = self._deduplicate_review_feedback(
                revision.get("concerns"),
                field="Problem Reviewer feedback concerns",
            )
            current_revision_instructions = self._deduplicate_review_feedback(
                revision.get("revision_instructions"),
                field="Problem Reviewer feedback revision_instructions",
            )
            recorded_at_value = revision.get("recorded_at", "")
            rationale_value = revision.get("rationale", "")
            if not isinstance(recorded_at_value, str) or not isinstance(
                rationale_value, str
            ):
                raise CampaignError(
                    "Problem Reviewer feedback timestamps and rationale must be strings"
                )
            normalized_revisions.append(
                {
                    "feedback_id": feedback_id,
                    "source": source,
                    "problem_review_attempt": attempt,
                    "verdict_sha256": verdict_sha,
                    "recorded_at": recorded_at_value.strip(),
                    "concerns": revision_concerns,
                    "revision_instructions": current_revision_instructions,
                    "rationale": rationale_value.strip(),
                }
            )
            concerns.extend(revision_concerns)
            accumulated_revision_instructions.extend(current_revision_instructions)
        return {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "revisions": normalized_revisions,
            "accumulated_concerns": self._deduplicate_review_feedback(concerns),
            "accumulated_revision_instructions": (
                self._deduplicate_review_feedback(accumulated_revision_instructions)
            ),
        }

    def _record_problem_review_feedback(
        self,
        candidate_id: str,
        candidate_dir: Path,
        verdict: dict[str, Any],
    ) -> dict[str, Any]:
        history = self._load_problem_review_feedback(candidate_id, candidate_dir)
        if verdict.get("verdict") != "revise":
            return history

        stage_key = f"candidate.{candidate_id}.problem-review"
        stage = self.ledger.stage_record(stage_key)
        verdict_path = candidate_dir / "problem-review-verdict.json"
        if (
            stage.get("status") != "completed"
            or stage.get("output") != _relative(verdict_path, self.run_dir)
            or not verdict_path.is_file()
            or stage.get("output_sha256") != file_sha256(verdict_path)
        ):
            return history
        disk_verdict = _load_json(verdict_path)
        # Verdicts cached before the `checks` object was retired still carry
        # it; the field is ignored, so strip it before schema validation
        # instead of failing the legacy artifact.
        schema_view = {
            key: value for key, value in disk_verdict.items() if key != "checks"
        }
        if (
            disk_verdict.get("candidate_id") != candidate_id
            or _json_sha256(disk_verdict) != _json_sha256(verdict)
            or _schema_errors(
                schema_view,
                self.schemas / "stages" / "problem-review.schema.json",
            )
        ):
            return history

        attempt = int(stage.get("attempt") or 0)
        if attempt < 1:
            return history
        verdict_sha = _json_sha256(verdict)
        revisions = history["revisions"]
        for revision in revisions:
            if (
                revision["source"] == "problem-review"
                and revision["verdict_sha256"] == verdict_sha
            ):
                return history
            if (
                revision["source"] == "problem-review"
                and revision["problem_review_attempt"] == attempt
            ):
                raise CampaignError(
                    "Problem Reviewer feedback history conflicts with "
                    f"completed attempt {attempt}"
                )

        feedback_id = f"auto-problem-review-{attempt}-{verdict_sha[:16]}"
        if any(revision["feedback_id"] == feedback_id for revision in revisions):
            raise CampaignError(
                f"duplicate Problem Reviewer feedback_id: {feedback_id}"
            )
        revisions.append(
            {
                "feedback_id": feedback_id,
                "source": "problem-review",
                "problem_review_attempt": attempt,
                "verdict_sha256": verdict_sha,
                "recorded_at": utc_now(),
                "concerns": self._deduplicate_review_feedback(
                    verdict.get("concerns"),
                    field="Problem Reviewer concerns",
                ),
                "revision_instructions": (
                    self._deduplicate_review_feedback(
                        verdict.get("revision_instructions"),
                        field="Problem Reviewer revision_instructions",
                    )
                ),
                "rationale": str(verdict.get("rationale") or "").strip(),
            }
        )
        history["revisions"] = revisions
        history["accumulated_concerns"] = self._deduplicate_review_feedback(
            [item for revision in revisions for item in revision["concerns"]]
        )
        history["accumulated_revision_instructions"] = (
            self._deduplicate_review_feedback(
                [
                    item
                    for revision in revisions
                    for item in revision["revision_instructions"]
                ]
            )
        )
        dump_json_atomic(
            candidate_dir / "problem-review-feedback-history.json",
            history,
        )
        return history

    def _recover_problem_review_feedback(
        self, candidate_id: str, candidate_dir: Path
    ) -> dict[str, Any]:
        history = self._load_problem_review_feedback(candidate_id, candidate_dir)
        verdict_path = candidate_dir / "problem-review-verdict.json"
        stage = self.ledger.stage_record(f"candidate.{candidate_id}.problem-review")
        if (
            stage.get("status") != "completed"
            or not verdict_path.is_file()
            or stage.get("output_sha256") != file_sha256(verdict_path)
        ):
            return history
        return self._record_problem_review_feedback(
            candidate_id, candidate_dir, _load_json(verdict_path)
        )

    @staticmethod
    def _research_feedback_from_history(
        candidate_id: str, history: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "feedback_sources": [
                {
                    "feedback_id": revision["feedback_id"],
                    "source": revision["source"],
                    "problem_review_attempt": revision["problem_review_attempt"],
                    "verdict_sha256": revision["verdict_sha256"],
                }
                for revision in history["revisions"]
            ],
            "concerns": history["accumulated_concerns"],
            "revision_instructions": history["accumulated_revision_instructions"],
        }

    def _research_feedback_snapshot(
        self,
        candidate_id: str,
        candidate_dir: Path,
        history: dict[str, Any],
        *,
        apply_pending: bool,
    ) -> dict[str, Any]:
        snapshot_path = candidate_dir / "research-feedback-applied.json"
        research_stage = self.ledger.stage_record(f"candidate.{candidate_id}.research")
        snapshot_exists = snapshot_path.is_file()
        recorded_snapshot_sha = str(
            self.state.get("candidates", {})
            .get(candidate_id, {})
            .get("research_feedback_sha256")
            or ""
        )
        if apply_pending or not snapshot_exists:
            try:
                stage_version = int(research_stage.get("pipeline_version") or 0)
            except (TypeError, ValueError):
                stage_version = 0
            migrating_legacy_research = (
                not snapshot_exists
                and research_stage.get("status") == "completed"
                and stage_version < PIPELINE_VERSION
                and not recorded_snapshot_sha
            )
            if (
                not apply_pending
                and not snapshot_exists
                and not migrating_legacy_research
                and (
                    recorded_snapshot_sha or research_stage.get("status") == "completed"
                )
            ):
                raise CampaignError(
                    "Research is missing its recorded applied-feedback "
                    "snapshot; restore it or explicitly retry Research"
                )
            if apply_pending or migrating_legacy_research:
                source_history = history
            else:
                source_history = {
                    "revisions": [],
                    "accumulated_concerns": [],
                    "accumulated_revision_instructions": [],
                }
            snapshot = self._research_feedback_from_history(
                candidate_id, source_history
            )
            dump_json_atomic(snapshot_path, snapshot)
            self.ledger.update_candidate(
                candidate_id,
                {"research_feedback_sha256": _json_sha256(snapshot)},
            )
            return snapshot

        snapshot = _load_json(snapshot_path)
        expected_snapshot_sha = recorded_snapshot_sha
        actual_snapshot_sha = _json_sha256(snapshot)
        if expected_snapshot_sha and expected_snapshot_sha != actual_snapshot_sha:
            raise CampaignError(
                "Research feedback snapshot does not match recorded state"
            )
        if not expected_snapshot_sha and research_stage.get("status") == "completed":
            raise CampaignError(
                "completed Research has no applied-feedback snapshot hash; "
                "restore state or explicitly retry Research"
            )
        if (
            snapshot.get("schema_version") != 1
            or snapshot.get("candidate_id") != candidate_id
            or not isinstance(snapshot.get("feedback_sources"), list)
        ):
            raise CampaignError(
                "Research feedback snapshot is invalid for this candidate"
            )
        for source in snapshot["feedback_sources"]:
            if not isinstance(source, dict) or not all(
                isinstance(source.get(field), expected)
                for field, expected in (
                    ("feedback_id", str),
                    ("source", str),
                    ("problem_review_attempt", int),
                    ("verdict_sha256", str),
                )
            ):
                raise CampaignError(
                    "Research feedback snapshot contains an invalid source"
                )
            if isinstance(source["problem_review_attempt"], bool):
                raise CampaignError(
                    "Research feedback snapshot contains an invalid attempt"
                )
            if source["source"] not in {"manual-seed", "problem-review"}:
                raise CampaignError(
                    "Research feedback snapshot contains an invalid source"
                )
            verdict_sha = source["verdict_sha256"]
            if verdict_sha and not re.fullmatch(r"[0-9a-f]{64}", verdict_sha):
                raise CampaignError(
                    "Research feedback snapshot contains an invalid SHA-256"
                )
        snapshot["concerns"] = self._deduplicate_review_feedback(
            snapshot.get("concerns"),
            field="Research feedback snapshot concerns",
        )
        snapshot["revision_instructions"] = self._deduplicate_review_feedback(
            snapshot.get("revision_instructions"),
            field="Research feedback snapshot revision_instructions",
        )
        revisions_by_id = {
            revision["feedback_id"]: revision for revision in history["revisions"]
        }
        applied_revisions: list[dict[str, Any]] = []
        for source in snapshot["feedback_sources"]:
            revision = revisions_by_id.get(source["feedback_id"])
            if revision is None or any(
                source[field] != revision[field]
                for field in (
                    "source",
                    "problem_review_attempt",
                    "verdict_sha256",
                )
            ):
                raise CampaignError(
                    "Research feedback snapshot is inconsistent with history"
                )
            applied_revisions.append(revision)
        expected_snapshot = self._research_feedback_from_history(
            candidate_id,
            {
                "revisions": applied_revisions,
                "accumulated_concerns": (
                    self._deduplicate_review_feedback(
                        [
                            item
                            for revision in applied_revisions
                            for item in revision["concerns"]
                        ]
                    )
                ),
                "accumulated_revision_instructions": (
                    self._deduplicate_review_feedback(
                        [
                            item
                            for revision in applied_revisions
                            for item in revision["revision_instructions"]
                        ]
                    )
                ),
            },
        )
        if snapshot != expected_snapshot:
            raise CampaignError(
                "Research feedback snapshot contents are inconsistent with history"
            )
        if not expected_snapshot_sha:
            self.ledger.update_candidate(
                candidate_id,
                {"research_feedback_sha256": actual_snapshot_sha},
            )
        return snapshot

    def _research_and_problem_review(
        self,
        candidate: dict[str, Any],
        triage: dict[str, Any],
        *,
        apply_pending_review_feedback: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        candidate_id = candidate["candidate_id"]
        candidate_dir = self.run_dir / "candidates" / candidate_id
        review_feedback = self._recover_problem_review_feedback(
            candidate_id, candidate_dir
        )
        research_feedback = self._research_feedback_snapshot(
            candidate_id,
            candidate_dir,
            review_feedback,
            apply_pending=apply_pending_review_feedback,
        )
        revision_context = ""
        if research_feedback["feedback_sources"]:
            revision_context = f"""

This is a Research retry after an independent Problem Reviewer requested
revision. Address every accumulated concern and revision instruction below
explicitly, including requirements from earlier revise rounds.
Preserve supported judgments, but correct the assessment wherever required.
Do not merely repeat the previous assessment.

Accumulated Problem Reviewer feedback:
{json.dumps(research_feedback, ensure_ascii=False, indent=2)}
""".rstrip()
        prompt = f"""
You are the Research Agent. Use ${SKILL_NAME} to reconstruct what later
literature says about this exact candidate and its declared origin class.
Choose LKM and web routes
adaptively. After retrieval, directly produce the status, major-progress
assessment, precise surviving core, verification difficulty, and CI contracts in the
required schema. Do not send control back to the Discovery Agent and do not
write to a problem pool or workspace files.
This is a literature-status audit, not a solver run. Do not attempt a novel
proof, counterexample, construction, computation, or experimental explanation
of the candidate. A resolved or refuted status must be supported by external
research evidence, not by reasoning or a witness created during this audit.
If you notice what appears to be an elementary new resolution, keep the
literature status separate and report the identity or scope concern without
counting your observation as closure.

An absence of a found solution is not enough for still_open. Inspect how later
work treats the same core. A literal recent sentence saying "remains open" is
not required. When a systematic same-core search, forward citation chain, and
review of plausible adjacent results leave a precise nonempty core with no
credible closure, use resolution_status still_open together with
resolution_conclusion likely_open and appropriately limited confidence. Use
uncertain when coverage is materially incomplete, conflicting, or
identity-ambiguous, not merely because no later paper repeats the open label.
If major progress narrows or reframes it, reassess
the surviving core's scientific_significance, importance, expected result,
and verification difficulty
from scratch. Score scientific_significance from 0 to 10 and explain why the
problem matters in importance_motivation and consequences_of_progress. Do not
propose a solving method. Describe what a correct final
submission would contain, why it genuinely answers the surviving core, and
any limits on that claim inside verification_difficulty_rationale. Preserve
the answer format committed to by an explicit source question. For an
evidence-derived seed, audit the derivation from its anchors without pretending
that a source explicitly posed the resulting question.
Preserve the Triage expected-result and verification score unless later
evidence changes the surviving core or shows that contract was not
scientifically sufficient.
Write every public-facing repository field in English. Use GitLab-compatible
math delimiters: `$...$` inline and `$$...$$` for display math; do not use
`\\(...\\)` or `\\[...\\]`.
Write `abstract` as a short overview. Record concrete prior results in
`previous_progress`. Record affected fields in
`scientific_significance_areas`; each item must use high, medium, or low and
state what changes in that field rather than assigning a single public score.
List possible solving obstacles in `solution_difficulty` without scoring them.
Build `verification_contracts` as one entry per accepted answer type. Each
entry must state a complete acceptance contract and a truthful textual
`ci_contract`; use an empty string when no mechanical CI is reasonable. The
single `verification_difficulty` is an overall score across all answer types
after mechanically checkable parts have been removed.
Write the material for `The Research Problem` as a concise academic introduction
followed by a problem statement, not as a schema checklist. Give a researcher
outside the narrow specialty enough background to understand how the question
arose. Explain specialist terminology and acronyms, summarize the relevant
prior result or limitation, and then state the unresolved target accurately.
Supply whatever discipline-specific detail identifies the problem and a
meaningful answer: for example equations and definitions in mathematics,
physical systems and observables in physics, organisms/assays/readouts in
biology, materials and operating conditions in engineering, or datasets,
baselines, metrics, and evaluation protocols in computational work. Do not
force mathematical symbols, parameter domains, or quantifiers when they are
not natural to the field. A bare equation number, acronym, or specialist
shorthand is not an adequate explanation.
Do not invent a benchmark or threshold merely to make a broad question appear
easy to verify, and do not move verification burden into an unverified
specification gap. Describe the final answer directly in expected_result.
Apply the same rubric used at triage:
{VERIFICATION_DIFFICULTY_RUBRIC}
Score 0 when every load-bearing claim is discharged by mechanical checks,
replay, or certificates with trivial specification fidelity, regardless of whether that check is automated or human. Explicit
counterexamples, exact solutions, finite constructions, frozen
code-to-experiment comparisons, and required proof-assistant artifacts with
contract-pinned statements may all
be 0. Use 1-9 for the increasing residual: a few independent local reasoning
units at 1-3, connected derivations or substantial specification-fidelity
reconstruction at 4-6, and long, fragile, or novel chains at 7-9. Score 10
for an essential claim that cannot be decomposed into independently checkable
units.
When an exact solution is checked primarily through independent numerical
reproduction of the original finite-size model, score it 2 for the local
residual in model fidelity, tolerances, coverage, and exceptional cases; do
not count discovery difficulty.
Do not hide derivation work behind an oracle-like CI step. Every claimed CI
operation must be direct recomputation, a named known terminating procedure
with concrete inputs, or replay of a submitted artifact. A command like
"decide the universal property exactly" is not an operational procedure.
Evidence content levels must state what was actually inspected. Retrieval
score is not confidence. Keep uncertainty visible when the later-literature
chain is too thin to support a systematic judgment.

Candidate:
{json.dumps(candidate, ensure_ascii=False, indent=2)}

Intrinsic triage:
{json.dumps(triage, ensure_ascii=False, indent=2)}
{revision_context}
""".strip()
        assessment = self._agent(
            stage_key=f"candidate.{candidate_id}.research",
            role="research",
            prompt=prompt,
            schema_name="assessment.schema.json",
            output_path=candidate_dir / "assessment.json",
            events_path=candidate_dir / "events" / "research.jsonl",
            inputs={
                "candidate": candidate,
                "triage": triage,
                "problem_review_feedback": research_feedback,
            },
            output_validator=lambda value: self._validate_candidate_output(
                candidate, value, candidate_id, "Research Agent"
            ),
        )
        if assessment["candidate_id"] != candidate_id:
            raise CampaignError("Research Agent returned the wrong candidate_id")
        problem_review_prompt = f"""
You are an independent Problem Reviewer Agent. Audit the Research Agent's structured
assessment against the candidate origins and source records, intrinsic triage, and its
cited evidence. Check the status conclusion, major-progress classification,
surviving core, scientific importance, content-level honesty, verification
difficulty, target fidelity and limitations, and problem-specific CI
pseudocode. Use this exact rubric:
{VERIFICATION_DIFFICULTY_RUBRIC}
Also check the public-contract fields: `abstract`, `previous_progress`,
`scientific_significance_areas`, `solution_difficulty`, and
`verification_contracts`. Scientific significance must identify affected
fields and concrete effects, not merely repeat a numeric score. Every accepted
answer type must have an unambiguous contract. Judge the one
`verification_difficulty` score across all of those contracts after removing
their mechanically checkable parts.
This is also not a solver run. Reject or request revision when a resolved,
refuted, or major-progress judgment depends on a proof, counterexample,
construction, computation, or explanation newly created by the Research Agent
rather than external research evidence. Do not validate that proposed new
solution as part of problem discovery.
Reject an artificially low score that depends on an invented proxy benchmark
rather than the stated route, or that moves burden into an unverified
specification gap. Verification difficulty and CI are separate layers: the
score is the structural residual, while CI records how much of the delegable
checking has been automated and cannot lower the score. Score 0 means every load-bearing claim is discharged by mechanical checks, replay, or
certificates with trivial specification fidelity, not that verification must
be automated. Finite witnesses, exact solutions,
finite constructions, algorithms tested against a fixed target, frozen
first-principles models, and required proof-assistant artifacts with
contract-pinned statements may all score
0. An exact solution checked primarily through independent numerical
reproduction of the original finite-size model instead scores 2 for the local
residual in model fidelity, tolerances, coverage, and exceptional cases; this
does not count discovery difficulty. Do
not solve the problem and do not mutate any pool or repository.

For current status, do not demand a literal recent "remains open" sentence. A
systematic same-core search, forward citation reconstruction, and explicit
separation of plausible adjacent results may support still_open paired with
likely_open and limited confidence. Reject only absence-based claims that lack
that reconstruction, or evidence that is materially incomplete, conflicting,
or identity-ambiguous.

If later evidence does not change the surviving core, require an explicit
scientific reason before the assessment changes the Triage expected-result or
verification difficulty. Reject an unexplained score decrease.
Reject oracle-like CI contracts. A score-0 result may be reviewed manually,
but claimed machine CI must still name a real procedure. Pseudocode
must identify a known terminating procedure and its concrete input/output;
"decide", "prove", or "verify" followed by the target global claim is not an
algorithm.
Reject any public-facing repository field that is not written in English or
uses non-GitLab math delimiters such as `\\(...\\)` or `\\[...\\]`.
Reject a repository description whose `The Research Problem` is only a bare task,
conjecture, acronym, or external equation reference. It must read like a
concise academic introduction and problem statement: explain the scientific
context, how the question follows from prior work, specialist terminology,
and the discipline-appropriate details needed to understand what is unresolved
and what would answer it. Do not demand mathematics-specific notation,
normalizations, parameter domains, or quantifiers from experimental,
computational, engineering, or descriptive problems unless they are genuinely
needed.

Return accept only if every load-bearing judgment is supported and the
verification score and boundary are supported. Return revise with concrete instructions
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
            stage_key=f"candidate.{candidate_id}.problem-review",
            role="problem-reviewer",
            prompt=problem_review_prompt,
            schema_name="problem-review.schema.json",
            output_path=candidate_dir / "problem-review-verdict.json",
            events_path=candidate_dir / "events" / "problem-review.jsonl",
            inputs={
                "candidate": candidate,
                "triage": triage,
                "assessment": assessment,
            },
            output_validator=lambda value: self._validate_candidate_id(
                value, candidate_id, "Problem Reviewer Agent"
            ),
        )
        if verdict["candidate_id"] != candidate_id:
            raise CampaignError(
                "Problem Reviewer Agent returned the wrong candidate_id"
            )
        self._record_problem_review_feedback(candidate_id, candidate_dir, verdict)
        for source in ("lkm", "web"):
            items = [
                item for item in assessment["evidence"] if item["source"] == source
            ]
            dump_json(
                candidate_dir / "evidence" / source / "research-evidence.json",
                {
                    "schema_version": 1,
                    "candidate_id": candidate_id,
                    "evidence": items,
                },
            )
        return verdict, assessment

    def _next_problem_id(self) -> str:
        numbers = []
        for path in self.problem_root.glob("ORP-*"):
            match = re.match(r"ORP-(\d+)(?:-|$)", path.name)
            if match:
                numbers.append(int(match.group(1)))
        if self.pool_root:
            for path in pool_snapshot_paths(self.pool_root / "pool" / "problems"):
                identifier = str(load_yaml(path).get("id") or "")
                match = re.fullmatch(r"ORP-(\d+)", identifier)
                if match:
                    numbers.append(int(match.group(1)))
        return f"ORP-{(max(numbers, default=0) + 1):04d}"

    def _reserve_problem_repo(self, candidate_id: str, slug: str) -> tuple[str, Path]:
        """Allocate a problem ID and reserve its repository directory.

        An exclusive flock on ``problem_root/.id-allocation.lock`` covers
        the used-ID scan, the reserving ``mkdir``, and a single state save
        recording ``problem_id`` and ``problem_repo`` together, so
        concurrent campaigns sharing ``problem_root`` never receive the
        same problem ID and a crash can leave at most an unrecorded empty
        reservation (which the ID scan still treats as used) rather than a
        half-recorded state. The reserved directory stays empty until the
        compiler populates it.
        """
        self.problem_root.mkdir(parents=True, exist_ok=True)
        lock_path = self.problem_root / ".id-allocation.lock"
        with lock_path.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                problem_id = self._next_problem_id()
                repo_dir = self.problem_root / f"{problem_id}-{slug}"
                repo_dir.mkdir()
                candidate_state = self.state["candidates"][candidate_id]
                candidate_state["problem_id"] = problem_id
                candidate_state["problem_repo"] = str(repo_dir)
                self.ledger.save()
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return problem_id, repo_dir

    def _compile(
        self,
        candidate: dict[str, Any],
        triage: dict[str, Any],
        assessment: dict[str, Any],
        verdict: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_id = candidate["candidate_id"]
        candidate_dir = self.run_dir / "candidates" / candidate_id
        candidate_state = self.state["candidates"][candidate_id]
        slug = slugify(assessment["canonical_title"])[:72].strip("-")
        recorded_repo = str(candidate_state.get("problem_repo") or "")
        if recorded_repo:
            problem_id = str(candidate_state["problem_id"])
            repo_dir = Path(recorded_repo)
        elif candidate_state.get("problem_id"):
            # Legacy state recorded the ID before repository paths were
            # persisted together with it at allocation time.
            problem_id = str(candidate_state["problem_id"])
            repo_dir = self.problem_root / f"{problem_id}-{slug}"
            if not repo_dir.is_dir() or not any(repo_dir.iterdir()):
                # A crash between the two legacy saves left the ID in state
                # with at most an empty reservation on disk. Adopt the
                # derived directory and record it instead of failing.
                candidate_state["problem_repo"] = str(repo_dir)
                self.ledger.save()
                recorded_repo = str(repo_dir)
        else:
            problem_id, repo_dir = self._reserve_problem_repo(candidate_id, slug)
            recorded_repo = str(repo_dir)
        output_path = candidate_dir / "compile.json"
        structured_path = candidate_dir / "problem.yaml"
        compile_key = f"candidate.{candidate_id}.compile"
        if output_path.is_file() and not repo_dir.is_dir():
            self.ledger.invalidate(lambda key: key == compile_key)
        elif repo_dir.is_dir():
            if not output_path.is_file():
                if recorded_repo != str(repo_dir):
                    raise CampaignError(
                        f"refusing to overwrite untracked problem repository: {repo_dir}"
                    )
                if any(repo_dir.iterdir()):
                    # Partial repository left by an attempt that crashed
                    # before compile.json was written; safe to rebuild.
                    shutil.rmtree(repo_dir)
            else:
                previous_compile = _load_json(output_path)
                readme_path = repo_dir / "README.md"
                contract_path = repo_dir / "problem.json"
                expected_hash = str(previous_compile.get("readme_sha256") or "")
                expected_contract_hash = str(
                    previous_compile.get("contract_sha256") or ""
                )
                legacy_contract_migration = (
                    not expected_contract_hash and not contract_path.exists()
                )
                if (
                    not readme_path.is_file()
                    or not expected_hash
                    or file_sha256(readme_path) != expected_hash
                    or (
                        not legacy_contract_migration
                        and (
                            not contract_path.is_file()
                            or not expected_contract_hash
                            or file_sha256(contract_path)
                            != expected_contract_hash
                        )
                    )
                ):
                    raise CampaignError(
                        f"refusing to overwrite modified problem repository: {repo_dir}"
                    )

        def produce() -> Produced:
            if repo_dir.is_dir() and not any(repo_dir.iterdir()):
                # Empty directory reserved during problem-ID allocation.
                repo_dir.rmdir()
            created_repo = not repo_dir.exists()
            try:
                problem = self._problem_manifest(
                    problem_id, candidate, triage, assessment
                )
                dump_yaml(structured_path, problem)
                contract = problem_contract_from_assessment(
                    problem_id=problem_id,
                    candidate=candidate,
                    assessment=assessment,
                    schema_path=self.schemas / "problem-contract.schema.json",
                )
                self.problem_root.mkdir(parents=True, exist_ok=True)
                repository_writer = (
                    materialize_problem_contract_repository
                    if created_repo
                    else write_problem_contract_repository
                )
                repository_writer(
                    contract=contract,
                    schema_path=self.schemas / "problem-contract.schema.json",
                    out_dir=repo_dir,
                )
                contract_path = repo_dir / "problem.json"
                errors = validate_problem(
                    structured_path, self.schemas / "problem.schema.json"
                )
                errors.extend(
                    validate_problem_contract(
                        contract, self.schemas / "problem-contract.schema.json"
                    )
                )
                errors.extend(validate_problem_contract_readme(repo_dir / "README.md"))
                if errors:
                    raise CampaignError(
                        f"compiled problem {problem_id} is invalid: {'; '.join(errors)}"
                    )
                if not (repo_dir / ".git").is_dir():
                    subprocess.run(
                        ["git", "init", "-b", "main"],
                        cwd=repo_dir,
                        text=True,
                        capture_output=True,
                        check=True,
                    )
                subprocess.run(
                    ["git", "add", "README.md", "problem.json"],
                    cwd=repo_dir,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                staged = subprocess.run(
                    ["git", "diff", "--cached", "--quiet"],
                    cwd=repo_dir,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if staged.returncode == 1:
                    subprocess.run(
                        [
                            "git",
                            "-c",
                            "user.name=Open Research Discovery",
                            "-c",
                            "user.email=discovery@localhost",
                            "commit",
                            "-m",
                            f"Initialize {problem_id}",
                        ],
                        cwd=repo_dir,
                        text=True,
                        capture_output=True,
                        check=True,
                    )
                elif staged.returncode != 0:
                    raise CampaignError(
                        f"git staging check failed for {problem_id}: "
                        f"{staged.stderr or staged.stdout}"
                    )
                git_head = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo_dir,
                    text=True,
                    capture_output=True,
                    check=True,
                ).stdout.strip()
                return Produced(
                    {
                        "schema_version": 1,
                        "candidate_id": candidate_id,
                        "problem_id": problem_id,
                        "problem_repo": str(repo_dir),
                        "readme_sha256": file_sha256(repo_dir / "README.md"),
                        "contract_sha256": file_sha256(contract_path),
                        "internal_record_sha256": file_sha256(structured_path),
                        "git_head": git_head,
                    },
                    {"exit_code": 0, "compiler": f"pipeline-v{PIPELINE_VERSION}"},
                )
            except Exception:
                if created_repo and repo_dir.is_dir():
                    # Drop the partial build but keep the reserved directory so
                    # concurrent campaigns cannot reuse the problem ID.
                    shutil.rmtree(repo_dir)
                    repo_dir.mkdir()
                raise

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
        open_current = assessment["resolution_status"] in {
            "still_open",
            "partially_resolved",
        } and assessment["resolution_conclusion"] in {"confirmed_open", "likely_open"}
        dispatch_ready = (
            open_current
            and assessment["importance_level"] in {"high", "medium"}
            and bool(assessment["surviving_open_core"])
            and bool(assessment["acceptance_boundary"])
        )
        if assessment["resolution_status"] == "resolved":
            status = "resolved-externally"
        elif assessment["resolution_status"] == "refuted":
            status = "refuted-externally"
        elif assessment["resolution_status"] == "uncertain":
            status = "uncertain"
        elif dispatch_ready:
            status = "ready"
        else:
            status = "resolution-audited"
        route = (
            "closed"
            if status in {"resolved-externally", "refuted-externally"}
            else "status-audit"
            if status == "uncertain"
            else "candidate-result"
            if dispatch_ready
            else "manual-review"
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
                    "paper_title": str(source.get("paper_title") or ""),
                    "paper_doi": str(source.get("paper_doi") or ""),
                    "source_path": "data.papers[].open_questions",
                }
            )
        manifest_seeds = candidate.get("source_records") or [
            self._normalize_seed_record(source)
            for source in candidate["source_open_questions"]
        ]
        origins = [
            {
                "source_key": seed["source_key"],
                "strategy_id": seed["strategy_id"],
                "origin_class": seed["origin_class"],
                "source_records": seed["source_records"],
                "origin": seed["origin"],
            }
            for seed in manifest_seeds
        ]
        # A surviving-core reassessment only happens when the audit found
        # major later progress; recording True unconditionally would
        # contradict major_progress_found=false.
        reassessed = bool(assessment["major_progress_found"])
        resolution_audit = {
            "checked_at": assessment["checked_through"],
            "checked_through": assessment["checked_through"],
            "status": assessment["resolution_status"],
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
                "surviving_core_reassessed": reassessed,
                "importance_reassessed": reassessed,
                "solution_review_reassessed": reassessed,
                "decision": assessment["post_progress_decision"],
                "derived_problem_ids": [],
            },
        }
        if assessment.get("coverage"):
            resolution_audit["coverage"] = assessment["coverage"]
        return {
            "schema_version": 3,
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
            "candidate_origins": origins,
            "resolution_audit": resolution_audit,
            "importance": {
                "scientific_significance": assessment["scientific_significance"],
                "motivation": assessment["importance_motivation"],
                "consequences_of_progress": assessment["consequences_of_progress"],
                "current_best_result": assessment["current_best_result"],
            },
            "research_triage": {
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
                "rationale": triage["importance_rationale"],
            },
            "discovery_contract": {
                "expected_result": assessment["expected_result"],
            },
            "solution_review_contract": {
                "verification_difficulty": assessment["verification_difficulty"],
                "rationale": assessment["verification_difficulty_rationale"],
                "checklist": "README.md#verification-difficulty",
                "estimated_review_time": assessment["estimated_solution_review_time"],
                "acceptance_boundary": assessment["acceptance_boundary"],
            },
            "ci_contract": {
                "status": assessment["ci_status"],
                "workflow": ".gitlab-ci.yml when a substantive checker exists",
                "driver": "verify/ when a substantive checker exists",
                "pseudocode": "README.md#possible-ci",
                "runner": assessment["ci_runner"],
                "estimated_runtime": assessment["ci_estimated_runtime"],
                "timeout_minutes": assessment["ci_timeout_minutes"],
            },
            "compute": assessment["compute"],
        }

    def _write_triage_deferred(self, records: list[dict[str, Any]]) -> None:
        payload = {
            "schema_version": 1,
            "run_id": self.state["run_id"],
            "count": len(records),
            "candidates": records,
        }
        dump_json(self.run_dir / "triage-deferred.json", payload)
        if self.pool_root:
            destination = (
                self.pool_root / "inbox" / self.state["run_id"] / "triage-deferred.json"
            )
            dump_json(destination, payload)

    def _sync_and_rank(self, accepted: list[str]) -> list[dict[str, Any]]:
        run_manifests = sorted(
            self.run_dir.glob("candidates/*/problem.yaml"),
            key=lambda path: path.parent.name,
        )
        catalog_path = (
            self.pool_root / "pool" / "catalog.jsonl" if self.pool_root else None
        )
        manifests = [*run_manifests]
        manifest_hashes = [
            {
                "path": str(path),
                "sha256": file_sha256(path),
            }
            for path in manifests
        ]
        if catalog_path and catalog_path.is_file():
            manifest_hashes.append(
                {
                    "path": str(catalog_path),
                    "sha256": file_sha256(catalog_path),
                }
            )
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
                existing_repo_names: dict[str, str] = {}
                catalog_path = pool_out / "catalog.jsonl"
                if catalog_path.is_file():
                    for line in catalog_path.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        existing_repo_names[str(row["id"])] = str(
                            row.get("local_repo") or row["id"]
                        )
                with tempfile.TemporaryDirectory(
                    prefix="pool-sync-", dir=self.run_dir
                ) as temporary:
                    sync_root = Path(temporary)
                    records_by_id: dict[str, tuple[dict[str, Any], str]] = {}
                    for path in run_manifests:
                        problem = load_yaml(path)
                        problem_id = str(problem["id"])
                        candidate_state = self.state["candidates"].get(
                            path.parent.name, {}
                        )
                        repo_name = Path(
                            str(candidate_state.get("problem_repo") or problem_id)
                        ).name
                        records_by_id[problem_id] = (problem, repo_name)
                    for problem_id, (problem, repo_name) in records_by_id.items():
                        dump_yaml(sync_root / repo_name / "problem.yaml", problem)

                    command = [
                        sys.executable,
                        str(self.repository_root / "scripts" / "sync_pool.py"),
                        str(sync_root),
                        "--out",
                        str(pool_out),
                        "--preserve-existing",
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
                for manifest in run_manifests:
                    problem = load_yaml(manifest)
                    candidate_state = self.state["candidates"].get(
                        manifest.parent.name, {}
                    )
                    repo_name = Path(
                        str(candidate_state.get("problem_repo") or str(problem["id"]))
                    ).name
                    records.append(problem_to_record(problem, repo_name))
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

    def retry(
        self, candidate_id: str, stage: str, *, defer: bool = False
    ) -> dict[str, Any]:
        if candidate_id not in self.state.get("candidates", {}):
            raise CampaignError(f"unknown candidate: {candidate_id}")
        if stage not in STAGE_ORDER:
            raise CampaignError(f"stage must be one of: {', '.join(STAGE_ORDER)}")
        candidate_dir = self.run_dir / "candidates" / candidate_id
        review_feedback = self._recover_problem_review_feedback(
            candidate_id,
            candidate_dir,
        )
        if stage == "triage":
            self._research_feedback_snapshot(
                candidate_id,
                candidate_dir,
                review_feedback,
                apply_pending=True,
            )
        start = STAGE_ORDER.index(stage)
        downstream = set(STAGE_ORDER[start:])

        def should_remove(key: str) -> bool:
            prefix = f"candidate.{candidate_id}."
            if not key.startswith(prefix):
                return False
            suffix = key[len(prefix) :]
            return any(
                suffix == name or suffix.startswith(f"{name}.") for name in downstream
            )

        self.ledger.invalidate(should_remove)
        self.state["candidates"][candidate_id]["status"] = "retry_requested"
        self.state["status"] = "created"
        self.ledger.save()
        if defer and stage != "research":
            return {
                "candidate_id": candidate_id,
                "stage": stage,
                "deferred": True,
                "status": "retry_requested",
            }
        if stage == "research":
            seeds = list(
                _load_json(self.run_dir / "candidate-seeds.json").get(
                    "candidate_seeds"
                )
                or []
            )
            candidates = self._materialize_candidates(
                _load_json(self.run_dir / "canonicalization.json"),
                seeds,
            )
            candidate = next(
                (item for item in candidates if item["candidate_id"] == candidate_id),
                None,
            )
            if candidate is None:
                raise CampaignError(
                    f"candidate is no longer active after canonicalization: "
                    f"{candidate_id}"
                )
            if defer:
                # Advance the applied-feedback snapshot now so the deferred
                # execution picks up every accumulated reviewer concern; the
                # Triage gate is re-checked when the retry is executed by a
                # later resume instead of blocking the deferral here.
                self._research_feedback_snapshot(
                    candidate_id,
                    candidate_dir,
                    review_feedback,
                    apply_pending=True,
                )
                self.ledger.save()
                return {
                    "candidate_id": candidate_id,
                    "stage": stage,
                    "deferred": True,
                    "status": "retry_requested",
                }
            triage = _load_json(
                self.run_dir / "candidates" / candidate_id / "triage.json"
            )
            if not self._passes_audit_gate(triage):
                raise CampaignError(
                    f"cannot retry research for a candidate that no longer "
                    f"has high or medium importance: {candidate_id}"
                )
            self.state["status"] = "running"
            self.state["error"] = ""
            self.state["updated_at"] = utc_now()
            self.ledger.save()
            verdict, assessment = self._research_and_problem_review(
                candidate,
                triage,
                apply_pending_review_feedback=True,
            )
            self.state["candidates"][candidate_id]["problem_review_verdict"] = verdict[
                "verdict"
            ]
            accepted_before_retry = {
                str(item.get("problem_id"))
                for item in self.state["candidates"].values()
                if item.get("status") == "accepted" and item.get("problem_id")
            }
            final_limit = self._portfolio_limit(shortlist=False)
            portfolio_full = (
                final_limit is not None
                and not self.state["candidates"][candidate_id].get("problem_id")
                and len(accepted_before_retry) >= final_limit
            )
            if (
                verdict["verdict"] == "accept"
                and self._passes_publication_gate(assessment)
                and not portfolio_full
            ):
                compiled = self._compile(candidate, triage, assessment, verdict)
                self.state["candidates"][candidate_id]["status"] = "accepted"
                self.state["candidates"][candidate_id]["problem_id"] = compiled[
                    "problem_id"
                ]
            elif verdict["verdict"] == "accept" and portfolio_full:
                self.state["candidates"][candidate_id]["status"] = (
                    "portfolio_deferred"
                )
            elif verdict["verdict"] == "accept":
                self.state["candidates"][candidate_id]["status"] = "audited_out"
            elif verdict["verdict"] == "reject":
                self.state["candidates"][candidate_id]["status"] = "rejected"
            else:
                self.state["candidates"][candidate_id]["status"] = "needs_revision"
            accepted = sorted(
                {
                    str(item["problem_id"])
                    for item in self.state["candidates"].values()
                    if item.get("status") == "accepted" and item.get("problem_id")
                }
            )
            ranking = self._sync_and_rank(accepted)
            summary = {
                "source_open_questions": sum(
                    seed["origin_class"] == "explicit_source_question"
                    for seed in seeds
                ),
                "candidate_seeds": len(seeds),
                "canonical_candidates": len(candidates),
                "accepted_problem_ids": accepted,
                "triage_deferred_count": sum(
                    item.get("status") == "triage_deferred"
                    for item in self.state["candidates"].values()
                ),
                "ranked_problem_count": len(ranking),
            }
            self.state.update(
                {
                    "status": "completed",
                    "updated_at": utc_now(),
                    "summary": summary,
                }
            )
            self.ledger.save()
            return summary
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
