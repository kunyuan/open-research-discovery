from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from open_research_discovery.agent import (
    AgentExecutionError,
    AgentOutputError,
    AgentRun,
    KimiRunner,
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


def _write_fake_kimi(tmp_path: Path, body: str) -> str:
    """Write a fake kimi CLI script handling --version plus the given body."""
    fake = tmp_path / "fake_kimi.py"
    fake.write_text(
        """
import sys

if "--version" in sys.argv:
    print("fake-kimi 1.0")
    raise SystemExit(0)
"""
        + body
        + "\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {fake}"


def _run_kwargs(tmp_path: Path, schema_path: Path, role: str = "triage") -> dict:
    return {
        "role": role,
        "prompt": "return structured output",
        "schema_path": schema_path,
        "output_path": tmp_path / "output.json",
        "events_path": tmp_path / "events.jsonl",
    }


def test_kimi_runner_builds_expected_command(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    executable = _write_fake_kimi(
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
print(json.dumps({{"role": "assistant", "content": json.dumps({{"ok": True}})}}))
print(json.dumps({{"role": "meta", "finish": "stop"}}))
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path,
        executable=executable,
        model="k2-thinking",
        timeout_seconds=30,
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))

    assert result.output == {"ok": True}
    captured = json.loads(capture.read_text(encoding="utf-8"))
    argv = captured["argv"]
    assert argv[0] == "-p"
    assert argv[2:] == ["--output-format", "stream-json", "-m", "k2-thinking"]
    assert captured["cwd"] == str(tmp_path.resolve())
    prompt = captured["prompt"]
    assert prompt.startswith("return structured output")
    assert "exactly one JSON object" in prompt
    assert "JSON Schema:" in prompt
    assert json.loads(schema_path.read_text(encoding="utf-8"))["properties"][
        "ok"
    ]["const"] is True
    assert '"const": true' in prompt
    # The persisted metadata command redacts the prompt like the Codex path.
    assert result.metadata["backend"] == "kimi"
    logged = result.metadata["command"]
    assert "<prompt>" in logged
    assert not any("return structured output" in item for item in logged)
    assert result.metadata["kimi_version"] == "fake-kimi 1.0"


def test_kimi_runner_omits_model_flag_without_model(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    executable = _write_fake_kimi(
        tmp_path,
        f"""
import json
import pathlib

pathlib.Path({str(capture)!r}).write_text(
    json.dumps(sys.argv[1:]), encoding="utf-8"
)
print(json.dumps({{"role": "assistant", "content": json.dumps({{"ok": True}})}}))
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))

    assert result.output == {"ok": True}
    argv = json.loads(capture.read_text(encoding="utf-8"))
    assert "-m" not in argv
    assert result.metadata["model"] == "configured-default"


def test_kimi_runner_takes_last_non_empty_assistant_message(
    tmp_path: Path,
) -> None:
    executable = _write_fake_kimi(
        tmp_path,
        """
import json

print("not json at all")
print(json.dumps({"role": "assistant", "content": "{\\"ok\\": false}"}))
print(json.dumps({"role": "tool", "content": "{\\"ok\\": false}"}))
print(json.dumps({"role": "assistant", "content": "  "}))
print(json.dumps({"role": "assistant", "content": "{\\"ok\\": true}"}))
print(json.dumps({"role": "meta", "finish": "stop"}))
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))
    assert result.output == {"ok": True}


def test_kimi_runner_extracts_json_from_prose_and_fences(tmp_path: Path) -> None:
    executable = _write_fake_kimi(
        tmp_path,
        """
import json

reply = "Sure, here is the result:\\n```json\\n{\\"ok\\": true}\\n```\\nDone."
print(json.dumps({"role": "assistant", "content": reply}))
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))
    assert result.output == {"ok": True}


def test_kimi_runner_raises_contract_error_without_json(tmp_path: Path) -> None:
    executable = _write_fake_kimi(
        tmp_path,
        """
import json

print(json.dumps({"role": "assistant", "content": "I could not answer."}))
""",
    )
    schema_path = _write_schema(tmp_path)
    output_path = tmp_path / "output.json"
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    with pytest.raises(
        AgentOutputError, match="no parseable JSON object"
    ):
        runner.run(**_run_kwargs(tmp_path, schema_path))
    # Contract failures are non-retryable AgentOutputError, and the output
    # artifact is never written for an unparseable reply.
    assert not output_path.exists()


def test_kimi_runner_schema_validation_failure_is_contract_error(
    tmp_path: Path,
) -> None:
    executable = _write_fake_kimi(
        tmp_path,
        """
import json

print(json.dumps({"role": "assistant", "content": "{\\"ok\\": false}"}))
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    with pytest.raises(AgentOutputError, match="failed schema validation"):
        runner.run(**_run_kwargs(tmp_path, schema_path))
    invalid = tmp_path / "output.invalid.json"
    assert json.loads(invalid.read_text(encoding="utf-8")) == {"ok": False}


def test_kimi_runner_skips_codex_strict_schema_check(tmp_path: Path) -> None:
    # if/then and properties missing from required are Codex
    # structured-output limits; the kimi backend validates after the call and
    # must accept such schemas.
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
    executable = _write_fake_kimi(
        tmp_path,
        """
import json

reply = json.dumps({"ok": True, "note": "present"})
print(json.dumps({"role": "assistant", "content": reply}))
""",
    )
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))
    assert result.output == {"ok": True, "note": "present"}


def test_kimi_runner_nonzero_exit_is_execution_error(tmp_path: Path) -> None:
    executable = _write_fake_kimi(
        tmp_path,
        """
import sys

print("boom", file=sys.stderr)
raise SystemExit(3)
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    with pytest.raises(AgentExecutionError, match="failed with exit 3") as info:
        runner.run(**_run_kwargs(tmp_path, schema_path))
    # Invocation failures are retryable AgentExecutionError, not the
    # non-retryable contract subclass.
    assert type(info.value) is AgentExecutionError


def test_kimi_runner_sanitizes_environment_by_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KIMI_RUNNER_TEST_SECRET_KEY", "present")
    capture = tmp_path / "capture.json"
    executable = _write_fake_kimi(
        tmp_path,
        f"""
import json
import os
import pathlib

pathlib.Path({str(capture)!r}).write_text(
    json.dumps("KIMI_RUNNER_TEST_SECRET_KEY" in os.environ),
    encoding="utf-8",
)
print(json.dumps({{"role": "assistant", "content": json.dumps({{"ok": True}})}}))
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    runner.run(**_run_kwargs(tmp_path, schema_path, role="triage"))
    assert json.loads(capture.read_text(encoding="utf-8")) is False

    capture.unlink()
    runner.run(**_run_kwargs(tmp_path, schema_path, role="discovery"))
    assert json.loads(capture.read_text(encoding="utf-8")) is True


def _minimal_config(tmp_path: Path, agents: dict) -> dict:
    return {
        "schema_version": 2,
        "name": "kimi-backend-smoke",
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


def test_campaign_selects_kimi_runner_from_config(tmp_path: Path) -> None:
    from open_research_discovery.campaign import CampaignPipeline

    executable = _write_fake_kimi(tmp_path, "\npass\n")
    config = _minimal_config(
        tmp_path,
        {
            "model": "",
            "backend": "kimi",
            "kimi_executable": executable,
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
        run_id="kimi-backend-smoke",
    )
    assert isinstance(pipeline.agent_runner, KimiRunner)
    assert pipeline.tool_versions["kimi"] == "fake-kimi 1.0"


def test_campaign_defaults_to_codex_backend(tmp_path: Path) -> None:
    from open_research_discovery.agent import CodexRunner
    from open_research_discovery.campaign import CampaignPipeline

    executable = _write_fake_kimi(tmp_path, "\npass\n")
    config = _minimal_config(
        tmp_path,
        {
            "model": "",
            "codex_executable": executable,
            "sandbox": "read-only",
            "timeout_seconds": 60,
        },
    )
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    pipeline = CampaignPipeline.start(
        config_path,
        repository_root=Path(__file__).resolve().parents[1],
        run_id="codex-backend-default",
    )
    assert isinstance(pipeline.agent_runner, CodexRunner)
    assert "codex" in pipeline.tool_versions


def test_campaign_rejects_unknown_backend(tmp_path: Path) -> None:
    from open_research_discovery.campaign import CampaignError, CampaignPipeline

    config = _minimal_config(
        tmp_path,
        {
            "model": "",
            "backend": "unknown",
            "codex_executable": "codex",
            "sandbox": "read-only",
            "timeout_seconds": 60,
        },
    )
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    # The campaign schema enum rejects it before runner construction.
    with pytest.raises(CampaignError, match="invalid campaign config"):
        CampaignPipeline.start(
            config_path,
            repository_root=Path(__file__).resolve().parents[1],
            run_id="unknown-backend",
        )


def test_kimi_runner_validation_feedback_repairs_output(tmp_path: Path) -> None:
    """A first invalid reply is retried once with the validator error."""
    counter = tmp_path / "calls.txt"
    capture = tmp_path / "prompt.txt"
    executable = _write_fake_kimi(
        tmp_path,
        f"""
import json
from pathlib import Path

counter = Path({str(counter)!r})
calls = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(calls + 1))
Path({str(capture)!r}).write_text(sys.argv[sys.argv.index("-p") + 1])
if calls == 0:
    print(json.dumps({{"role": "assistant", "content": "{{\\"bad\\": true}}"}}))
else:
    print(json.dumps({{"role": "assistant", "content": "{{\\"ok\\": true}}"}}))
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(**_run_kwargs(tmp_path, schema_path))
    assert result.output == {"ok": True}
    assert counter.read_text() == "2"
    assert result.metadata["validation_feedback_attempt"] == 1
    # The feedback round carries the concrete schema error back to the model.
    assert "failed validation" in capture.read_text(encoding="utf-8")


def test_kimi_runner_validation_feedback_is_bounded(tmp_path: Path) -> None:
    counter = tmp_path / "calls.txt"
    executable = _write_fake_kimi(
        tmp_path,
        f"""
import json
from pathlib import Path

counter = Path({str(counter)!r})
calls = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(calls + 1))
print(json.dumps({{"role": "assistant", "content": "{{\\"bad\\": true}}"}}))
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    with pytest.raises(AgentOutputError, match="failed schema validation"):
        runner.run(**_run_kwargs(tmp_path, schema_path))
    assert counter.read_text() == "2"


def test_kimi_runner_contract_validator_gets_feedback_round(tmp_path: Path) -> None:
    """Contract (Python) validator errors also trigger the feedback round."""
    counter = tmp_path / "calls.txt"
    executable = _write_fake_kimi(
        tmp_path,
        f"""
import json
from pathlib import Path

counter = Path({str(counter)!r})
calls = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(calls + 1))
print(json.dumps({{"role": "assistant", "content": "{{\\"ok\\": true, \\"n\\": %d}}" % (calls + 1)}}))
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

    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    result = runner.run(
        contract_validator=validator, **_run_kwargs(tmp_path, schema_path)
    )
    assert result.output == {"ok": True, "n": 2}
    assert seen == [1, 2]


def test_kimi_runner_honors_stage_cwd(tmp_path: Path) -> None:
    """The stage's memory directory becomes the agent's working directory."""
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    (stage_dir / "memory.md").write_text("# memory\n", encoding="utf-8")
    capture = tmp_path / "capture.json"
    executable = _write_fake_kimi(
        tmp_path,
        f"""
import json
import os
import pathlib

pathlib.Path({str(capture)!r}).write_text(
    json.dumps({{"cwd": os.getcwd()}}), encoding="utf-8"
)
print(json.dumps({{"role": "assistant", "content": json.dumps({{"ok": True}})}}))
""",
    )
    schema_path = _write_schema(tmp_path)
    runner = KimiRunner(
        repository_root=tmp_path, executable=executable, timeout_seconds=30
    )
    kwargs = _run_kwargs(tmp_path, schema_path)
    kwargs["cwd"] = stage_dir

    result = runner.run(**kwargs)

    assert result.output == {"ok": True}
    captured = json.loads(capture.read_text(encoding="utf-8"))
    assert captured["cwd"] == str(stage_dir.resolve())
