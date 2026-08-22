from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from open_research_discovery.agent import TraeRunner


def _write_schema(tmp_path: Path) -> Path:
    path = tmp_path / "schema.json"
    path.write_text(
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
    return path


def _write_fake_internal_trae(tmp_path: Path, capture: Path) -> str:
    fake = tmp_path / "fake_trae.py"
    fake.write_text(
        f"""
import json
import os
import pathlib
import sys

if "--help" in sys.argv:
    print("Run Trae non-interactively")
    raise SystemExit(0)
if "--version" in sys.argv:
    print("fake-trae 1.0")
    raise SystemExit(0)

pathlib.Path({str(capture)!r}).write_text(
    json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}),
    encoding="utf-8",
)
pathlib.Path("output.json").write_text(
    json.dumps({{"ok": True}}),
    encoding="utf-8",
)
print(json.dumps({{"ok": True}}))
""",
        encoding="utf-8",
    )
    return f"{sys.executable} {fake}"


def test_internal_trae_runner_uses_file_delivery_contract(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifact_dir = tmp_path / "artifacts"
    schema_path = _write_schema(tmp_path)
    runner = TraeRunner(
        repository_root=tmp_path,
        executable=_write_fake_internal_trae(tmp_path, capture),
        model="seed-test",
        timeout_seconds=30,
    )

    result = runner.run(
        role="triage",
        prompt="return structured output",
        schema_path=schema_path,
        output_path=artifact_dir / "output.json",
        events_path=artifact_dir / "events.jsonl",
        cwd=workspace,
    )

    assert result.output == {"ok": True}
    assert json.loads((artifact_dir / "output.json").read_text()) == {"ok": True}
    assert not (workspace / "output.json").exists()
    captured = json.loads(capture.read_text(encoding="utf-8"))
    assert captured["cwd"] == str(workspace)
    assert captured["argv"][:5] == [
        "exec",
        "--skip-git-repo-check",
        "--output-mode",
        "final-message-only",
        "-m",
    ]
    assert captured["argv"][5:8] == ["seed-test", "-s", "workspace-write"]
    assert "Delivery contract:" in captured["argv"][-1]
    assert result.metadata["backend"] == "trae"
    assert result.metadata["trae_subcommand"] == "exec"
    assert result.metadata["trae_version"] == "fake-trae 1.0"


def test_campaign_schema_accepts_trae_without_codex_fields() -> None:
    schema_path = Path(__file__).parents[1] / "schemas" / "campaign.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    config = {
        "schema_version": 2,
        "name": "trae-smoke",
        "topics": [
            {
                "id": "test-topic",
                "title": "Test topic",
                "query": "test query",
                "sources": ["topic_search"],
                "seed_papers": [],
                "seed_references": [],
            }
        ],
        "limits": {
            "questions_per_domain": 1,
            "lkm_timeout_seconds": 10,
        },
        "agents": {
            "backend": "trae",
            "model": "seed-test",
            "timeout_seconds": 60,
        },
        "outputs": {
            "runs_root": "work/runs",
            "problem_root": "work/problems",
            "pool_root": "work/pool",
        },
    }

    errors = sorted(
        Draft202012Validator(schema).iter_errors(config),
        key=lambda error: list(error.path),
    )
    assert errors == []
