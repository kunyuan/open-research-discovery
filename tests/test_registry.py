from pathlib import Path

from open_research_discovery.common import dump_yaml
from open_research_discovery.registry import build_registry


def test_build_registry_writes_jsonl_and_markdown(tmp_path: Path) -> None:
    source = tmp_path / "repos.yaml"
    jsonl = tmp_path / "registry.jsonl"
    index = tmp_path / "INDEX.md"
    dump_yaml(
        source,
        {
            "schema_version": 1,
            "repos": [
                {
                    "id": "OMP-0002",
                    "title": "Second",
                    "domain": "graph-theory",
                    "status": "ready",
                    "importance_level": "high",
                    "post_audit_priority": "high",
                    "route": "candidate-result",
                    "verification_difficulty": 6,
                    "ci_status": "solution-reviewer-only",
                    "resolution_checked_at": "2026-07-25",
                    "repo": "https://example.test/two",
                }
            ],
        },
    )

    rows = build_registry(source, jsonl, index)

    assert rows[0]["id"] == "OMP-0002"
    assert '"id": "OMP-0002"' in jsonl.read_text()
    assert "candidate-result" in index.read_text()
    assert "6/10" in index.read_text()
    assert "solution-reviewer-only" in index.read_text()
    assert "[repo](https://example.test/two)" in index.read_text()


def test_build_registry_rebases_local_repo_link_for_index(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    source = registry_dir / "repos.yaml"
    jsonl = registry_dir / "registry.jsonl"
    index = registry_dir / "INDEX.md"
    dump_yaml(
        source,
        {
            "schema_version": 1,
            "repos": [
                {
                    "id": "OMP-0001",
                    "title": "Local problem",
                    "domain": "graph-theory",
                    "status": "ready",
                    "resolution_checked_at": "2026-07-25",
                    "repo": "../OMP-0001-local-problem",
                }
            ],
        },
    )

    build_registry(source, jsonl, index)

    assert "[repo](../../OMP-0001-local-problem)" in index.read_text()
