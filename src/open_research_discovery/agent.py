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

from .common import dump_json
from .validation import schema_error_lines


class AgentExecutionError(RuntimeError):
    """A headless Codex invocation failed or returned invalid structured output."""


class AgentOutputError(AgentExecutionError):
    """The invocation completed but produced unusable structured output.

    Raised for deterministic contract failures (an incompatible output
    schema, non-JSON output, or output failing schema validation). Unlike a
    failed invocation, replaying the call is not expected to repair these,
    so the campaign layer treats them as non-retryable.
    """


# Non-networked roles (selection, problem review) receive a sanitized
# environment instead of inheriting the
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
    errors = schema_error_lines(output, schema, limit=8)
    if errors:
        dump_json(output_path.with_suffix(".invalid.json"), output)
        raise AgentOutputError(
            f"{role} output failed schema validation: {'; '.join(errors)}"
        )


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

    NETWORKED_ROLES = frozenset({"discovery", "research", "problem-reviewer"})

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
        cwd: Path | None = None,
    ) -> AgentRun:
        # contract_validator is accepted for interface uniformity with
        # KimiRunner; Codex enforces the schema at the API level, so no
        # validation-feedback round is needed here.
        # cwd pins the agent's working directory (the directory holding the
        # stage's memory.md); it defaults to the repository root.
        workdir = (cwd or self.repository_root).resolve()
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
            str(workdir),
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
            cwd=workdir,
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



# Prompt-only backends (kimi, claude) have no --output-schema structured-output
# mode, so the schema constraint is carried by this prompt instruction and
# enforced deterministically after the call (parse + Draft202012Validator).
_SCHEMA_INSTRUCTION = (
    "\n\nYour final reply must be exactly one JSON object that conforms to "
    "the following JSON Schema. Do not include any prose, explanation, or "
    "markdown code fences before or after it; reply with the JSON object and "
    "nothing else.\n\nJSON Schema:\n"
)

# Prompt-only structured output occasionally misses a field or a cross-field
# rule that an API-enforced schema (codex) cannot. One feedback round with the
# concrete validator error repairs most of these; the campaign layer's
# "contract failures are not retried" policy still applies to the corrected
# result.
_VALIDATION_FEEDBACK = (
    "\n\nYour previous reply failed validation with this error:\n"
    "{error}\n"
    "Return one corrected JSON object that fixes exactly this problem. "
    "Reply with the JSON object and nothing else.\n"
)


class _PromptCliRunner(_HeadlessCliRunner):
    """Shared ``run`` for prompt-only CLI backends (Kimi Code, Claude Code).

    Unlike Codex, these CLIs offer no ``--output-schema`` enforcement and no
    sandbox flag, so the output contract is carried by the prompt instruction
    and enforced deterministically after the call (parse +
    Draft202012Validator), and role isolation relies on environment
    sanitization alone. Prompt-only structured output occasionally misses a
    field or a cross-field rule, so the call gets exactly one validation
    feedback round with the concrete validator error; the campaign layer's
    "contract failures are not retried" policy applies to the result.
    Contract failures raise AgentOutputError, exactly like the Codex backend.
    """

    BACKEND: str = ""
    OUTPUT_FORMAT: str = ""
    MODEL_FLAG: str = ""

    def __init__(
        self,
        *,
        repository_root: Path,
        executable: str,
        model: str = "",
        timeout_seconds: int = 3600,
    ) -> None:
        super().__init__(
            repository_root=repository_root,
            executable=executable,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    def _reply(self, stdout: str) -> str:
        """Extract the assistant's final reply from this backend's stdout."""
        raise NotImplementedError

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
        contract_validator: Any | None = None,
        cwd: Path | None = None,
    ) -> AgentRun:
        # cwd pins the agent's working directory (the directory holding the
        # stage's memory.md); it defaults to the repository root.
        workdir = (cwd or self.repository_root).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        # strict_output_schema_errors encodes Codex structured-output limits
        # (if/then, required coverage); they do not apply to a backend that
        # validates output after the fact.
        schema_instruction = (
            _SCHEMA_INSTRUCTION + json.dumps(schema, indent=2)
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
                self.OUTPUT_FORMAT,
            ]
            if self.model:
                command.extend([self.MODEL_FLAG, self.model])
            # The prompt rides in argv for these CLIs; keep it out of persisted
            # metadata the same way the Codex backend keeps its stdin prompt
            # out of the logged command.
            logged_command = [
                *executable_parts,
                "-p",
                "<prompt>",
                "--output-format",
                self.OUTPUT_FORMAT,
                *([self.MODEL_FLAG, self.model] if self.model else []),
            ]
            # Cache misses and retries intentionally reuse output_path; it is
            # written only by this invocation, after parsing succeeds.
            output_path.unlink(missing_ok=True)
            stdout, _stderr, returncode = _execute_headless(
                role=role,
                command=command,
                cwd=workdir,
                env=self._environment(role),
                stdin_text=None,
                timeout_seconds=self.timeout_seconds,
                events_path=events_path,
            )
            stderr_path = events_path.with_suffix(".stderr.log")
            metadata = {
                "role": role,
                "backend": self.BACKEND,
                "command": logged_command,
                f"{self.BACKEND}_version": self.version(),
                "model": self.model or "configured-default",
                # These CLIs expose no sandbox or network toggle; None records
                # that isolation is not enforceable beyond environment
                # sanitization.
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
            reply = self._reply(stdout)
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
            feedback = _VALIDATION_FEEDBACK.format(error=last_error)
        raise last_error


class KimiRunner(_PromptCliRunner):
    """Run one coarse-grained, schema-constrained stage via Kimi Code CLI.

    Headless mode is ``kimi -p <prompt> --output-format stream-json``: stdout
    carries one JSON object per line and the last non-empty assistant message
    is the reply.
    """

    BACKEND = "kimi"
    OUTPUT_FORMAT = "stream-json"
    MODEL_FLAG = "-m"

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

    def _reply(self, stdout: str) -> str:
        return _last_assistant_content(stdout)


class ClaudeRunner(_PromptCliRunner):
    """Run one coarse-grained, schema-constrained stage via Claude Code CLI.

    Headless mode is ``claude -p <prompt> --output-format json``: stdout
    carries a single JSON object whose ``result`` field is the assistant's
    final reply.
    """

    BACKEND = "claude"
    OUTPUT_FORMAT = "json"
    MODEL_FLAG = "--model"

    def __init__(
        self,
        *,
        repository_root: Path,
        executable: str = "claude",
        model: str = "",
        timeout_seconds: int = 3600,
    ) -> None:
        super().__init__(
            repository_root=repository_root,
            executable=executable,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    def _environment(self, role: str) -> dict[str, str] | None:
        """Return the environment for a Claude CLI invocation.

        Claude authenticates via ``ANTHROPIC_AUTH_TOKEN`` and reads the API
        base URL and model mappings from ``ANTHROPIC_*`` variables.  The
        default sanitizer strips ``*_TOKEN`` and anything not on the safe
        list, which would leave the CLI unable to authenticate even for
        non-networked roles.  Unlike Codex (which keeps credentials in
        ``CODEX_HOME``) and Kimi (which keeps them in ``~/.kimi/``), Claude
        has no file-based fallback in a typical proxy setup, so the
        ``ANTHROPIC_*`` block must survive sanitization.
        """
        env = super()._environment(role)
        if env is not None:
            for key, value in os.environ.items():
                if key.startswith("ANTHROPIC_"):
                    env[key] = value
        return env

    def _reply(self, stdout: str) -> str:
        # Claude's --output-format json emits a single JSON envelope with
        # the assistant's reply in the "result" field.
        try:
            envelope = json.loads(stdout)
            if isinstance(envelope, dict):
                return str(envelope.get("result", ""))
        except json.JSONDecodeError:
            pass
        return ""


class TraeRunner(_HeadlessCliRunner):
    """Run one coarse-grained, schema-constrained stage via trae-cli.

    Supports both trae CLI generations through one code path:

    * internal edition (``traecli exec`` from traex_install.sh): Claude
      Code-style headless mode. ``--output-mode final-message-only`` yields
      the clean final reply on stdout and the model comes from the logged-in
      Trae account, so no local API key or bridge is involved.
    * open-source trae-agent (``trae-cli run``): rich stdout only; the reply
      is recovered from the ``--trajectory-file`` JSON.

    The output contract is file-based in both cases: the prompt instructs
    the agent to write the JSON object to ``output_path`` (absolute path)
    before finishing. Stdout final-message (internal edition) and the
    trajectory JSON are fallbacks, in that order.
    """

    BACKEND = "trae"
    _CONFIG_FLAG = "--config-file"
    _WORKDIR_FLAG = "-w"
    _SUBCOMMAND_RUN = "run"
    _SUBCOMMAND_EXEC = "exec"

    def __init__(
        self,
        *,
        repository_root: Path,
        executable: str = "trae-cli",
        config_file: str = "",
        model: str = "",
        timeout_seconds: int = 3600,
    ) -> None:
        super().__init__(
            repository_root=repository_root,
            executable=executable,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        self.config_file = config_file

    def _probe_subcommand(self) -> str:
        """internal edition speaks ``exec``; open-source trae-agent ``run``."""
        cached = getattr(self, "_subcommand", None)
        if cached is not None:
            return cached
        executable_parts = shlex.split(self.executable)
        try:
            probe = subprocess.run(
                [*executable_parts, "--help"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            rendered = (probe.stdout or "") + (probe.stderr or "")
        except (OSError, subprocess.SubprocessError):
            rendered = ""
        subcommand = (
            self._SUBCOMMAND_EXEC
            if "non-interactively" in rendered
            else self._SUBCOMMAND_RUN
        )
        self._subcommand = subcommand
        return subcommand

    def _base_command(self) -> list[str]:
        command = [
            *shlex.split(self.executable),
            self._probe_subcommand(),
        ]
        if self._probe_subcommand() == self._SUBCOMMAND_EXEC:
            # Claude Code-style headless flags (internal edition).
            command.extend(
                ["--skip-git-repo-check", "--output-mode", "final-message-only"]
            )
        if self.config_file:
            command.extend([self._CONFIG_FLAG, self.config_file])
        if self.model:
            command.extend(["-m", self.model])
        return command

    def _reply_from_trajectory(self, trajectory_path: Path) -> str:
        try:
            payload = json.loads(
                trajectory_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return ""
        interactions = payload.get("llm_interactions")
        if isinstance(interactions, list):
            for interaction in reversed(interactions):
                response = (
                    interaction.get("response")
                    if isinstance(interaction, dict)
                    else None
                )
                if isinstance(response, dict):
                    content = response.get("content")
                    if isinstance(content, str) and content.strip():
                        return content
                    tool_calls = response.get("tool_calls") or []
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        arguments = call.get("arguments")
                        if isinstance(arguments, dict) and arguments:
                            return json.dumps(arguments, ensure_ascii=False)
        return ""

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
        contract_validator: Any | None = None,
        cwd: Path | None = None,
    ) -> AgentRun:
        workdir = (cwd or self.repository_root).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema_instruction = (
            _SCHEMA_INSTRUCTION + json.dumps(schema, indent=2)
        )
        # The workspace-write sandbox makes only the working directory tree
        # writable; an absolute path outside it (ORD's run-dir layout) would
        # be refused. Contract: deliver to a relative file in the cwd, then
        # this runner relocates it to output_path after validation.
        deliverable_path = workdir / output_path.name
        file_contract = (
            "\n\nDelivery contract: write the JSON object to the file "
            f"{output_path.name} in your current working directory "
            "(relative path, UTF-8, no markdown fences, no extra keys). "
            "Do not write anywhere else. After the file is written and "
            "verified, finish immediately. The file, not your chat reply, "
            "is the deliverable."
        )
        executable_parts = shlex.split(self.executable)
        feedback = ""
        last_error: Exception | None = None
        for attempt in range(2):
            full_prompt = prompt + schema_instruction + file_contract + feedback
            # Trae's CLI takes the task as the final positional argument;
            # --trajectory-file pins where the machine-readable record lands
            # so the reply can be recovered without parsing rich stdout.
            trajectory_path = (
                events_path.parent
                / f"{events_path.name}.attempt{attempt}.trajectory.json"
            )
            subcommand = self._probe_subcommand()
            command = [*self._base_command()]
            if subcommand == self._SUBCOMMAND_EXEC:
                # traecli exec runs in the caller's cwd; cd is handled by
                # _execute_headless. workspace-write lets the agent honor
                # the file-delivery contract.
                command.extend(["-s", "workspace-write"])
            else:
                command.extend(
                    [
                        self._WORKDIR_FLAG,
                        str(workdir),
                        "--trajectory-file",
                        str(trajectory_path),
                    ]
                )
            command.append(full_prompt)
            logged_command = [
                *executable_parts,
                "run",
                *([self._CONFIG_FLAG, self.config_file] if self.config_file else []),
                *(["-m", self.model] if self.model else []),
                self._WORKDIR_FLAG,
                "<workdir>",
                "--trajectory-file",
                "<trajectory>",
                "<prompt>",
            ]
            output_path.unlink(missing_ok=True)
            stdout, _stderr, returncode = _execute_headless(
                role=role,
                command=command,
                cwd=workdir,
                env=self._environment(role),
                stdin_text=None,
                timeout_seconds=self.timeout_seconds,
                events_path=events_path,
            )
            stderr_path = events_path.with_suffix(".stderr.log")
            metadata = {
                "role": role,
                "backend": self.BACKEND,
                "command": logged_command,
                f"{self.BACKEND}_version": self.version(),
                "model": self.model or "configured-default",
                "sandbox": None,
                "network_access": None,
                "prompt_sha256": hashlib.sha256(
                    prompt.encode("utf-8")
                ).hexdigest(),
                "schema": str(schema_path),
                "schema_sha256": file_sha256(schema_path),
                "events": str(events_path),
                "stderr": str(stderr_path),
                "exit_code": returncode,
                "validation_feedback_attempt": attempt,
                "trae_subcommand": subcommand,
                "trajectory": str(trajectory_path),
            }
            if returncode != 0:
                raise AgentExecutionError(
                    f"{role} failed with exit {returncode}; "
                    f"see {stderr_path}"
                )
            # The file contract is primary; stdout final-message (internal
            # edition) and the trajectory JSON are fallbacks, in that order.
            reply = stdout.strip() if subcommand == self._SUBCOMMAND_EXEC else ""
            if deliverable_path.is_file():
                # Relocate the sandbox deliverable to the canonical path.
                output_path.parent.mkdir(parents=True, exist_ok=True)
                deliverable_path.replace(output_path)
            if output_path.is_file():
                try:
                    output = json.loads(
                        output_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError) as error:
                    last_error = AgentOutputError(
                        f"{role} wrote unparseable JSON to {output_path}"
                    )
                    last_error.__cause__ = error
                    feedback = _VALIDATION_FEEDBACK.format(error=last_error)
                    continue
            else:
                if not reply:
                    reply = self._reply_from_trajectory(trajectory_path)
                try:
                    output = _extract_json_object(reply)
                except ValueError as error:
                    last_error = AgentOutputError(
                        f"{role} produced no deliverable file and the "
                        f"trajectory reply contained no parseable JSON object"
                    )
                    last_error.__cause__ = error
                    feedback = _VALIDATION_FEEDBACK.format(error=last_error)
                    continue
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
                last_error = error
            else:
                dump_json(output_path, output)
                return AgentRun(output=output, metadata=metadata)
            feedback = _VALIDATION_FEEDBACK.format(error=last_error)
        raise last_error
