from __future__ import annotations

import json
import sys
from pathlib import Path

from open_research_discovery.agent import CodexRunner


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
        walk(json.loads(schema_path.read_text(encoding="utf-8")))


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
                "properties": {"ok": {"const": True}},
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
    assert "--json" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert result.metadata["codex_version"] == "fake-codex 1.0"
    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8"))
    assert event["type"] == "fake-event"


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
                "properties": {"ok": {"const": True}},
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
