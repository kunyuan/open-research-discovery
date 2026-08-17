from __future__ import annotations

from typing import Any

from open_research_discovery.citation_audit import (
    check_citations,
    is_flagged,
    render_possible_bugs,
)


def _found(title: str, authors: list[str]) -> dict[str, Any]:
    return {
        "identifier": "x",
        "kind": "doi",
        "fetched_at": "2026-08-17T00:00:00+00:00",
        "status": "found",
        "metadata": {
            "title": title,
            "authors": authors,
            "venue": "Journal of Testing",
            "year": 2020,
            "doi": "x",
            "url": "",
        },
        "detail": "",
    }


def _not_found() -> dict[str, Any]:
    return {
        "identifier": "x",
        "kind": "doi",
        "fetched_at": "2026-08-17T00:00:00+00:00",
        "status": "not_found",
        "metadata": {
            "title": "",
            "authors": [],
            "venue": "",
            "year": None,
            "doi": "",
            "url": "",
        },
        "detail": "Crossref has no work for this DOI",
    }


MATCHING_TITLE = "Optimal state determination by mutually unbiased measurements"

PROBLEM = {
    "references": [
        (
            "Ivanovic, Wiesner. Optimal state-determination by mutually "
            "unbiased measurements. https://doi.org/10.1/ok, 1989."
        ),
        "Smith. Entirely unrelated words about gardening. "
        "https://doi.org/10.1/mismatch, 2019.",
        "Roe. A work that cannot be resolved. https://doi.org/10.1/gone, 2018.",
        "A cited work with no identifier at all, 2017.",
        "Kohn. Optimal state-determination by mutually unbiased "
        "measurements (reprint). https://doi.org/10.1/auth, 2021.",
    ],
    "previous_progress": [],
}


def _fetch(kind: str, identifier: str) -> dict[str, Any]:
    if identifier == "10.1/ok":
        return _found(MATCHING_TITLE, ["H. Ivanovic", "S. Wiesner"])
    if identifier == "10.1/mismatch":
        return _found(MATCHING_TITLE, ["H. Ivanovic"])
    if identifier == "10.1/auth":
        return _found(MATCHING_TITLE, ["G. Wannier"])
    return _not_found()


def test_check_citations_verdicts() -> None:
    entries = check_citations(PROBLEM, _fetch)
    by_identifier = {
        entry["identifiers"][0] if entry["identifiers"] else "": entry
        for entry in entries
    }
    assert by_identifier["10.1/ok"]["verdict"] == "ok"
    assert by_identifier["10.1/ok"]["flags"] == []
    mismatch = by_identifier["10.1/mismatch"]
    assert mismatch["verdict"] == "mismatch"
    assert mismatch["checks"][0]["title"] == MATCHING_TITLE
    assert by_identifier["10.1/gone"]["verdict"] == "unresolvable"
    no_id = by_identifier[""]
    assert no_id["verdict"] == "no-identifier"
    author = by_identifier["10.1/auth"]
    # The fetched first author family name is absent from the citation text.
    assert author["verdict"] == "ok"
    assert author["flags"] == ["author-mismatch"]
    assert [is_flagged(entry) for entry in entries] == [
        False,
        True,
        True,
        True,
        True,
    ]


def test_one_wrong_identifier_mismatches_the_whole_citation() -> None:
    """A correct arXiv ID must not whitewash a wrong DOI in one citation."""

    problem = {
        "references": [
            "Brändén, Huh. Lorentzian polynomials. "
            "DOI 10.4007/annals.2020.192.3.2, "
            "https://arxiv.org/abs/1902.03719, 2020."
        ],
        "previous_progress": [],
    }

    def fetch(kind: str, identifier: str) -> dict[str, Any]:
        if kind == "arxiv":
            return _found("Lorentzian polynomials", ["P. Brändén", "J. Huh"])
        return _found(
            "An unrelated paper by Casale et al.",
            ["M. Casale", "R. Doe"],
        )

    (entry,) = check_citations(problem, fetch)
    assert entry["verdict"] == "mismatch"
    assert len(entry["checks"]) == 2
    arxiv_check = next(c for c in entry["checks"] if c["kind"] == "arxiv")
    doi_check = next(c for c in entry["checks"] if c["kind"] == "doi")
    assert arxiv_check["verdict"] == "ok"
    assert doi_check["verdict"] == "mismatch"
    assert "Casale" in doi_check["title"]
    assert entry["flags"] == ["author-mismatch"]

    text = render_possible_bugs([entry])
    assert "arxiv:1902.03719 → `ok`" in text
    assert "doi:10.4007/annals.2020.192.3.2 → `mismatch`" in text
    assert "An unrelated paper by Casale et al." in text
    assert "Lorentzian polynomials" in text


def test_first_author_family_in_text_counts_as_ok() -> None:
    """Paraphrased prose need not repeat the paper's title."""

    problem = {
        "references": [],
        "previous_progress": [
            "Feder and Mihail (1992, DOI 10.1145/129712.129716) via "
            "balanced matroids established the pairwise inequality."
        ],
    }

    def fetch(kind: str, identifier: str) -> dict[str, Any]:
        return _found("Balanced matroids", ["T. Feder", "M. Mihail"])

    (entry,) = check_citations(problem, fetch)
    assert entry["verdict"] == "ok"
    assert entry["flags"] == []
    assert entry["checks"][0]["title"] == "Balanced matroids"


def test_bare_arxiv_id_in_prose_is_extracted() -> None:
    """arXiv IDs without a URL must not fall through to no-identifier."""

    problem = {
        "references": [],
        "previous_progress": [
            "Brändén and Huh (arXiv:1902.03719; Annals of Mathematics "
            "192 (2020) 821–891) proved the pairwise inequality up to "
            "a factor of two."
        ],
    }

    def fetch(kind: str, identifier: str) -> dict[str, Any]:
        assert kind == "arxiv" and identifier == "1902.03719"
        return _found("Lorentzian polynomials", ["P. Brändén", "J. Huh"])

    (entry,) = check_citations(problem, fetch)
    assert entry["verdict"] == "ok"
    assert len(entry["checks"]) == 1
    assert entry["checks"][0]["kind"] == "arxiv"


def test_author_fallback_does_not_apply_to_references() -> None:
    """References stay on the strict title judgment even when authors match."""

    problem = {
        "references": [
            "Ayyer, Linusson, Ravichandran. Bunkbed inequalities for the "
            "arboreal gas. https://arxiv.org/abs/2509.18788, 2025."
        ],
        "previous_progress": [],
    }

    def fetch(kind: str, identifier: str) -> dict[str, Any]:
        return _found(
            "The bunkbed problem and the random cluster model",
            ["Arvind Ayyer", "Svante Linusson"],
        )

    (entry,) = check_citations(problem, fetch)
    assert entry["verdict"] == "mismatch"
    assert entry["flags"] == []


def test_arxiv_digit_runs_inside_doi_are_not_extracted() -> None:
    problem = {
        "references": [
            "Huang. On negative correlation of the arboreal gas. "
            "DOI 10.1016/j.spl.2024.110174, 2024."
        ],
        "previous_progress": [],
    }
    fetched_kinds: list[str] = []

    def fetch(kind: str, identifier: str) -> dict[str, Any]:
        fetched_kinds.append(kind)
        return _found("On negative correlation of Arboreal Gas", ["X. Huang"])

    (entry,) = check_citations(problem, fetch)
    assert fetched_kinds == ["doi"]
    assert [check["identifier"] for check in entry["checks"]] == [
        "10.1016/j.spl.2024.110174"
    ]
    assert entry["verdict"] == "ok"


def test_check_citations_tolerates_raising_fetcher() -> None:
    def boom(kind: str, identifier: str) -> dict[str, Any]:
        raise TimeoutError("stuck")

    entries = check_citations(
        {"references": ["Doe. Some work. https://doi.org/10.1/x, 2020."]},
        boom,
    )
    assert entries[0]["verdict"] == "unresolvable"
    assert "TimeoutError" in entries[0]["checks"][0]["detail"]


def test_render_possible_bugs_lists_flagged_entries() -> None:
    entries = check_citations(PROBLEM, _fetch)
    text = render_possible_bugs(entries)
    assert "5 citation(s) checked, 4 flagged" in text
    assert "`mismatch`" in text
    assert "`unresolvable`" in text
    assert "`no-identifier`" in text
    assert "author-mismatch" in text
    assert MATCHING_TITLE in text
    assert "G. Wannier" in text
    # Every identifier's own verdict line is rendered.
    assert "10.1/mismatch → `mismatch`" in text
    assert "10.1/gone → `unresolvable`" in text
