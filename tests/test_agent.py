from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from open_research_discovery.agent import (
    AgentExecutionError,
    CodexRunner,
    strict_output_schema_errors,
)


def test_stage_schemas_avoid_unsupported_codex_keywords() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert "uniqueItems" not in value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for schema_path in (
        repository_root / "schemas" / "stages"
    ).glob("*.schema.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        walk(schema)
        assert strict_output_schema_errors(schema) == []


def test_codex_runner_rejects_non_strict_schema_before_exec(
    tmp_path: Path,
) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["required_value"],
                "properties": {
                    "required_value": {"type": "string"},
                    "optional_value": {"type": "string"},
                },
            }
        ),
        encoding="utf-8",
    )
    runner = CodexRunner(
        repository_root=tmp_path,
        executable="this-command-must-not-run",
        sandbox="read-only",
    )
    with pytest.raises(
        AgentExecutionError,
        match="every property must be required; missing optional_value",
    ):
        runner.run(
            role="triage",
            prompt="return structured output",
            schema_path=schema,
            output_path=tmp_path / "output.json",
            events_path=tmp_path / "events.jsonl",
        )


def test_strict_output_schema_requires_type_for_const() -> None:
    assert strict_output_schema_errors({"const": 7}) == [
        "$: const requires an explicit type"
    ]
    assert strict_output_schema_errors(
        {"type": "integer", "const": 7}
    ) == []


def test_codex_runner_uses_safe_structured_exec_boundary(tmp_path: Path) -> None:
    fake = tmp_path / "fake_codex.py"
    fake.write_text(
        """
import json
import pathlib
import sys

if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
prompt = sys.stdin.read()
output = pathlib.Path(sys.argv[sys.argv.index("--output-last-message") + 1])
output.write_text(json.dumps({"ok": True}), encoding="utf-8")
print(json.dumps({"type": "fake-event", "prompt_length": len(prompt)}))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean", "const": True}},
            }
        ),
        encoding="utf-8",
    )
    runner = CodexRunner(
        repository_root=tmp_path,
        executable=f"{sys.executable} {fake}",
        sandbox="read-only",
    )
    result = runner.run(
        role="smoke",
        prompt="return structured output",
        schema_path=schema,
        output_path=tmp_path / "output.json",
        events_path=tmp_path / "events.jsonl",
    )
    assert result.output == {"ok": True}
    command = result.metadata["command"]
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--json" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert result.metadata["codex_version"] == "fake-codex 1.0"
    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8"))
    assert event["type"] == "fake-event"


def test_codex_runner_enforces_timeout_on_stuck_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung codex whose descendants hold the pipes must die at the timeout.

    The fake codex spawns a grandchild that inherits the stdout/stderr pipe
    write ends, emits one partial event, then hangs. The runner must kill the
    whole process group, persist the partial events/stderr, and raise a
    timeout error without exceeding the timeout by more than a small grace.
    """
    fake = tmp_path / "fake_codex_hang.py"
    fake.write_text(
        """
import json
import os
import pathlib
import subprocess
import sys
import time

if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
prompt = sys.stdin.read()
pathlib.Path(os.environ["FAKE_CODEX_PGID_FILE"]).write_text(str(os.getpgrp()))
# Grandchild inherits the stdout/stderr pipes; it must not outlive the run.
subprocess.Popen(["sleep", "120"])
print(json.dumps({"type": "fake-event", "phase": "started"}), flush=True)
time.sleep(120)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    pgid_file = tmp_path / "pgid.txt"
    monkeypatch.setenv("FAKE_CODEX_PGID_FILE", str(pgid_file))
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean", "const": True}},
            }
        ),
        encoding="utf-8",
    )
    runner = CodexRunner(
        repository_root=tmp_path,
        executable=f"{sys.executable} {fake}",
        sandbox="read-only",
        timeout_seconds=2,
    )
    start = time.monotonic()
    try:
        with pytest.raises(AgentExecutionError, match="timed out after 2s"):
            runner.run(
                role="research",
                prompt="return structured output",
                schema_path=schema,
                output_path=tmp_path / "output.json",
                events_path=tmp_path / "events.jsonl",
            )
    finally:
        # Test cleanup in case the fix regresses and the group survives.
        if pgid_file.exists():
            try:
                os.killpg(int(pgid_file.read_text()), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    elapsed = time.monotonic() - start
    assert elapsed < 2 + 10
    assert pgid_file.exists()
    pgid = int(pgid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)
    events = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "started" in events
    assert (tmp_path / "events.stderr.log").is_file()


def test_codex_runner_networks_only_retrieval_roles(tmp_path: Path) -> None:
    fake = tmp_path / "fake_codex.py"
    fake.write_text(
        """
import json
import pathlib
import sys

if "--version" in sys.argv:
    print("fake-codex 1.0")
    raise SystemExit(0)
output = pathlib.Path(sys.argv[sys.argv.index("--output-last-message") + 1])
output.write_text(json.dumps({"ok": True}), encoding="utf-8")
print(json.dumps({"type": "fake-event"}))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean", "const": True}},
            }
        ),
        encoding="utf-8",
    )
    runner = CodexRunner(
        repository_root=tmp_path,
        executable=f"{sys.executable} {fake}",
        sandbox="read-only",
        networked_sandbox="workspace-write",
        network_access=True,
    )
    result = runner.run(
        role="research",
        prompt="search read-only evidence",
        schema_path=schema,
        output_path=tmp_path / "output.json",
        events_path=tmp_path / "events.jsonl",
    )
    command = result.metadata["command"]
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    config_index = command.index("--config")
    assert command[config_index + 1] == (
        "sandbox_workspace_write.network_access=true"
    )
    assert result.metadata["sandbox"] == "workspace-write"
    assert result.metadata["network_access"] is True
