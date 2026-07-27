from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .common import dump_json


class AgentExecutionError(RuntimeError):
    """A headless Codex invocation failed or returned invalid structured output."""


def strict_output_schema_errors(
    schema: Any, path: str = "$"
) -> list[str]:
    """Return Codex structured-output incompatibilities that JSON Schema allows."""

    if not isinstance(schema, dict):
        return []
    errors: list[str] = []
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


class CodexRunner:
    """Run one coarse-grained, schema-constrained Codex research stage."""

    NETWORKED_ROLES = frozenset({"discovery", "research"})

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
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("Codex sandbox must be read-only or workspace-write")
        if networked_sandbox not in {"read-only", "workspace-write"}:
            raise ValueError(
                "Codex networked sandbox must be read-only or workspace-write"
            )
        self.repository_root = repository_root.resolve()
        self.executable = executable
        self.model = model
        self.sandbox = sandbox
        self.networked_sandbox = networked_sandbox
        self.network_access = network_access
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

    def run(
        self,
        *,
        role: str,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        events_path: Path,
    ) -> AgentRun:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        strict_errors = strict_output_schema_errors(schema)
        if strict_errors:
            raise AgentExecutionError(
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
        completed = subprocess.run(
            command,
            cwd=self.repository_root,
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            timeout=self.timeout_seconds,
        )
        events_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path = events_path.with_suffix(".stderr.log")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
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
            "exit_code": completed.returncode,
        }
        if completed.returncode != 0:
            raise AgentExecutionError(
                f"{role} failed with exit {completed.returncode}; "
                f"see {stderr_path}"
            )
        if not output_path.is_file():
            raise AgentExecutionError(
                f"{role} did not write structured output to {output_path}"
            )
        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise AgentExecutionError(
                f"{role} output is not valid JSON: {error}"
            ) from error
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
            raise AgentExecutionError(f"{role} output failed schema validation: {details}")
        return AgentRun(output=output, metadata=metadata)
