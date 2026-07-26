#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import yaml

from open_research_discovery.common import (
    dump_json,
    dump_yaml,
    pool_snapshot_paths,
    problem_manifest_paths,
)
from open_research_discovery.pool import (
    VIEW_SPECS,
    dedup_candidates,
    pool_statistics,
    problem_to_record,
    render_table,
    validate_relations,
)
from open_research_discovery.validation import validate_problem


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synchronize a portable problem pool from local problem repositories."
    )
    parser.add_argument("problem_root", type=Path)
    parser.add_argument("--out", type=Path, default=Path("pool"))
    parser.add_argument("--dedup-threshold", type=float, default=0.25)
    args = parser.parse_args()

    discovery_root = Path(__file__).resolve().parents[1]
    out = args.out.resolve()
    problems_out = out / "problems"
    views_out = out / "views"
    problems_out.mkdir(parents=True, exist_ok=True)
    views_out.mkdir(parents=True, exist_ok=True)

    sources = problem_manifest_paths(args.problem_root)
    records = []
    problem_ids = set()
    for source in sources:
        errors = validate_problem(
            source, discovery_root / "schemas" / "problem.schema.json"
        )
        if errors:
            raise SystemExit(
                f"{source}:\n" + "\n".join(f"  - {error}" for error in errors)
            )
        problem = yaml.safe_load(source.read_text(encoding="utf-8"))
        problem_id = str(problem["id"])
        if problem_id in problem_ids:
            raise SystemExit(f"duplicate problem id: {problem_id}")
        problem_ids.add(problem_id)
        destination = problems_out / f"{problem_id}.yaml"
        shutil.copy2(source, destination)
        records.append(problem_to_record(problem, source.parent.name))

    for stale in pool_snapshot_paths(problems_out):
        if stale.stem not in problem_ids:
            stale.unlink()

    records.sort(key=lambda row: row["id"])
    catalog_path = out / "catalog.jsonl"
    with catalog_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    relations_path = out / "relations.yaml"
    relations = (
        yaml.safe_load(relations_path.read_text(encoding="utf-8"))
        if relations_path.exists()
        else {"schema_version": 1, "relations": []}
    ) or {"schema_version": 1, "relations": []}
    relation_errors = validate_relations(relations, problem_ids)
    if relation_errors:
        raise SystemExit("\n".join(relation_errors))

    dump_json(
        out / "dedup-candidates.json",
        {
            "schema_version": 1,
            "threshold": args.dedup_threshold,
            "candidates": dedup_candidates(
                records,
                relations=relations,
                threshold=args.dedup_threshold,
            ),
        },
    )
    dump_yaml(out / "stats.yaml", pool_statistics(records))

    for view_name, (title, field, values) in VIEW_SPECS.items():
        selected = [row for row in records if row.get(field) in values]
        (views_out / f"{view_name}.md").write_text(
            render_table(title, selected), encoding="utf-8"
        )
    (views_out / "all.md").write_text(
        render_table("All canonical problems", records), encoding="utf-8"
    )

    domain_groups: dict[str, list[dict[str, object]]] = {}
    for record in records:
        domain_groups.setdefault(record["domain"], []).append(record)
    domain_lines = ["# Problems by domain", ""]
    for domain, domain_records in sorted(domain_groups.items()):
        domain_lines.extend(
            [
                f"## {domain}",
                "",
                *[
                    f"- [{row['id']}](../{row['snapshot']}): {row['title']}"
                    for row in sorted(domain_records, key=lambda item: item["id"])
                ],
                "",
            ]
        )
    (views_out / "by-domain.md").write_text(
        "\n".join(domain_lines).rstrip() + "\n", encoding="utf-8"
    )

    print(
        f"synced={len(records)} pool={out} "
        f"dedup_candidates={len(dedup_candidates(records, relations=relations, threshold=args.dedup_threshold))}"
    )


if __name__ == "__main__":
    main()
