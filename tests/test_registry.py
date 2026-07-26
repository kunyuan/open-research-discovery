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
                    "artifact_type": "counterexample",
                    "importance_level": "high",
                    "post_audit_priority": "high",
                    "route": "candidate-llm",
                    "verification_mode": "llm-reviewable",
                    "verification_ease": "easy",
                    "review_scope": "result-and-derivation",
                    "ci_status": "reviewer-only",
                    "resolution_checked_at": "2026-07-25",
                    "repo": "https://example.test/two",
                }
            ],
        },
    )

    rows = build_registry(source, jsonl, index)

    assert rows[0]["id"] == "OMP-0002"
    assert '"id": "OMP-0002"' in jsonl.read_text()
    assert "candidate-llm" in index.read_text()
    assert "llm-reviewable" in index.read_text()
    assert "result-and-derivation" in index.read_text()
    assert "reviewer-only" in index.read_text()
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
                    "artifact_type": "counterexample",
                    "resolution_checked_at": "2026-07-25",
                    "repo": "../OMP-0001-local-problem",
                }
            ],
        },
    )

    build_registry(source, jsonl, index)

    assert "[repo](../../OMP-0001-local-problem)" in index.read_text()
