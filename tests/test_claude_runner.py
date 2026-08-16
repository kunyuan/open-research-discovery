from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from open_research_discovery.agent import (
    AgentExecutionError,
    AgentOutputError,
    ClaudeRunner,
    strict_output_schema_errors,
)


def _write_schema(tmp_path: Path, schema: dict | None = None) -> Path:
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps(
            schema
            or {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean", "const": True}},
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_fake_claude(tmp_path: Path, body: str) -> str:
    """Write a fake claude CLI script handling --version plus the given body.

    The body should set ``result`` (a string).  The wrapper emits a JSON
    envelope matching ``claude -p --output-format json``.
    """
    fake = tmp_path / "fake_claude.py"
    fake.write_text(
        """
import sys

if "--version" in sys.argv:
    print("fake-claude 1.0")
    raise SystemExit(0)

result = ""
"""
        + body
        + """
import json as _json
print(_json.dumps({"type": "result", "subtype": "success", "result": result}))
""",
        encoding="utf-8",
    )
    return f"{sys.executable} {fake}"


def _run_kwargs(tmp_path: Path, schema_path: Path, role: str = "triage") -> dict:
    return {
        "role": role,
        "prompt": "return structured output",
        "schema_path": schema_path,
        "output_path": tmp_path / "output.json",
        "events_path": tmp_path / "events.json",
    }


def test_claude_runner_builds_expected_command(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    executable = _write_fake_claude(
        tmp_path,
        f"""
import json
import os
import pathlib

prompt = sys.argv[sys.argv.index("-p") + 1]
pathlib.Path({str(capture)!r}).write_text(
    json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "prompt": prompt}}),
    encoding="utf-8",
)
result = json.dumps({{"ok": True}})
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path,
        executable=executable,
        model="claude-sonnet-5",
        timeout_seconds=30,
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))

    assert result.output == {"ok": True}
    captured = json.loads(capture.read_text(encoding="utf-8"))
    argv = captured["argv"]
    assert argv[0] == "-p"
    assert argv[2:] == [
        "--output-format",
        "json",
        "--model",
        "claude-sonnet-5",
    ]
    assert captured["cwd"] == str(tmp_path.resolve())
    prompt = captured["prompt"]
    assert prompt.startswith("return structured output")
    assert "exactly one JSON object" in prompt
    assert "JSON Schema:" in prompt
    assert json.loads(schema_path.read_text(encoding="utf-8"))["properties"][
        "ok"
    ]["const"] is True
    assert '"const": true' in prompt
    assert result.metadata["backend"] == "claude"
    logged = result.metadata["command"]
    assert "<prompt>" in logged
    assert not any("return structured output" in item for item in logged)
    assert result.metadata["claude_version"] == "fake-claude 1.0"


def test_claude_runner_omits_model_flag_without_model(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    executable = _write_fake_claude(
        tmp_path,
        f"""
import json
import pathlib

pathlib.Path({str(capture)!r}).write_text(
    json.dumps(sys.argv[1:]), encoding="utf-8"
)
result = json.dumps({{"ok": True}})
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))

    assert result.output == {"ok": True}
    argv = json.loads(capture.read_text(encoding="utf-8"))
    assert "--model" not in argv
    assert result.metadata["model"] == "configured-default"


def test_claude_runner_extracts_json_from_result_field(tmp_path: Path) -> None:
    executable = _write_fake_claude(
        tmp_path,
        """
import json

result = json.dumps({"ok": True})
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))
    assert result.output == {"ok": True}


def test_claude_runner_extracts_json_from_prose_and_fences(tmp_path: Path) -> None:
    executable = _write_fake_claude(
        tmp_path,
        """
result = "Sure, here is the result:\\n```json\\n{\\"ok\\": true}\\n```\\nDone."
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))
    assert result.output == {"ok": True}


def test_claude_runner_raises_contract_error_without_json(tmp_path: Path) -> None:
    executable = _write_fake_claude(
        tmp_path,
        """
result = "I could not answer."
""",
    )
    schema_path = _write_schema(tmp_path)
    output_path = tmp_path / "output.json"
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    with pytest.raises(AgentOutputError, match="no parseable JSON object"):
        runner.run(**_run_kwargs(tmp_path, schema_path))
    assert not output_path.exists()


def test_claude_runner_schema_validation_failure_is_contract_error(
    tmp_path: Path,
) -> None:
    executable = _write_fake_claude(
        tmp_path,
        """
import json

result = json.dumps({"ok": False})
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    with pytest.raises(AgentOutputError, match="failed schema validation"):
        runner.run(**_run_kwargs(tmp_path, schema_path))
    invalid = tmp_path / "output.invalid.json"
    assert json.loads(invalid.read_text(encoding="utf-8")) == {"ok": False}


def test_claude_runner_skips_codex_strict_schema_check(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "note": {"type": "string"},
        },
        "if": {"properties": {"ok": {"const": True}}},
        "then": {"required": ["note"]},
    }
    assert strict_output_schema_errors(schema) != []
    schema_path = _write_schema(tmp_path, schema)
    executable = _write_fake_claude(
        tmp_path,
        """
import json

result = json.dumps({"ok": True, "note": "present"})
""",
    )
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))
    assert result.output == {"ok": True, "note": "present"}


def test_claude_runner_nonzero_exit_is_execution_error(tmp_path: Path) -> None:
    executable = _write_fake_claude(
        tmp_path,
        """
import sys

print("boom", file=sys.stderr)
raise SystemExit(3)
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    with pytest.raises(AgentExecutionError, match="failed with exit 3") as info:
        runner.run(**_run_kwargs(tmp_path, schema_path))
    assert type(info.value) is AgentExecutionError


def test_claude_runner_sanitizes_environment_by_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_RUNNER_TEST_SECRET_KEY", "present")
    capture = tmp_path / "capture.json"
    executable = _write_fake_claude(
        tmp_path,
        f"""
import json
import os
import pathlib

pathlib.Path({str(capture)!r}).write_text(
    json.dumps("CLAUDE_RUNNER_TEST_SECRET_KEY" in os.environ),
    encoding="utf-8",
)
result = json.dumps({{"ok": True}})
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    runner.run(**_run_kwargs(tmp_path, schema_path, role="triage"))
    assert json.loads(capture.read_text(encoding="utf-8")) is False

    capture.unlink()
    runner.run(**_run_kwargs(tmp_path, schema_path, role="discovery"))
    assert json.loads(capture.read_text(encoding="utf-8")) is True


def test_claude_runner_preserves_anthropic_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ANTHROPIC_* vars must survive sanitization for CLI authentication."""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:4141")
    monkeypatch.setenv("ANTHROPIC_MODEL", "seed[1m]")
    monkeypatch.setenv("UNRELATED_SECRET", "should-not-pass")
    capture = tmp_path / "capture.json"
    executable = _write_fake_claude(
        tmp_path,
        f"""
import json
import os
import pathlib

pathlib.Path({str(capture)!r}).write_text(
    json.dumps({{
        "auth_token": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        "base_url": os.environ.get("ANTHROPIC_BASE_URL", ""),
        "model": os.environ.get("ANTHROPIC_MODEL", ""),
        "unrelated_secret": os.environ.get("UNRELATED_SECRET", ""),
    }}),
    encoding="utf-8",
)
result = json.dumps({{"ok": True}})
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    runner.run(**_run_kwargs(tmp_path, schema_path, role="triage"))
    captured = json.loads(capture.read_text(encoding="utf-8"))
    assert captured["auth_token"] == "test-token"
    assert captured["base_url"] == "http://localhost:4141"
    assert captured["model"] == "seed[1m]"
    assert captured["unrelated_secret"] == ""


def _minimal_config(tmp_path: Path, agents: dict) -> dict:
    return {
        "schema_version": 2,
        "name": "claude-backend-smoke",
        "topics": [
            {
                "id": "alpha",
                "title": "Alpha",
                "query": "Find open problems in alpha.",
                "sources": ["lkm_open_questions"],
                "seed_papers": [],
                "seed_references": [],
            }
        ],
        "limits": {
            "papers_per_domain": 1,
            "questions_per_domain": 1,
            "lkm_timeout_seconds": 30,
        },
        "agents": agents,
        "outputs": {
            "runs_root": str(tmp_path / "runs"),
            "problem_root": str(tmp_path / "problems"),
            "pool_root": "",
        },
    }


def test_campaign_selects_claude_runner_from_config(tmp_path: Path) -> None:
    from open_research_discovery.campaign import CampaignPipeline

    executable = _write_fake_claude(tmp_path, 'result = "{}"')
    config = _minimal_config(
        tmp_path,
        {
            "model": "",
            "backend": "claude",
            "claude_executable": executable,
            "codex_executable": "codex",
            "sandbox": "read-only",
            "timeout_seconds": 60,
        },
    )
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="claude-backend-smoke",
    )
    assert isinstance(pipeline.agent_runner, ClaudeRunner)
    assert pipeline.tool_versions["claude"] == "fake-claude 1.0"


def test_claude_runner_validation_feedback_repairs_output(tmp_path: Path) -> None:
    counter = tmp_path / "calls.txt"
    capture = tmp_path / "prompt.txt"
    executable = _write_fake_claude(
        tmp_path,
        f"""
import json
from pathlib import Path

counter = Path({str(counter)!r})
calls = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(calls + 1))
Path({str(capture)!r}).write_text(sys.argv[sys.argv.index("-p") + 1])
if calls == 0:
    result = '{{\\"bad\\": true}}'
else:
    result = '{{\\"ok\\": true}}'
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))
    assert result.output == {"ok": True}
    assert counter.read_text() == "2"
    assert result.metadata["validation_feedback_attempt"] == 1
    assert "failed validation" in capture.read_text(encoding="utf-8")


def test_claude_runner_validation_feedback_is_bounded(tmp_path: Path) -> None:
    counter = tmp_path / "calls.txt"
    executable = _write_fake_claude(
        tmp_path,
        f"""
import json
from pathlib import Path

counter = Path({str(counter)!r})
calls = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(calls + 1))
result = '{{\\"bad\\": true}}'
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    with pytest.raises(AgentOutputError, match="failed schema validation"):
        runner.run(**_run_kwargs(tmp_path, schema_path))
    assert counter.read_text() == "2"


def test_claude_runner_contract_validator_gets_feedback_round(tmp_path: Path) -> None:
    counter = tmp_path / "calls.txt"
    executable = _write_fake_claude(
        tmp_path,
        f"""
import json
from pathlib import Path

counter = Path({str(counter)!r})
calls = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(calls + 1))
result = json.dumps({{"ok": True, "n": calls + 1}})
""",
    )
    schema_path = _write_schema(
        tmp_path,
        {
            "type": "object",
            "required": ["ok", "n"],
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean"}, "n": {"type": "integer"}},
        },
    )
    seen: list[int] = []

    def validator(output: dict) -> None:
        seen.append(output["n"])
        if output["n"] < 2:
            raise AgentOutputError("n must be at least 2")

    runner = ClaudeRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(
        contract_validator=validator, **_run_kwargs(tmp_path, schema_path)
    )
    assert result.output == {"ok": True, "n": 2}
    assert seen == [1, 2]
