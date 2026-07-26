from open_research_discovery.status_audit import closed_rationale


def test_closed_rationale_is_idempotent() -> None:
    base = "A direct later result settles the target."
    once = closed_rationale(base)
    twice = closed_rationale(once)

    assert once == twice
    assert once.count("The original target is closed") == 1


def test_closed_rationale_removes_historical_duplicates() -> None:
    duplicated = (
        "A direct later result settles the target. "
        "The original target is closed by the cited later result. "
        "The original target is closed by the cited later result."
    )

    assert closed_rationale(duplicated).count(
        "The original target is closed"
    ) == 1
