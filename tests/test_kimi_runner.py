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


def test_benchmark_evaluate_runs_end_to_end_with_kimi_backend(
    tmp_path: Path,
) -> None:
    from test_benchmark import _write_dataset

    from open_research_discovery.benchmark import evaluate_benchmark

    repository_root = Path(__file__).resolve().parents[1]
    executable = _write_fake_kimi(
        tmp_path,
        """
import json
import re
import sys

prompt = sys.argv[sys.argv.index("-p") + 1]
case_id = re.search(r"ORSB-[0-9A-Z]+", prompt).group(0)
prediction = {
    "schema_version": 9,
    "case_id": case_id,
    "importance": {
        "label": "medium",
        "confidence": 0.8,
        "rationale": "The question controls a recognized finite boundary.",
    },
    "solution_review": {
        "verification_difficulty": 0,
        "confidence": 0.9,
        "expected_result": "A finite counterexample.",
        "rationale": "The final witness can be checked directly.",
    },
    "ci": {
        "buildability": "machine",
        "confidence": 0.9,
        "verification_contract": "Parse and check the finite witness.",
        "pseudocode": ["assert check(candidate)"],
        "estimated_runtime": "under one minute",
        "timeout_minutes": 5,
        "rationale": "All acceptance predicates are finite.",
    },
}
print(json.dumps({"role": "assistant", "content": json.dumps(prediction)}))
print(json.dumps({"role": "meta", "finish": "stop"}))
""",
    )
    dataset = _write_dataset(tmp_path)
    runner = KimiRunner(
        repository_root=repository_root, executable=executable, timeout_seconds=30
    )
    report = evaluate_benchmark(
        dataset_dir=dataset,
        out_dir=tmp_path / "out",
        input_schema=repository_root / "schemas" / "benchmark" / "input.schema.json",
        prediction_schema=repository_root
        / "schemas"
        / "benchmark"
        / "prediction.schema.json",
        runner=runner,
    )
    assert report["case_count"] == 1
    assert report["predictions"][0]["case_id"] == "ORSB-111111111111"
    prediction_path = (
        tmp_path / "out" / "predictions" / "ORSB-111111111111" / "prediction.json"
    )
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    assert prediction["case_id"] == "ORSB-111111111111"
    metadata = json.loads(
        prediction_path.with_name("metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["backend"] == "kimi"
    assert metadata["network_policy"] == "offline"
