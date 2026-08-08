#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from open_research_discovery.pool import load_catalog
from open_research_discovery.ranking import rank_records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List Problem Contracts by significance and review score."
    )
    parser.add_argument(
        "--catalog", type=Path, default=Path("pool/catalog.jsonl")
    )
    parser.add_argument("--domain", default="")
    parser.add_argument("--lane", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    records = load_catalog(args.catalog)
    if args.domain:
        needle = args.domain.lower()
        records = [
            record
            for record in records
            if needle in str(record.get("domain") or "").lower()
        ]
    ranked = rank_records(records)
    if args.lane:
        allowed_lanes = set(args.lane)
        ranked = [
            record
            for record in ranked
            if record["ranking_lane"] in allowed_lanes
        ]
    if args.limit > 0:
        ranked = ranked[: args.limit]

    if args.json:
        print(json.dumps(ranked, ensure_ascii=False, indent=2, sort_keys=True))
        return

    print(
        "rank\tID\tsignificance\tverification_difficulty\tCI\ttitle\trationale"
    )
    for index, row in enumerate(ranked, start=1):
        print(
            "\t".join(
                [
                    str(index),
                    row["id"],
                    row["scientific_significance_level"],
                    str(row["verification_difficulty"]),
                    row["ci_status"],
                    row["title"],
                    row["ranking_rationale"],
                ]
            )
        )


if __name__ == "__main__":
    main()
