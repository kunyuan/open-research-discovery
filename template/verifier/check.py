#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    submission = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("submission")
    result = {
        "valid": False,
        "status": "verifier_not_implemented",
        "submission": str(submission),
    }
    print(json.dumps(result, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
