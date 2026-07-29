#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from open_research_discovery.common import load_yaml
from open_research_discovery.pool import load_catalog, validate_pool
from open_research_discovery.validation import (
    validate_agentgitlab_snapshot,
    validate_registry,
    validate_registry_pool_consistency,
)


def validate_repository(root: Path) -> dict[str, list[str]]:
    registry = root / "registry" / "repos.yaml"
    checks = {
        "pool": validate_pool(root / "pool"),
        "registry/repos.yaml": (
            validate_registry(registry)
            if registry.is_file()
            else ["missing registry/repos.yaml"]
        ),
    }
    catalog = root / "pool" / "catalog.jsonl"
    if registry.is_file() and catalog.is_file():
        rows = load_yaml(registry).get("repos") or []
        checks["registry/repos.yaml↔pool/catalog.jsonl"] = (
            validate_registry_pool_consistency(rows, load_catalog(catalog))
        )
    snapshot = root / "registry" / "agentgitlab-research-ready.yaml"
    if snapshot.is_file() and registry.is_file():
        checks["registry/agentgitlab-research-ready.yaml"] = (
            validate_agentgitlab_snapshot(snapshot, registry)
        )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an external open-research problem-pool repository."
    )
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    root = args.repository.resolve()
    checks = validate_repository(root)
    errors = [
        f"{name}: {error}"
        for name, findings in checks.items()
        for error in findings
    ]
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"problem-pool validation passed: {root}")


if __name__ == "__main__":
    main()
