from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shlex
import signal
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jsonschema import Draft202012Validator

from .agent import (
    AgentExecutionError,
    AgentOutputError,
    CodexRunner,
    file_sha256,
    strict_output_schema_errors,
)
from .common import dump_json_atomic, slugify, utc_now
from .problem_contract import (
    SCIENTIFIC_SIGNIFICANCE_RUBRIC,
    VERIFICATION_DIFFICULTY_RUBRIC,
    dump_problem_contract,
    problem_contract_from_agent_content,
    require_valid_problem_contract,
)


class TopicOrchestrationError(RuntimeError):
    """One per-topic orchestration run violated its deterministic boundary."""


def _json_hash(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _normalized_identifier(value: object) -> str:
    identifier = _normalized_text(value)
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if identifier.startswith(prefix):
            identifier = identifier[len(prefix) :]
            break
    return identifier


def _normalized_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    split = urlsplit(raw)
    query = urlencode(
        sorted(
            (key, val)
            for key, val in parse_qsl(split.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
        )
    )
    path = split.path.rstrip("/") or "/"
    return urlunsplit(
        (split.scheme.casefold(), split.netloc.casefold(), path, query, "")
    )


def _source_identity(source: dict[str, Any]) -> str:
    identifier = _normalized_identifier(source.get("identifier"))
    if identifier:
        return f"identifier:{identifier}"
    url = _normalized_url(source.get("url"))
    if url:
        return f"url:{url}"
    return "title-date:" + "|".join(
        (_normalized_text(source.get("title")), _normalized_text(source.get("date")))
    )


def _stable_id(prefix: str, identity: object, length: int = 16) -> str:
    return f"{prefix}-{_json_hash(identity)[:length].upper()}"


def _best_nonempty(old: object, new: object) -> str:
    left = str(old or "").strip()
    right = str(new or "").strip()
    if not left:
        return right
    if not right:
        return left
    return right if len(right) > len(left) else left


def _bounded_context(excerpt: str, context: str, limit: int) -> str:
    if len(context) <= limit:
        return context
    if len(excerpt) >= limit:
        return excerpt
    index = context.find(excerpt)
    if index < 0:
        return context[:limit]
    remaining = limit - len(excerpt)
    left = min(index, remaining // 2)
    right = min(len(context) - index - len(excerpt), remaining - left)
    left = min(index, remaining - right)
    start = index - left
    end = index + len(excerpt) + right
    return ("..." if start else "") + context[start:end] + (
        "..." if end < len(context) else ""
    )


_CONTENT_RANK = {
    "metadata": 0,
    "abstract": 1,
    "compressed_claim": 2,
    "reasoning_chain": 3,
    "partial_full_text": 4,
    "full_text": 5,
}

_RESEARCH_EVIDENCE_SKILL = "research-evidence-search"
_SEARCH_WORKER_CONTRACT_VERSION = "2"


class EvidenceLedger:
    """Durable, deduplicated evidence shared by all turns of one topic Agent.

    Raw search packets stay in their worker directories.  The ledger keeps
    canonical source/anchor identities and excerpt-sized observations, so a
    resumed Topic Agent never needs every worker packet or full document again.
    """

    SCHEMA_VERSION = "1.0"

    def __init__(self, *, topic_id: str, path: Path, data: dict[str, Any]) -> None:
        self.topic_id = topic_id
        self.path = path
        self.data = data

    @classmethod
    def load(cls, *, topic_id: str, path: Path) -> EvidenceLedger:
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("topic_id") != topic_id:
                raise TopicOrchestrationError(
                    f"evidence ledger does not belong to topic {topic_id}: {path}"
                )
            return cls(topic_id=topic_id, path=path, data=value)
        return cls(
            topic_id=topic_id,
            path=path,
            data={
                "schema_version": cls.SCHEMA_VERSION,
                "topic_id": topic_id,
                "revision": 0,
                "sources": {},
                "anchors": {},
                "packets": {},
            },
        )

    @property
    def revision(self) -> int:
        return int(self.data["revision"])

    @property
    def digest(self) -> str:
        return _json_hash(self.data)

    def save(self) -> None:
        dump_json_atomic(self.path, self.data)

    def has_packet(self, *, brief_id: str, fingerprint: str) -> bool:
        packet = self.data["packets"].get(brief_id)
        return bool(packet and packet.get("fingerprint") == fingerprint)

    def ingest(
        self,
        *,
        packet: dict[str, Any],
        brief_id: str,
        fingerprint: str,
    ) -> bool:
        if self.has_packet(brief_id=brief_id, fingerprint=fingerprint):
            return False
        next_revision = self.revision + 1
        original_to_canonical: dict[str, str] = {}
        packet_source_ids: list[str] = []
        for source in packet["sources"]:
            identity = _source_identity(source)
            canonical_id = _stable_id("SRC", identity)
            original_to_canonical[str(source["source_id"])] = canonical_id
            packet_source_ids.append(canonical_id)
            existing = self.data["sources"].get(canonical_id)
            if existing is None:
                existing = {
                    "source_id": canonical_id,
                    "identity": identity,
                    "origins": [],
                    "title": "",
                    "identifier": "",
                    "url": "",
                    "date": "",
                    "content_level": "metadata",
                    "observations": [],
                    "first_revision": next_revision,
                    "last_revision": next_revision,
                }
                self.data["sources"][canonical_id] = existing
            origin = str(source["source"])
            if origin not in existing["origins"]:
                existing["origins"].append(origin)
                existing["origins"].sort()
            for field in ("title", "identifier", "url", "date"):
                existing[field] = _best_nonempty(existing[field], source.get(field))
            if _CONTENT_RANK.get(str(source["content_level"]), -1) > _CONTENT_RANK.get(
                str(existing["content_level"]), -1
            ):
                existing["content_level"] = source["content_level"]
            observation = {
                "exact_excerpt": str(source["exact_excerpt"]),
                "surrounding_context": str(source["surrounding_context"]),
                "brief_ids": [brief_id],
            }
            observation_identity = _json_hash(
                {
                    "excerpt": _normalized_text(observation["exact_excerpt"]),
                    "context": _normalized_text(observation["surrounding_context"]),
                }
            )
            matched = next(
                (
                    item
                    for item in existing["observations"]
                    if item["observation_id"] == observation_identity
                ),
                None,
            )
            if matched is None:
                existing["observations"].append(
                    {
                        "observation_id": observation_identity,
                        "first_revision": next_revision,
                        **observation,
                    }
                )
            elif brief_id not in matched["brief_ids"]:
                matched["brief_ids"].append(brief_id)
                matched["brief_ids"].sort()
            existing["observations"].sort(key=lambda item: item["observation_id"])
            existing["last_revision"] = next_revision

        packet_anchor_ids: list[str] = []
        for anchor in packet["anchors"]:
            canonical_sources = sorted(
                {original_to_canonical[source_id] for source_id in anchor["source_ids"]}
            )
            identity = {
                "statement": _normalized_text(anchor["statement"]),
                "source_ids": canonical_sources,
            }
            canonical_id = _stable_id("ANC", identity)
            packet_anchor_ids.append(canonical_id)
            existing = self.data["anchors"].get(canonical_id)
            if existing is None:
                existing = {
                    "anchor_id": canonical_id,
                    "anchor_type": anchor["anchor_type"],
                    "statement": str(anchor["statement"]),
                    "source_ids": canonical_sources,
                    "closest_prior": str(anchor["closest_prior"]),
                    "why_open": str(anchor["why_open"]),
                    "freshness_searches": [],
                    "brief_ids": [],
                    "first_revision": next_revision,
                    "last_revision": next_revision,
                }
                self.data["anchors"][canonical_id] = existing
            existing["closest_prior"] = _best_nonempty(
                existing["closest_prior"], anchor["closest_prior"]
            )
            existing["why_open"] = _best_nonempty(
                existing["why_open"], anchor["why_open"]
            )
            existing["freshness_searches"] = sorted(
                {
                    *existing["freshness_searches"],
                    *(str(item) for item in anchor["freshness_searches"]),
                }
            )
            if brief_id not in existing["brief_ids"]:
                existing["brief_ids"].append(brief_id)
                existing["brief_ids"].sort()
            existing["last_revision"] = next_revision

        self.data["packets"][brief_id] = {
            "fingerprint": fingerprint,
            "source_ids": sorted(set(packet_source_ids)),
            "anchor_ids": sorted(set(packet_anchor_ids)),
            "search_summary": str(packet["search_summary"]),
            "revision": next_revision,
        }
        self.data["revision"] = next_revision
        return True

    def coverage_summary(self, *, max_anchors: int = 24) -> dict[str, Any]:
        anchors = [
            {
                "anchor_id": anchor["anchor_id"],
                "anchor_type": anchor["anchor_type"],
                "statement": anchor["statement"],
                "brief_ids": anchor["brief_ids"],
            }
            for _, anchor in sorted(self.data["anchors"].items())[:max_anchors]
        ]
        return {
            "revision": self.revision,
            "source_count": len(self.data["sources"]),
            "anchor_count": len(self.data["anchors"]),
            "covered_briefs": sorted(self.data["packets"]),
            "anchors": anchors,
        }

    def synthesis_view(
        self,
        *,
        since_revision: int = 0,
        context_chars_per_source: int = 2400,
        observations_per_source: int = 2,
    ) -> dict[str, Any]:
        anchors = [
            anchor
            for _, anchor in sorted(self.data["anchors"].items())
            if int(anchor.get("last_revision", 0)) > since_revision
        ]
        referenced = {
            source_id for anchor in anchors for source_id in anchor["source_ids"]
        }
        sources: list[dict[str, Any]] = []
        for source_id in sorted(referenced):
            source = self.data["sources"][source_id]
            observations = sorted(
                [
                    item
                    for item in source["observations"]
                    if int(item.get("first_revision", 0)) > since_revision
                ]
                or source["observations"][:1],
                key=lambda item: (
                    -len(item["exact_excerpt"]),
                    item["observation_id"],
                ),
            )[:observations_per_source]
            sources.append(
                {
                    key: source[key]
                    for key in (
                        "source_id",
                        "origins",
                        "title",
                        "identifier",
                        "url",
                        "date",
                        "content_level",
                    )
                }
                | {
                    "observations": [
                        {
                            "exact_excerpt": item["exact_excerpt"],
                            "surrounding_context": _bounded_context(
                                item["exact_excerpt"],
                                item["surrounding_context"],
                                context_chars_per_source,
                            ),
                            "brief_ids": item["brief_ids"],
                        }
                        for item in observations
                    ]
                }
            )
        return {
            "topic_id": self.topic_id,
            "since_revision": since_revision,
            "revision": self.revision,
            "sources": sources,
            "anchors": anchors,
        }

    def reference_strings(self, source_ids: list[str]) -> list[str]:
        references: list[str] = []
        for source_id in source_ids:
            source = self.data["sources"][source_id]
            parts = [
                str(source[field]).strip()
                for field in ("title", "identifier", "url")
                if str(source[field]).strip()
            ]
            reference = " — ".join(parts)
            if reference and reference not in references:
                references.append(reference)
        return references

    def companion_dossier(
        self,
        *,
        problem_id: str,
        source_ids: list[str],
        anchor_ids: list[str],
    ) -> dict[str, Any]:
        """Return the auditable evidence subgraph for one public contract."""

        selected_sources = {
            source_id: self.data["sources"][source_id] for source_id in source_ids
        }
        selected_anchors = {
            anchor_id: self.data["anchors"][anchor_id] for anchor_id in anchor_ids
        }
        selected_anchor_set = set(anchor_ids)
        packets = {
            brief_id: packet
            for brief_id, packet in self.data["packets"].items()
            if selected_anchor_set.intersection(packet["anchor_ids"])
        }
        return {
            "schema_version": "1.0",
            "topic_id": self.topic_id,
            "problem_id": problem_id,
            "ledger_revision": self.revision,
            "ledger_sha256": self.digest,
            "source_ids": source_ids,
            "anchor_ids": anchor_ids,
            "sources": selected_sources,
            "anchors": selected_anchors,
            "search_packets": packets,
        }


@dataclass(frozen=True)
class TopicSessionTurn:
    output: dict[str, Any]
    metadata: dict[str, Any]
    thread_id: str


class TopicSession(Protocol):
    def start(
        self,
        *,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> TopicSessionTurn: ...

    def resume(
        self,
        *,
        thread_id: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> TopicSessionTurn: ...


class CodexTopicSession:
    """A non-ephemeral Codex main Agent resumed across one topic's turns."""

    def __init__(
        self,
        *,
        repository_root: Path,
        executable: str = "codex",
        model: str = "",
        sandbox: str = "read-only",
        timeout_seconds: int = 3600,
    ) -> None:
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("Codex sandbox must be read-only or workspace-write")
        self.repository_root = repository_root.resolve()
        self.executable = executable
        self.model = model
        self.sandbox = sandbox
        self.timeout_seconds = timeout_seconds
        self._version: str | None = None

    def version(self) -> str:
        if self._version is None:
            completed = subprocess.run(
                [*shlex.split(self.executable), "--version"],
                cwd=self.repository_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            rendered = (completed.stdout or completed.stderr).strip()
            self._version = rendered or f"exit={completed.returncode}"
        return self._version

    def start(
        self,
        *,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> TopicSessionTurn:
        command = [
            *shlex.split(self.executable),
            "exec",
            "--ignore-user-config",
            "--json",
            "--color",
            "never",
            "--sandbox",
            self.sandbox,
            "--output-schema",
            str(schema_path.resolve()),
            "--output-last-message",
            str(output_path.resolve()),
            "--cd",
            str(self.repository_root),
        ]
        if self.model:
            command.extend(["--model", self.model])
        command.append("-")
        return self._execute(
            command=command,
            prompt=prompt,
            schema_path=schema_path,
            output_path=output_path,
            events_path=events_path,
            expected_thread_id=None,
            action="topic-main-start",
        )

    def resume(
        self,
        *,
        thread_id: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> TopicSessionTurn:
        self._require_session_uuid(thread_id)
        command = [
            *shlex.split(self.executable),
            "exec",
            "resume",
            "--ignore-user-config",
            "--json",
            "--output-schema",
            str(schema_path.resolve()),
            "--output-last-message",
            str(output_path.resolve()),
        ]
        if self.model:
            command.extend(["--model", self.model])
        command.extend([thread_id, "-"])
        return self._execute(
            command=command,
            prompt=prompt,
            schema_path=schema_path,
            output_path=output_path,
            events_path=events_path,
            expected_thread_id=thread_id,
            action="topic-main-resume",
        )

    @staticmethod
    def _event_thread_id(stdout: str) -> str:
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            for key in ("thread_id", "threadId", "session_id", "sessionId"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _require_session_uuid(thread_id: str) -> str:
        try:
            parsed = uuid.UUID(thread_id)
        except (ValueError, AttributeError) as error:
            raise ValueError(
                "topic Agent thread_id must be an exact session UUID"
            ) from error
        return str(parsed)

    def _execute(
        self,
        *,
        command: list[str],
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
        expected_thread_id: str | None,
        action: str,
    ) -> TopicSessionTurn:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        strict_errors = strict_output_schema_errors(schema)
        if strict_errors:
            raise AgentOutputError(
                "output schema is incompatible with Codex structured output: "
                + "; ".join(strict_errors)
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        process = subprocess.Popen(
            command,
            cwd=self.repository_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(
                input=prompt, timeout=self.timeout_seconds
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired as drained:
                for stream in (process.stdout, process.stderr, process.stdin):
                    try:
                        if stream is not None:
                            stream.close()
                    except OSError:
                        pass
                process.wait()
                stdout = drained.output or ""
                stderr = drained.stderr or ""
                if isinstance(stdout, bytes):
                    stdout = stdout.decode(errors="replace")
                if isinstance(stderr, bytes):
                    stderr = stderr.decode(errors="replace")
        events_path.write_text(stdout, encoding="utf-8")
        stderr_path = events_path.with_suffix(".stderr.log")
        stderr_path.write_text(stderr, encoding="utf-8")
        if timed_out:
            raise AgentExecutionError(
                f"{action} timed out after {self.timeout_seconds}s; "
                f"see {stderr_path}"
            )
        if process.returncode != 0:
            raise AgentExecutionError(
                f"{action} failed with exit {process.returncode}; see {stderr_path}"
            )
        if not output_path.is_file():
            raise AgentExecutionError(
                f"{action} did not write structured output to {output_path}"
            )
        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise AgentOutputError(f"{action} output is not valid JSON: {error}") from error
        findings = sorted(
            Draft202012Validator(schema).iter_errors(output),
            key=lambda item: list(item.absolute_path),
        )
        if findings:
            details = "; ".join(
                f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: "
                f"{error.message}"
                for error in findings[:8]
            )
            raise AgentOutputError(f"{action} output failed schema validation: {details}")
        event_thread_id = self._event_thread_id(stdout)
        thread_id = expected_thread_id or event_thread_id
        if not thread_id:
            raise AgentExecutionError(
                f"{action} did not emit a thread_id in {events_path}"
            )
        self._require_session_uuid(thread_id)
        if expected_thread_id and event_thread_id and event_thread_id != expected_thread_id:
            raise AgentExecutionError(
                f"{action} resumed {event_thread_id}, expected {expected_thread_id}"
            )
        metadata = {
            "role": "topic-main",
            "action": action,
            "command": command,
            "codex_version": self.version(),
            "model": self.model or "configured-default",
            "sandbox": self.sandbox,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "schema": str(schema_path),
            "schema_sha256": file_sha256(schema_path),
            "events": str(events_path),
            "stderr": str(stderr_path),
            "exit_code": process.returncode,
            "thread_id": thread_id,
        }
        return TopicSessionTurn(output=output, metadata=metadata, thread_id=thread_id)


@dataclass(frozen=True)
class TopicOrchestrationResult:
    topic_id: str
    thread_id: str
    ledger_path: Path
    dossier_path: Path
    contracts: list[dict[str, Any]]
    reused_search_briefs: list[str]


class TopicOrchestrator:
    """Deterministic control plane around one persistent Topic Main Agent."""

    def __init__(
        self,
        *,
        repository_root: Path,
        state_root: Path,
        session: TopicSession | None = None,
        search_runner: CodexRunner | None = None,
        workers: int = 4,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.state_root = state_root.resolve()
        self.schemas = self.repository_root / "schemas"
        self.session = session or CodexTopicSession(
            repository_root=self.repository_root
        )
        self.search_runner = search_runner or CodexRunner(
            repository_root=self.repository_root
        )
        self.workers = max(1, workers)

    def run(
        self,
        *,
        topic_id: str,
        topic: str,
        search_groups: int = 4,
        sources: list[str] | None = None,
        max_contracts: int = 6,
        seed_papers: list[dict[str, Any]] | None = None,
        review_delta: dict[str, Any] | None = None,
    ) -> TopicOrchestrationResult:
        """Run one topic while holding its cross-process session lock."""

        topic_dir = self._topic_directory(topic_id)
        topic_dir.mkdir(parents=True, exist_ok=True)
        lock_path = topic_dir / ".topic-session.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                return self._run_locked(
                    topic_id=topic_id,
                    topic=topic,
                    search_groups=search_groups,
                    sources=sources,
                    max_contracts=max_contracts,
                    seed_papers=seed_papers,
                    review_delta=review_delta,
                )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _run_locked(
        self,
        *,
        topic_id: str,
        topic: str,
        search_groups: int = 4,
        sources: list[str] | None = None,
        max_contracts: int = 6,
        seed_papers: list[dict[str, Any]] | None = None,
        review_delta: dict[str, Any] | None = None,
    ) -> TopicOrchestrationResult:
        sources = list(sources or ["lkm", "web"])
        if not topic_id.strip() or not topic.strip():
            raise ValueError("topic_id and topic are required")
        if search_groups < 1 or max_contracts < 1:
            raise ValueError("search_groups and max_contracts must be positive")
        topic_dir = self._topic_directory(topic_id)
        topic_dir.mkdir(parents=True, exist_ok=True)
        dossier_path = topic_dir / "topic-session-dossier.json"
        dossier = self._load_dossier(dossier_path, topic_id, topic)
        ledger = EvidenceLedger.load(
            topic_id=topic_id, path=topic_dir / "evidence-ledger.json"
        )

        plan_inputs = {
            "topic_id": topic_id,
            "topic": topic,
            "search_groups": search_groups,
            "sources": sources,
            "seed_papers": seed_papers or [],
            "prior_coverage": ledger.coverage_summary(),
        }
        plan_hash = _json_hash(
            {key: value for key, value in plan_inputs.items() if key != "prior_coverage"}
        )
        plan_path = topic_dir / "search-plan.json"
        cached_plan = dossier.get("plan") or {}
        if cached_plan.get("input_sha256") == plan_hash and plan_path.is_file():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self._validate_plan(plan, topic_id, search_groups)
        else:
            prompt = self._plan_prompt(plan_inputs)
            turn = self._topic_turn(
                dossier=dossier,
                prompt=prompt,
                schema_path=self.schemas / "stages" / "discovery-plan.schema.json",
                output_path=plan_path,
                events_path=topic_dir / "events" / f"plan-{plan_hash[:12]}.jsonl",
            )
            plan = turn.output
            self._validate_plan(plan, topic_id, search_groups)
            dossier["thread_id"] = turn.thread_id
            dossier["plan"] = {
                "input_sha256": plan_hash,
                "output": str(plan_path.relative_to(topic_dir)),
                "turn": turn.metadata,
            }
            self._save_dossier(dossier_path, dossier, ledger)

        reused: list[str] = []
        pending: list[tuple[dict[str, Any], str]] = []
        for brief in plan["briefs"]:
            fingerprint = _json_hash(
                {
                    "worker_contract_version": _SEARCH_WORKER_CONTRACT_VERSION,
                    "topic": topic,
                    "sources": sources,
                    "brief": brief,
                }
            )
            if ledger.has_packet(
                brief_id=brief["brief_id"], fingerprint=fingerprint
            ):
                reused.append(brief["brief_id"])
            else:
                pending.append((brief, fingerprint))

        packets: dict[str, tuple[dict[str, Any], str]] = {}
        if pending:
            with ThreadPoolExecutor(
                max_workers=min(self.workers, len(pending)),
                thread_name_prefix=f"topic-search-{slugify(topic_id)}",
            ) as executor:
                futures = {
                    executor.submit(
                        self._search,
                        topic_dir=topic_dir,
                        topic_id=topic_id,
                        topic=topic,
                        sources=sources,
                        brief=brief,
                        fingerprint=fingerprint,
                    ): (brief, fingerprint)
                    for brief, fingerprint in pending
                }
                for future in as_completed(futures):
                    brief, fingerprint = futures[future]
                    packets[brief["brief_id"]] = (future.result(), fingerprint)
            for brief in plan["briefs"]:
                brief_id = brief["brief_id"]
                if brief_id not in packets:
                    continue
                packet, fingerprint = packets[brief_id]
                self._validate_packet(packet, topic_id, brief_id, sources)
                ledger.ingest(
                    packet=packet, brief_id=brief_id, fingerprint=fingerprint
                )
            ledger.save()
            self._save_dossier(dossier_path, dossier, ledger)

        seen_revision = int(dossier.get("session_evidence_revision", 0))
        view = ledger.synthesis_view(since_revision=seen_revision)
        if (
            review_delta is None
            and ledger.revision > seen_revision
            and not view["anchors"]
        ):
            raise TopicOrchestrationError(
                "new search packets contained no usable evidence anchors; "
                "refusing to synthesize new contracts from prior session context"
            )
        review_hash = _json_hash(review_delta) if review_delta is not None else ""
        if review_delta is not None:
            review_path = topic_dir / "review-deltas" / f"{review_hash}.json"
            if not review_path.is_file():
                dump_json_atomic(review_path, review_delta)
            dossier.setdefault("review_deltas", [])
            review_record = {
                "sha256": review_hash,
                "path": str(review_path.relative_to(topic_dir)),
            }
            if review_record not in dossier["review_deltas"]:
                dossier["review_deltas"].append(review_record)
        synthesis_inputs = {
            "topic_id": topic_id,
            "topic": topic,
            "ledger_digest": ledger.digest,
            "ledger_revision": ledger.revision,
            "max_contracts": max_contracts,
            "review_delta_sha256": review_hash,
        }
        synthesis_hash = _json_hash(synthesis_inputs)
        synthesis_path = topic_dir / "contract-drafts.json"
        cached_synthesis = dossier.get("synthesis") or {}
        if (
            cached_synthesis.get("input_sha256") == synthesis_hash
            and synthesis_path.is_file()
        ):
            synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
        else:
            prompt = self._synthesis_prompt(
                topic_id=topic_id,
                topic=topic,
                max_contracts=max_contracts,
                evidence_delta=view,
                review_delta=review_delta,
            )
            turn = self._topic_turn(
                dossier=dossier,
                prompt=prompt,
                schema_path=(
                    self.schemas
                    / "stages"
                    / "topic-contract-drafts.schema.json"
                ),
                output_path=synthesis_path,
                events_path=(
                    topic_dir / "events" / f"contracts-{synthesis_hash[:12]}.jsonl"
                ),
            )
            synthesis = turn.output
            dossier["thread_id"] = turn.thread_id
            dossier["synthesis"] = {
                "input_sha256": synthesis_hash,
                "output": str(synthesis_path.relative_to(topic_dir)),
                "turn": turn.metadata,
            }
            dossier["session_evidence_revision"] = ledger.revision
            dossier["latest_review_delta_sha256"] = review_hash

        contracts = self._compile_contracts(
            topic_id=topic_id,
            synthesis=synthesis,
            ledger=ledger,
            max_contracts=max_contracts,
            topic_dir=topic_dir,
        )
        dossier["contracts"] = [
            {
                "problem_id": contract["problem_id"],
                "path": f"contracts/{contract['problem_id']}.json",
                "companion_dossier": (
                    f"contracts/{contract['problem_id']}.dossier.json"
                ),
            }
            for contract in contracts
        ]
        self._save_dossier(dossier_path, dossier, ledger)
        return TopicOrchestrationResult(
            topic_id=topic_id,
            thread_id=str(dossier["thread_id"]),
            ledger_path=ledger.path,
            dossier_path=dossier_path,
            contracts=contracts,
            reused_search_briefs=sorted(reused),
        )

    def revise_contract(
        self,
        *,
        topic_id: str,
        contract: dict[str, Any],
        review_delta: dict[str, Any],
    ) -> dict[str, Any]:
        """Resume the exact Topic Agent with one contract and one review delta."""

        topic_dir = self._topic_directory(topic_id)
        dossier_path = topic_dir / "topic-session-dossier.json"
        lock_path = topic_dir / ".topic-session.lock"
        if not dossier_path.is_file():
            raise TopicOrchestrationError(
                f"no persistent Topic Agent dossier for {topic_id}"
            )
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
                thread_id = str(dossier.get("thread_id") or "")
                if not thread_id:
                    raise TopicOrchestrationError(
                        "cannot apply review without the Topic Agent session UUID"
                    )
                schema_path = self.schemas / "problem-contract.schema.json"
                require_valid_problem_contract(contract, schema_path)
                review_hash = _json_hash(review_delta)
                contract_hash = _json_hash(contract)
                review_path = topic_dir / "review-deltas" / f"{review_hash}.json"
                if not review_path.is_file():
                    dump_json_atomic(review_path, review_delta)
                content_path = (
                    topic_dir
                    / "revisions"
                    / contract["problem_id"]
                    / f"{review_hash[:12]}-content.json"
                )
                prompt = f"""
Continue as the same Topic Main Agent. An independent headless Reviewer has
audited the exact current Problem Contract below. Rewrite only what the review
delta requires while preserving the scientific question whenever possible.
This is a revision turn, not a new literature search: use the evidence already
held in this session, do not re-read the corpus, and do not invent references.
Treat the review as a constraint diagnosis, not as permission to replace the
scientific question with arbitrary numerical thresholds, benchmark instances,
model choices, or proof architecture. Preserve the largest source-faithful
scope that still admits a determinate solve/not-solve decision. If a requested
detail is unsupported by the existing evidence, remove the unsupported claim,
make the inherited source definition explicit in human-readable prose, or
decompose the target; do not manufacture specificity.

Never repair an unresolved scope by asking a future answer submission to
choose, select, define, or delimit the scientific target. The Topic Main Agent
must freeze the named model or mathematical class, physical system, parameter
domain, representation, benchmark population when one is intrinsic to the
claim, and all load-bearing quantifiers from the existing evidence. An answer
may choose only a method or a witness inside that already fixed domain. For an
explicitly source-aligned existential claim, the admissible universe and the
predicate a witness must satisfy must still be fixed by the Contract.

Apply the scope-ownership gate after rewriting: could two complete-looking
answers choose materially different scientific targets and both claim success?
If yes, the leaf is still invalid. Freeze the target from evidence or decompose
it into fixed children; never pass target selection through to the answer.

Keep internal canonical source IDs out of all public Contract prose. Refer to
the human-readable bibliography and precise source locators instead. Ensure
that alternative answer branches resolve the same quantified target, and that
impact claims follow from the minimum result accepted by the contract.
Return one complete contract-content object. The deterministic controller will
preserve the problem ID, validate the result, and restore the current reference
list.

Current Problem Contract:
{json.dumps(contract, ensure_ascii=False, indent=2)}
Review delta:
{json.dumps(review_delta, ensure_ascii=False, indent=2)}
""".strip()
                turn = self.session.resume(
                    thread_id=thread_id,
                    prompt=prompt,
                    schema_path=(
                        self.schemas / "stages" / "problem-contract-content.schema.json"
                    ),
                    output_path=content_path,
                    events_path=content_path.with_suffix(".events.jsonl"),
                )
                content = dict(turn.output)
                content["references"] = list(contract.get("references") or [])
                revised = problem_contract_from_agent_content(
                    problem_id=contract["problem_id"],
                    content=content,
                    schema_path=schema_path,
                )
                contract_path = topic_dir / "contracts" / f"{contract['problem_id']}.json"
                dump_problem_contract(contract_path, revised, schema_path)
                dossier.setdefault("review_deltas", [])
                review_record = {
                    "sha256": review_hash,
                    "path": str(review_path.relative_to(topic_dir)),
                }
                if review_record not in dossier["review_deltas"]:
                    dossier["review_deltas"].append(review_record)
                dossier.setdefault("revisions", []).append(
                    {
                        "problem_id": contract["problem_id"],
                        "input_contract_sha256": contract_hash,
                        "review_delta_sha256": review_hash,
                        "output": str(contract_path.relative_to(topic_dir)),
                        "turn": turn.metadata,
                    }
                )
                dossier["thread_id"] = turn.thread_id
                ledger = EvidenceLedger.load(
                    topic_id=topic_id, path=topic_dir / "evidence-ledger.json"
                )
                self._save_dossier(dossier_path, dossier, ledger)
                return revised
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _topic_turn(
        self,
        *,
        dossier: dict[str, Any],
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> TopicSessionTurn:
        thread_id = str(dossier.get("thread_id") or "")
        if thread_id:
            return self.session.resume(
                thread_id=thread_id,
                prompt=prompt,
                schema_path=schema_path,
                output_path=output_path,
                events_path=events_path,
            )
        return self.session.start(
            prompt=prompt,
            schema_path=schema_path,
            output_path=output_path,
            events_path=events_path,
        )

    def _search(
        self,
        *,
        topic_dir: Path,
        topic_id: str,
        topic: str,
        sources: list[str],
        brief: dict[str, Any],
        fingerprint: str,
    ) -> dict[str, Any]:
        brief_id = brief["brief_id"]
        prompt = f"""
You are one ephemeral evidence-search worker delegated by a persistent Topic
Main Agent. Use ${_RESEARCH_EVIDENCE_SKILL} and search only this brief in the
allowed sources. If LKM is allowed, execute at least one Gaia LKM route from
that skill; if web is allowed, execute at least one web route. Record attempted
routes and any source with no usable result in search_summary. Inspect enough
surrounding context to avoid quote mining and execute the disconfirming and
freshness searches. Return evidence packets, not final problems. Every anchor
must cite source IDs in this packet. If the evidence is insufficient, return
no anchors rather than inventing one. Do not repeat or summarize unrelated
documents. For every source, exact_excerpt must be copied verbatim from the
source, and surrounding_context must also be verbatim source text that contains
exact_excerpt as a literal substring. Never use your explanation, paraphrase,
or citation analysis as surrounding_context; put such analysis only in the
anchor fields or search_summary.

Topic id: {topic_id}
Topic: {topic}
Allowed sources: {json.dumps(sources)}
Assigned brief:
{json.dumps(brief, ensure_ascii=False, indent=2)}
""".strip()
        result = self.search_runner.run(
            role="strategy-search",
            prompt=prompt,
            schema_path=self.schemas / "stages" / "evidence-packet.schema.json",
            output_path=(
                topic_dir
                / "search-workers"
                / brief_id
                / f"{fingerprint[:12]}-evidence.json"
            ),
            events_path=(
                topic_dir / "search-workers" / brief_id / f"{fingerprint[:12]}.jsonl"
            ),
        )
        return result.output

    @staticmethod
    def _plan_prompt(inputs: dict[str, Any]) -> str:
        return f"""
You are the persistent Topic Main Agent for one scientific topic. This is a
planning turn; do not perform literature search and do not propose final
problems. Create exactly {inputs['search_groups']} independent briefs for
ephemeral search workers. Use distinct CDQ-style routes and include
disconfirming searches that could show a gap is closed. The control program
will run those workers and resume this same session with a compact evidence
ledger. Existing coverage is provided only to avoid repeating already covered
directions.

Topic id: {inputs['topic_id']}
Topic: {inputs['topic']}
Allowed sources: {json.dumps(inputs['sources'])}
Seed papers: {json.dumps(inputs['seed_papers'], ensure_ascii=False)}
Compact prior coverage:
{json.dumps(inputs['prior_coverage'], ensure_ascii=False, indent=2)}
""".strip()

    @staticmethod
    def _synthesis_prompt(
        *,
        topic_id: str,
        topic: str,
        max_contracts: int,
        evidence_delta: dict[str, Any],
        review_delta: dict[str, Any] | None,
    ) -> str:
        return f"""
Continue as the same Topic Main Agent. The deterministic control program ran
your delegated search briefs and normalized their results into a durable
ledger. This turn receives only evidence added or changed since the last
successful turn; retain the earlier evidence already in this session. A review
delta, when present, is the only new reviewer instruction. Do not request or
re-read full documents unless a later targeted search is strictly necessary.
Synthesize at most {max_contracts} diverse, atomic Problem Contract drafts.
Use canonical IDs only in each draft's source_ids field; never expose them in
public Contract prose. Align famous problems with the literature and do not
strengthen, narrow, or otherwise
distort an evidence anchor merely to simplify verification. Split an over-broad
target rather than write an ambiguous contract. Leave content.references empty:
the program will derive exact references from source_ids.

Original literature is an allowed dependency: use precise source locators
instead of forcing a self-contained restatement that changes the question. Seek
the largest source-faithful scope that still has a determinate resolution
criterion. Do not add model, parameter, method, proof-architecture, artifact,
or implementation restrictions unless they are source-mandated, scientifically
necessary, or required to make resolution determinate.

The Topic Main Agent owns the scientific target. Before emitting a leaf, freeze
the named model or mathematical class, physical system, parameter domain,
representation, benchmark population when one is intrinsic to the claim, and
all load-bearing quantifiers from the evidence. Never ask a future answer
submission to choose, select, define, or delimit any of them. An answer may
choose a method or a witness only inside an already fixed quantified domain.
For a genuinely source-aligned existential problem, the Contract must still
fix the admissible universe and the exact predicate the witness must satisfy.

Apply a scope-ownership gate before emitting each leaf: could two
complete-looking answers choose materially different scientific targets and
both claim success? If yes, the Contract is invalid. Use the evidence to freeze
one source-supported target, run a later targeted search when the ledger is
insufficient, or represent the broad aim as a parent with fixed child problems.

Every leaf contract must let a complete submitted solution be classified as
solving or not solving the stated problem. If the scientific aim is broader,
represent it as a parent and delegate acceptance to resolvable child contracts.
Cover every legitimate answer branch in verification_contracts, and keep CI
limited to checks that are genuinely mechanical. Assess actual impact: a narrow
technical problem may still be important when the evidence identifies it as a
load-bearing bottleneck, but do not inflate significance through speculative
downstream claims.

Scientific significance rubric: {SCIENTIFIC_SIGNIFICANCE_RUBRIC}
Verification difficulty rubric: {VERIFICATION_DIFFICULTY_RUBRIC}

Topic id: {topic_id}
Topic: {topic}
Evidence delta (revision {evidence_delta['since_revision']} to
{evidence_delta['revision']}):
{json.dumps(evidence_delta, ensure_ascii=False, indent=2)}
Review delta:
{json.dumps(review_delta or {}, ensure_ascii=False, indent=2)}
""".strip()

    @staticmethod
    def _validate_plan(
        plan: dict[str, Any], topic_id: str, search_groups: int
    ) -> None:
        if plan.get("domain_id") != topic_id:
            raise TopicOrchestrationError("topic plan returned the wrong domain_id")
        briefs = list(plan.get("briefs") or [])
        if len(briefs) != search_groups:
            raise TopicOrchestrationError(
                f"topic plan must return exactly {search_groups} briefs"
            )
        ids = [brief["brief_id"] for brief in briefs]
        axes = [_normalized_text(brief["coverage_axis"]) for brief in briefs]
        if len(ids) != len(set(ids)) or len(axes) != len(set(axes)):
            raise TopicOrchestrationError(
                "topic plan brief IDs and coverage axes must be distinct"
            )

    @staticmethod
    def _validate_packet(
        packet: dict[str, Any],
        topic_id: str,
        brief_id: str,
        allowed_sources: list[str],
    ) -> None:
        if packet.get("domain_id") != topic_id or packet.get("brief_id") != brief_id:
            raise TopicOrchestrationError("evidence packet returned the wrong topic or brief")
        source_ids = [source["source_id"] for source in packet["sources"]]
        if len(source_ids) != len(set(source_ids)):
            raise TopicOrchestrationError("worker source IDs must be unique")
        if any(source["source"] not in allowed_sources for source in packet["sources"]):
            raise TopicOrchestrationError("worker used a disabled evidence source")
        if any(
            source["exact_excerpt"] not in source["surrounding_context"]
            for source in packet["sources"]
        ):
            raise TopicOrchestrationError("exact excerpt is absent from its context")
        known = set(source_ids)
        if any(
            not set(anchor["source_ids"]).issubset(known)
            for anchor in packet["anchors"]
        ):
            raise TopicOrchestrationError("anchor cites an unknown worker source ID")

    def _compile_contracts(
        self,
        *,
        topic_id: str,
        synthesis: dict[str, Any],
        ledger: EvidenceLedger,
        max_contracts: int,
        topic_dir: Path,
    ) -> list[dict[str, Any]]:
        if synthesis.get("domain_id") != topic_id:
            raise TopicOrchestrationError("contract synthesis returned the wrong domain_id")
        if int(synthesis.get("ledger_revision", -1)) != ledger.revision:
            raise TopicOrchestrationError("contract synthesis used a stale evidence ledger")
        drafts = list(synthesis.get("drafts") or [])
        if len(drafts) > max_contracts:
            raise TopicOrchestrationError("contract synthesis exceeded max_contracts")
        draft_keys = [str(draft["draft_key"]) for draft in drafts]
        if len(draft_keys) != len(set(draft_keys)):
            raise TopicOrchestrationError("contract draft keys must be unique")
        known_sources = set(ledger.data["sources"])
        known_anchors = set(ledger.data["anchors"])
        contracts: list[dict[str, Any]] = []
        contracts_dir = topic_dir / "contracts"
        contract_schema = self.schemas / "problem-contract.schema.json"
        for draft in drafts:
            source_ids = list(dict.fromkeys(draft["source_ids"]))
            anchor_ids = list(dict.fromkeys(draft["anchor_ids"]))
            if not set(source_ids).issubset(known_sources):
                raise TopicOrchestrationError("contract draft cites an unknown source ID")
            if not set(anchor_ids).issubset(known_anchors):
                raise TopicOrchestrationError("contract draft cites an unknown anchor ID")
            anchor_sources = {
                source_id
                for anchor_id in anchor_ids
                for source_id in ledger.data["anchors"][anchor_id]["source_ids"]
            }
            if not anchor_sources.issubset(set(source_ids)):
                raise TopicOrchestrationError(
                    "contract source IDs do not cover every cited anchor"
                )
            content = dict(draft["content"])
            content["references"] = ledger.reference_strings(source_ids)
            problem_number = int(
                _json_hash({"topic_id": topic_id, "draft_key": draft["draft_key"]})[:12],
                16,
            )
            problem_id = f"ORP-{problem_number:015d}"
            contract = problem_contract_from_agent_content(
                problem_id=problem_id,
                content=content,
                schema_path=contract_schema,
            )
            dump_problem_contract(
                contracts_dir / f"{problem_id}.json", contract, contract_schema
            )
            dump_json_atomic(
                contracts_dir / f"{problem_id}.dossier.json",
                ledger.companion_dossier(
                    problem_id=problem_id,
                    source_ids=source_ids,
                    anchor_ids=anchor_ids,
                ),
            )
            contracts.append(contract)
        return contracts

    @staticmethod
    def _load_dossier(path: Path, topic_id: str, topic: str) -> dict[str, Any]:
        if path.is_file():
            dossier = json.loads(path.read_text(encoding="utf-8"))
            if dossier.get("topic_id") != topic_id:
                raise TopicOrchestrationError("topic dossier belongs to another topic")
            if dossier.get("topic") != topic:
                raise TopicOrchestrationError(
                    "topic text changed for an existing persistent Topic Agent"
                )
            return dossier
        return {
            "schema_version": "1.0",
            "topic_id": topic_id,
            "topic": topic,
            "thread_id": "",
            "created_at": utc_now(),
        }

    def _topic_directory(self, topic_id: str) -> Path:
        # The digest prevents path collisions such as ``a/b`` versus ``a-b``.
        return self.state_root / f"{slugify(topic_id)}-{_json_hash(topic_id)[:8]}"

    @staticmethod
    def _save_dossier(
        path: Path, dossier: dict[str, Any], ledger: EvidenceLedger
    ) -> None:
        dossier["updated_at"] = utc_now()
        dossier["evidence"] = {
            "path": str(ledger.path.name),
            "revision": ledger.revision,
            "sha256": ledger.digest,
            "coverage": ledger.coverage_summary(),
        }
        dump_json_atomic(path, dossier)
