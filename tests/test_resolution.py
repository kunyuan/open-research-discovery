import pytest

from open_research_discovery.resolution import build_resolution_queries


def test_resolution_queries_include_status_and_alias_variants() -> None:
    problem = {
        "question": {
            "canonical_statement": "Does every object satisfy P?",
            "aliases": ["P conjecture"],
        }
    }

    queries = build_resolution_queries(problem)

    assert queries[0] == "Does every object satisfy P?"
    assert any("counterexample" in query for query in queries)
    assert any("improved bound" in query for query in queries)
    assert any("replication reproduction" in query for query in queries)
    assert "P conjecture" in queries


def test_resolution_queries_require_canonical_statement() -> None:
    with pytest.raises(ValueError):
        build_resolution_queries({"question": {}})
