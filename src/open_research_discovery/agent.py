from __future__ import annotations

import hashlib
import json
import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .common import dump_json


class AgentExecutionError(RuntimeError):
    """A headless Codex invocation failed or returned invalid structured output."""


class AgentOutputError(AgentExecutionError):
    """The invocation completed but produced unusable structured output.

    Raised for deterministic contract failures (an incompatible output
    schema, non-JSON output, or output failing schema validation). Unlike a
    failed invocation, replaying the call is not expected to repair these,
    so the campaign layer treats them as non-retryable.
    """


# Non-networked roles (canonicalization, triage, problem review, benchmark
# evaluation) receive a sanitized environment instead of inheriting the
# parent process env wholesale, so credentials such as LKM_ACCESS_KEY never
# reach a stage that has no business using them. Codex authenticates from
# files under ~/.codex (or CODEX_HOME), so no credential-bearing variable is
# needed; the whitelist is generous with inert system variables and strict
# with anything whose name even looks like a secret.
_SAFE_ENV_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "TERM",
        "TMPDIR",
        "TEMP",
        "TMP",
        "TZ",
        "CODEX_HOME",
        "SSH_AUTH_SOCK",
        "__CF_USER_TEXT_ENCODING",
        # Codex still calls the model API in read-only roles, so proxy and
        # CA-bundle configuration must survive sanitization.
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
    }
)
_SAFE_ENV_PREFIXES = ("LC_", "XDG_")
_SECRET_ENV_MARKERS = ("_KEY", "_TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def sanitized_environment(
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the whitelisted environment a non-networked role may inherit."""

    source = os.environ if environ is None else environ
    env: dict[str, str] = {}
    for name, value in source.items():
        upper = name.upper()
        if any(marker in upper for marker in _SECRET_ENV_MARKERS):
            continue
        if name in _SAFE_ENV_NAMES or upper.startswith(_SAFE_ENV_PREFIXES):
            env[name] = value
    return env


def strict_output_schema_errors(
    schema: Any, path: str = "$"
) -> list[str]:
    """Return Codex structured-output incompatibilities that JSON Schema allows."""

    if not isinstance(schema, dict):
        return []
    errors: list[str] = []
    if "const" in schema and "type" not in schema:
        errors.append(f"{path}: const requires an explicit type")
    # Conditional and containment keywords are silently ignored or rejected by
    # Codex structured output; the pipeline enforces such rules in Python
    # instead (see validation.py).
    for keyword in ("if", "then", "else", "contains"):
        if keyword in schema:
            errors.append(
                f"{path}: {keyword} is not supported by Codex structured output"
            )
    properties = schema.get("properties")
    if isinstance(properties, dict):
        required = schema.get("required")
        if not isinstance(required, list):
            errors.append(f"{path}: object properties require a required array")
            required_names: set[str] = set()
        else:
            required_names = {str(item) for item in required}
        missing = sorted(set(properties) - required_names)
        if missing:
            errors.append(
                f"{path}: every property must be required; missing "
                + ", ".join(missing)
            )
        for name, child in properties.items():
            errors.extend(
                strict_output_schema_errors(child, f"{path}.{name}")
            )
    items = schema.get("items")
    if isinstance(items, dict):
        errors.extend(strict_output_schema_errors(items, f"{path}[]"))
    for keyword in ("allOf", "anyOf", "oneOf"):
        variants = schema.get(keyword)
        if isinstance(variants, list):
            for index, child in enumerate(variants):
                errors.extend(
                    strict_output_schema_errors(
                        child, f"{path}.{keyword}[{index}]"
                    )
                )
    for keyword in ("$defs", "definitions"):
        definitions = schema.get(keyword)
        if isinstance(definitions, dict):
            for name, child in definitions.items():
                errors.extend(
                    strict_output_schema_errors(
                        child, f"{path}.{keyword}.{name}"
                    )
                )
    return errors


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class AgentRun:
    output: dict[str, Any]
    metadata: dict[str, Any]


def _execute_headless(
    *,
    role: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    stdin_text: str | None,
    timeout_seconds: int,
    events_path: Path,
) -> tuple[str, str, int]:
    """Run one headless agent CLI and persist its raw event stream.

    Shared by every backend so timeout and process-group semantics cannot
    drift between them. Popen + communicate() instead of subprocess.run(): on
    timeout the whole process group must be killed, not just the direct
    child. subprocess.run() kills only the direct child, so CLI descendants
    that inherited the stdout/stderr pipes survive as orphans (observed in
    real campaigns as codex workers stuck for hours past
    agents.timeout_seconds). start_new_session puts the child in its own
    process group so killpg can reach every descendant. Networked roles keep
    the parent environment (discovery/research may need LKM credentials for
    gaia); every other role gets a sanitized whitelist so secrets never reach
    a stage that cannot use them.
    """
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(
            input=stdin_text, timeout=timeout_seconds
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
            # A descendant escaped the process group and still holds the
            # pipes; abandon them so the runner still returns promptly.
            for stream in (
                process.stdout,
                process.stderr,
                process.stdin,
            ):
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
            f"{role} timed out after {timeout_seconds}s; "
            f"killed process group; see {stderr_path}"
        )
    return stdout, stderr, process.returncode


def _validate_agent_output(
    *, role: str, schema: Any, output: Any, output_path: Path
) -> None:
    """Enforce the output contract shared by every backend.

    Raises AgentOutputError on failure, which the campaign layer treats as
    non-retryable: replaying the call is not expected to repair output that
    fails deterministic validation.
    """
    errors = sorted(
        Draft202012Validator(schema).iter_errors(output),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        dump_json(output_path.with_suffix(".invalid.json"), output)
        details = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: "
            f"{error.message}"
            for error in errors[:8]
        )
        raise AgentOutputError(f"{role} output failed schema validation: {details}")


def _last_assistant_content(stdout: str) -> str:
    """Return the final non-empty assistant message from stream-json output.

    Kimi's ``--output-format stream-json`` emits one JSON object per line;
    tool use produces several assistant and tool lines, and a trailing meta
    line closes the stream. The last non-empty assistant content carries the
    structured reply.
    """
    content = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("role") != "assistant":
            continue
        text = event.get("content")
        if isinstance(text, list):
            # Defensive: tolerate chat-style content blocks.
            text = "".join(
                str(block.get("text", ""))
                for block in text
                if isinstance(block, dict)
            )
        if isinstance(text, str) and text.strip():
            content = text
    return content


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first parseable JSON object from an assistant reply.

    raw_decode returns the longest parseable prefix starting at each
    candidate opening brace, so prose or markdown fences around the object
    are tolerated.
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    raise ValueError("no parseable JSON object in assistant reply")


class _HeadlessCliRunner:
    """Shared machinery for headless agent CLI backends."""

    NETWORKED_ROLES = frozenset({"discovery", "research"})

    def __init__(
        self,
        *,
        repository_root: Path,
        executable: str,
        model: str = "",
        timeout_seconds: int = 3600,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.executable = executable
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._version: str | None = None

    def version(self) -> str:
        if self._version is None:
            command = [*shlex.split(self.executable), "--version"]
            completed = subprocess.run(
                command,
                cwd=self.repository_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            rendered = (completed.stdout or completed.stderr).strip()
            self._version = rendered or f"exit={completed.returncode}"
        return self._version

    def _environment(self, role: str) -> dict[str, str] | None:
        """Return the environment a role may inherit (None means parent env)."""
        if role in self.NETWORKED_ROLES:
            return None
        return sanitized_environment()


class CodexRunner(_HeadlessCliRunner):
    """Run one coarse-grained, schema-constrained Codex research stage."""

    def __init__(
        self,
        *,
        repository_root: Path,
        executable: str = "codex",
        model: str = "",
        sandbox: str = "read-only",
        networked_sandbox: str = "workspace-write",
        network_access: bool = True,
        timeout_seconds: int = 3600,
    ) -> None:
        super().__init__(
            repository_root=repository_root,
            executable=executable,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("Codex sandbox must be read-only or workspace-write")
        if networked_sandbox not in {"read-only", "workspace-write"}:
            raise ValueError(
                "Codex networked sandbox must be read-only or workspace-write"
            )
        self.sandbox = sandbox
        self.networked_sandbox = networked_sandbox
        self.network_access = network_access

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
        contract_validator: Any | None = None,
    ) -> AgentRun:
        # contract_validator is accepted for interface uniformity with
        # KimiRunner; Codex enforces the schema at the API level, so no
        # validation-feedback round is needed here.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        strict_errors = strict_output_schema_errors(schema)
        if strict_errors:
            raise AgentOutputError(
                "output schema is incompatible with Codex structured output: "
                + "; ".join(strict_errors)
            )
        networked = role in self.NETWORKED_ROLES
        effective_sandbox = (
            self.networked_sandbox if networked else self.sandbox
        )
        command = [
            *shlex.split(self.executable),
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--json",
            "--color",
            "never",
            "--sandbox",
            effective_sandbox,
            "--output-schema",
            str(schema_path.resolve()),
            "--output-last-message",
            str(output_path.resolve()),
            "--cd",
            str(self.repository_root),
        ]
        if (
            networked
            and self.network_access
            and effective_sandbox == "workspace-write"
        ):
            command.extend(
                ["--config", "sandbox_workspace_write.network_access=true"]
            )
        if self.model:
            command.extend(["--model", self.model])
        command.append("-")
        # Cache misses and retries intentionally reuse output_path. Remove any
        # prior artifact so the existence check below proves that this exact
        # invocation, rather than an earlier one, produced the output.
        output_path.unlink(missing_ok=True)
        _stdout, _stderr, returncode = _execute_headless(
            role=role,
            command=command,
            cwd=self.repository_root,
            env=None if networked else sanitized_environment(),
            stdin_text=prompt,
            timeout_seconds=self.timeout_seconds,
            events_path=events_path,
        )
        stderr_path = events_path.with_suffix(".stderr.log")
        metadata = {
            "role": role,
            "command": command,
            "codex_version": self.version(),
            "model": self.model or "configured-default",
            "sandbox": effective_sandbox,
            "network_access": bool(networked and self.network_access),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "schema": str(schema_path),
            "schema_sha256": file_sha256(schema_path),
            "events": str(events_path),
            "stderr": str(stderr_path),
            "exit_code": returncode,
        }
        if returncode != 0:
            raise AgentExecutionError(
                f"{role} failed with exit {returncode}; "
                f"see {stderr_path}"
            )
        if not output_path.is_file():
            raise AgentExecutionError(
                f"{role} did not write structured output to {output_path}"
            )
        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise AgentOutputError(
                f"{role} output is not valid JSON: {error}"
            ) from error
        _validate_agent_output(
            role=role, schema=schema, output=output, output_path=output_path
        )
        return AgentRun(output=output, metadata=metadata)



# Kimi has no --output-schema structured-output mode, so the schema constraint
# is carried by this prompt instruction and enforced deterministically after
# the call (parse + Draft202012Validator).
_KIMI_SCHEMA_INSTRUCTION = (
    "\n\nYour final reply must be exactly one JSON object that conforms to "
    "the following JSON Schema. Do not include any prose, explanation, or "
    "markdown code fences before or after it; reply with the JSON object and "
    "nothing else.\n\nJSON Schema:\n"
)

# Prompt-only structured output (kimi) occasionally misses a field or a
# cross-field rule that an API-enforced schema (codex) cannot. One feedback
# round with the concrete validator error repairs most of these; the campaign
# layer's "contract failures are not retried" policy still applies to the
# corrected result.
_KIMI_VALIDATION_FEEDBACK = (
    "\n\nYour previous reply failed validation with this error:\n"
    "{error}\n"
    "Return one corrected JSON object that fixes exactly this problem. "
    "Reply with the JSON object and nothing else.\n"
)


class KimiRunner(_HeadlessCliRunner):
    """Run one coarse-grained, schema-constrained stage via Kimi Code CLI.

    Headless mode is ``kimi -p <prompt> --output-format stream-json``: stdout
    carries one JSON object per line and the last non-empty assistant message
    is the reply. Unlike Codex, kimi offers no ``--output-schema`` enforcement
    and no sandbox flag, so the output contract is enforced by the prompt
    instruction plus deterministic parsing and schema validation after the
    call, and role isolation relies on environment sanitization alone (the
    ``sandbox`` concept does not exist here and is not accepted). Contract
    failures raise AgentOutputError and are not retried, exactly like the
    Codex backend.
    """

    def __init__(
        self,
        *,
        repository_root: Path,
        executable: str = "kimi",
        model: str = "",
        timeout_seconds: int = 3600,
    ) -> None:
        super().__init__(
            repository_root=repository_root,
            executable=executable,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
        contract_validator: Any | None = None,
    ) -> AgentRun:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        # strict_output_schema_errors encodes Codex structured-output limits
        # (if/then, required coverage); they do not apply to a backend that
        # validates output after the fact.
        schema_instruction = (
            _KIMI_SCHEMA_INSTRUCTION + json.dumps(schema, indent=2)
        )
        executable_parts = shlex.split(self.executable)
        feedback = ""
        last_error: Exception | None = None
        for attempt in range(2):
            full_prompt = prompt + schema_instruction + feedback
            command = [
                *executable_parts,
                "-p",
                full_prompt,
                "--output-format",
                "stream-json",
            ]
            if self.model:
                command.extend(["-m", self.model])
            # The prompt rides in argv for kimi; keep it out of persisted
            # metadata the same way the Codex backend keeps its stdin prompt
            # out of the logged command.
            logged_command = [
                *executable_parts,
                "-p",
                "<prompt>",
                "--output-format",
                "stream-json",
                *(["-m", self.model] if self.model else []),
            ]
            # Cache misses and retries intentionally reuse output_path; it is
            # written only by this invocation, after parsing succeeds.
            output_path.unlink(missing_ok=True)
            stdout, _stderr, returncode = _execute_headless(
                role=role,
                command=command,
                cwd=self.repository_root,
                env=self._environment(role),
                stdin_text=None,
                timeout_seconds=self.timeout_seconds,
                events_path=events_path,
            )
            stderr_path = events_path.with_suffix(".stderr.log")
            metadata = {
                "role": role,
                "backend": "kimi",
                "command": logged_command,
                "kimi_version": self.version(),
                "model": self.model or "configured-default",
                # Kimi exposes no sandbox or network toggle; None records that
                # isolation is not enforceable beyond environment sanitization.
                "sandbox": None,
                "network_access": None,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "schema": str(schema_path),
                "schema_sha256": file_sha256(schema_path),
                "events": str(events_path),
                "stderr": str(stderr_path),
                "exit_code": returncode,
                "validation_feedback_attempt": attempt,
            }
            if returncode != 0:
                raise AgentExecutionError(
                    f"{role} failed with exit {returncode}; "
                    f"see {stderr_path}"
                )
            reply = _last_assistant_content(stdout)
            try:
                output = _extract_json_object(reply)
            except ValueError as error:
                last_error = AgentOutputError(
                    f"{role} reply contained no parseable JSON object"
                )
                last_error.__cause__ = error
            else:
                try:
                    _validate_agent_output(
                        role=role,
                        schema=schema,
                        output=output,
                        output_path=output_path,
                    )
                    if contract_validator is not None:
                        contract_validator(output)
                except RuntimeError as error:
                    # AgentOutputError from the schema check or CampaignError
                    # from the contract validator (defined in campaign.py;
                    # imported lazily nowhere to avoid a circular import).
                    last_error = error
                else:
                    dump_json(output_path, output)
                    return AgentRun(output=output, metadata=metadata)
            feedback = _KIMI_VALIDATION_FEEDBACK.format(error=last_error)
        raise last_error
