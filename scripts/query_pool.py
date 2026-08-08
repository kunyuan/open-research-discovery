#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from open_research_discovery.pool import filter_records, load_catalog, normalize_text


FILTER_FIELDS = {
    "significance": "scientific_significance_level",
    "verification-difficulty": "verification_difficulty",
    "ci-status": "ci_status",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter the canonical problem pool.")
    parser.add_argument(
        "--catalog", type=Path, default=Path("pool/catalog.jsonl")
    )
    for option in FILTER_FIELDS:
        parser.add_argument(
            f"--{option}",
            dest=option.replace("-", "_"),
            action="append",
            default=[],
        )
    parser.add_argument("--domain", default="")
    parser.add_argument("--text", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    filters = {
        field: set(getattr(args, option.replace("-", "_")))
        for option, field in FILTER_FIELDS.items()
        if getattr(args, option.replace("-", "_"))
    }
    records = filter_records(load_catalog(args.catalog), filters)
    if args.domain:
        records = [
            row for row in records if args.domain.lower() in row["domain"].lower()
        ]
    if args.text:
        needle = normalize_text(args.text)
        records = [
            row
            for row in records
            if needle in row["search_text"] or needle in row["id"].lower()
        ]
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print("ID\tsignificance\tverification_difficulty\tci\ttitle")
    for row in records:
        print(
            "\t".join(
                [
                    row["id"],
                    row["scientific_significance_level"],
                    str(row["verification_difficulty"]),
                    row["ci_status"],
                    row["title"],
                ]
            )
        )


if __name__ == "__main__":
    main()
