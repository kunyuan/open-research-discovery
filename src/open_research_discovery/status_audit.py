from __future__ import annotations


CLOSED_RATIONALE_SUFFIX = (
    "The original target is closed by the cited later result."
)


def closed_rationale(rationale: str) -> str:
    base = " ".join(rationale.split())
    while base.endswith(CLOSED_RATIONALE_SUFFIX):
        base = base[: -len(CLOSED_RATIONALE_SUFFIX)].rstrip()
    return f"{base} {CLOSED_RATIONALE_SUFFIX}".strip()
