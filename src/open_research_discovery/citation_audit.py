"""Deterministic pre-review citation check.

After the Research stage and before the editing Problem Review, the pipeline
resolves every identifier cited in the problem record and compares the
fetched metadata with the citation text. The verdicts land in
``review-workdir/possible-bugs.md`` for the reviewer to process; the check
itself never blocks the stage.
"""

from __future__ import annotations

from typing import Any

from .pool import jaccard, text_tokens
from .quality import FetchCallable, _reference_records, classify_identifier


# A fetched title counts as matching when its tokens are contained in the
# citation text or the token Jaccard clears this bar; when in doubt the
# entry is flagged rather than waved through.
_TITLE_MATCH_THRESHOLD = 0.5

VERDICT_ORDER = ("ok", "mismatch", "unresolvable", "no-identifier")


def _title_matches(reference_text: str, fetched_title: str) -> bool:
    title_tokens = text_tokens(fetched_title)
    if not title_tokens:
        return False
    reference_tokens = text_tokens(reference_text)
    return title_tokens <= reference_tokens or (
        jaccard(title_tokens, reference_tokens) >= _TITLE_MATCH_THRESHOLD
    )


def _first_author_family(authors: list[Any]) -> str:
    if not authors:
        return ""
    parts = str(authors[0]).replace(",", " ").split()
    return parts[-1].lower() if parts else ""


def check_citations(
    problem: dict[str, Any], fetch: FetchCallable
) -> list[dict[str, Any]]:
    """Check every reference/progress string of a problem record.

    Every extracted identifier (DOI, arXiv ID, URL) in a citation is resolved
    and compared individually; the citation's verdict aggregates them: any
    ``mismatch`` wins, then any ``unresolvable``, otherwise ``ok`` (or
    ``no-identifier`` when nothing was extracted). ``author-mismatch`` is
    flagged when any fetched first author's family name is absent from the
    citation text. Fetch failures are recorded as ``unresolvable``; they
    never raise.
    """

    entries: list[dict[str, Any]] = []
    texts = [
        (origin, str(text))
        for origin, field in (("references", "references"), ("previous_progress", "previous_progress"))
        for text in (problem.get(field) or [])
        if isinstance(text, str) and str(text).strip()
    ]
    for origin, text in texts:
        records = _reference_records({"references": [text]})
        entry: dict[str, Any] = {
            "origin": origin,
            "reference": text,
            "identifiers": [
                record["identifier"] or record["url"] for record in records
            ],
            "verdict": "no-identifier",
            "flags": [],
            "checks": [],
        }
        for record in records:
            kind, normalized = classify_identifier(record["identifier"])
            target = normalized or record["url"]
            target_kind = kind if normalized else "url"
            try:
                fetched = fetch(target_kind, target)
            except Exception as error:  # an injected fetcher must not kill the stage
                fetched = {
                    "status": "error",
                    "metadata": {},
                    "detail": f"{type(error).__name__}: {error}",
                }
            metadata = fetched.get("metadata") or {}
            check: dict[str, Any] = {
                "identifier": record["identifier"] or record["url"],
                "kind": target_kind,
                "status": str(fetched.get("status") or ""),
                "title": str(metadata.get("title") or ""),
                "authors": [
                    str(author) for author in metadata.get("authors") or []
                ],
                "detail": str(fetched.get("detail") or ""),
                "verdict": "unresolvable",
                "author_mismatch": False,
            }
            if check["status"] == "found":
                check["verdict"] = (
                    "ok" if _title_matches(text, check["title"]) else "mismatch"
                )
                family = _first_author_family(check["authors"])
                if family and family not in text.lower():
                    check["author_mismatch"] = True
            entry["checks"].append(check)
        if entry["checks"]:
            verdicts = {check["verdict"] for check in entry["checks"]}
            if "mismatch" in verdicts:
                entry["verdict"] = "mismatch"
            elif "unresolvable" in verdicts:
                entry["verdict"] = "unresolvable"
            else:
                entry["verdict"] = "ok"
            if any(check["author_mismatch"] for check in entry["checks"]):
                entry["flags"].append("author-mismatch")
        entries.append(entry)
    return entries


def is_flagged(entry: dict[str, Any]) -> bool:
    return entry["verdict"] != "ok" or bool(entry["flags"])


def render_possible_bugs(entries: list[dict[str, Any]]) -> str:
    """Render the review-workdir possible-bugs.md content."""

    flagged = [entry for entry in entries if is_flagged(entry)]
    lines = [
        "# Possible citation bugs (pipeline mechanical pre-check)",
        "",
        "Every reference in research.json was checked deterministically: its",
        "identifiers were extracted and resolved against arXiv, Crossref, and",
        "web metadata. Verdicts: `ok`, `mismatch` (the fetched work's title",
        "does not match the citation text), `unresolvable` (the identifier",
        "could not be resolved), `no-identifier` (no DOI, arXiv ID, or URL in",
        "the citation); `author-mismatch` is an extra flag when the fetched",
        "first author's family name is absent from the citation text.",
        "",
        f"{len(entries)} citation(s) checked, {len(flagged)} flagged.",
        "",
    ]
    for index, entry in enumerate(entries, start=1):
        reference = entry["reference"]
        if len(reference) > 200:
            reference = reference[:197] + "..."
        flags = f" (+ {', '.join(entry['flags'])})" if entry["flags"] else ""
        lines.append(f"## {index}. {reference}")
        lines.append(f"- Origin: {entry['origin']}")
        lines.append(f"- Verdict: `{entry['verdict']}`{flags}")
        if not entry["checks"]:
            lines.append("- Identifier: none found in the citation text")
        for check in entry["checks"]:
            lines.append(
                f"- {check['kind']}:{check['identifier']} → `{check['verdict']}`"
            )
            if check["title"]:
                lines.append(f"  - Fetched title: {check['title']}")
            if check["authors"]:
                lines.append(
                    "  - Fetched authors: " + ", ".join(check["authors"])
                )
            if check["author_mismatch"]:
                lines.append(
                    "  - First author's family name is absent from the "
                    "citation text"
                )
            if check["status"] != "found" and check["detail"]:
                lines.append(f"  - Fetch detail: {check['detail']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
