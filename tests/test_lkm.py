import json

import pytest

from open_research_discovery.lkm import (
    LKMResponseError,
    PAPER_GRAPH_URL,
    build_paper_graph_request,
    extract_paper_open_questions,
    paper_identifier,
)


def test_extracts_only_dedicated_paper_open_questions() -> None:
    payload = {
        "code": 0,
        "data": {
            "papers": [
                {
                    "paper": {
                        "id": "123",
                        "en_title": "A Paper",
                        "doi": "10.1000/example",
                    },
                    "open_questions": [
                        {
                            "content": "Determine whether X is true.",
                            "id": "paper:123::open_question",
                            "global_id": "gcn_open",
                        }
                    ],
                    "questions": [
                        {
                            "content": "An ordinary question.",
                            "id": "paper:123::question",
                            "global_id": "gcn_question",
                        }
                    ],
                    "addressed_problems": [
                        {
                            "content": "A historical problem.",
                            "id": "paper:123::problem",
                            "global_id": "gcn_problem",
                        }
                    ],
                    "subproblems": [
                        {
                            "content": "A subproblem inferred from a proof.",
                            "id": "paper:123::subproblem",
                            "global_id": "gcn_subproblem",
                        }
                    ],
                    "variables": [
                        {
                            "type": "question",
                            "content": "A graph question node.",
                            "id": "paper:123::question_2",
                        }
                    ],
                }
            ]
        },
        "trace_id": "req_test",
    }

    assert extract_paper_open_questions(payload) == [
        {
            "content": "Determine whether X is true.",
            "id": "paper:123::open_question",
            "global_id": "gcn_open",
            "paper_id": "123",
            "paper_title": "A Paper",
            "paper_doi": "10.1000/example",
            "source_path": "data.papers[].open_questions",
        }
    ]


def test_extracts_each_open_question_with_its_own_paper_metadata() -> None:
    payload = {
        "code": 0,
        "data": {
            "papers": [
                {
                    "paper": {"id": "1", "zh_title": "论文一", "doi": "doi:1"},
                    "open_questions": [
                        {"content": "Q1", "id": "l1", "global_id": "g1"},
                        {"content": "Q2", "id": "l2", "global_id": "g2"},
                    ],
                },
                {
                    "paper": {"id": "2", "title": "Paper Two"},
                    "open_questions": [
                        {"content": "Q3", "id": "l3", "global_id": "g3"}
                    ],
                },
            ]
        },
    }

    questions = extract_paper_open_questions(payload)

    assert [item["global_id"] for item in questions] == ["g1", "g2", "g3"]
    assert questions[0]["paper_title"] == "论文一"
    assert questions[2]["paper_title"] == "Paper Two"
    assert questions[2]["paper_doi"] == ""


def test_nonzero_business_code_is_not_treated_as_empty_success() -> None:
    with pytest.raises(LKMResponseError, match="code=290011"):
        extract_paper_open_questions(
            {"code": 290011, "msg": "paper not found", "data": {"papers": []}}
        )


def test_paper_identifier_requires_exactly_one_value() -> None:
    assert paper_identifier(doi=" 10.1000/example ") == {
        "doi": "10.1000/example"
    }
    with pytest.raises(ValueError, match="exactly one"):
        paper_identifier()
    with pytest.raises(ValueError, match="exactly one"):
        paper_identifier(paper_id="123", title="A Paper")


def test_request_is_post_with_access_key_and_identifier_only() -> None:
    request = build_paper_graph_request(
        {"paper_id": "123"},
        access_key="secret-for-test",
    )

    assert request.full_url == PAPER_GRAPH_URL
    assert request.method == "POST"
    assert json.loads(request.data.decode("utf-8")) == {"paper_id": "123"}
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["accesskey"] == "secret-for-test"
    assert headers["content-type"] == "application/json"
