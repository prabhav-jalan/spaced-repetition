from collections import Counter

import pytest
from sqlalchemy import func, select

from app import catalog
from app.models import DIFFICULTIES, Problem

EXPECTED_TOPIC_COUNTS = {
    "Arrays & Hashing": 9,
    "Two Pointers": 5,
    "Sliding Window": 6,
    "Stack": 7,
    "Binary Search": 7,
    "Linked List": 11,
    "Trees": 15,
    "Tries": 3,
    "Heap / Priority Queue": 7,
    "Backtracking": 9,
    "Graphs": 13,
    "Advanced Graphs": 6,
    "1-D Dynamic Programming": 12,
    "2-D Dynamic Programming": 11,
    "Greedy": 8,
    "Intervals": 6,
    "Math & Geometry": 8,
    "Bit Manipulation": 7,
}


def snapshot(db) -> dict[str, tuple]:
    rows = db.execute(select(Problem.slug, Problem.id, Problem.title, Problem.topic)).all()
    return {slug: tuple(rest) for slug, *rest in rows}


def test_csv_has_the_neetcode_150_across_18_topics():
    rows = catalog.read_csv()

    assert len(rows) == 150
    assert Counter(row["topic"] for row in rows) == EXPECTED_TOPIC_COUNTS
    assert sum(EXPECTED_TOPIC_COUNTS.values()) == 150


def test_csv_follows_the_roadmap_order():
    rows = catalog.read_csv()

    assert list(dict.fromkeys(row["topic"] for row in rows)) == list(EXPECTED_TOPIC_COUNTS)
    assert [row["slug"] for row in rows[:3]] == ["contains-duplicate", "valid-anagram", "two-sum"]


def test_csv_rows_link_to_leetcode_and_store_no_statements():
    rows = catalog.read_csv()

    assert len({row["slug"] for row in rows}) == 150
    assert len({row["title"] for row in rows}) == 150
    for row in rows:
        assert set(row) == {"title", "slug", "url", "difficulty", "topic"}
        assert row["url"] == f"https://leetcode.com/problems/{row['slug']}/"
        assert row["difficulty"] in DIFFICULTIES
        assert row["title"].strip() == row["title"] != ""


def test_loading_twice_changes_nothing(db):
    assert catalog.load(db, catalog.read_csv()) == 150
    before = snapshot(db)

    assert catalog.load(db, catalog.read_csv()) == 150

    assert snapshot(db) == before
    assert db.scalar(select(func.count()).select_from(Problem)) == 150


def test_loading_updates_a_changed_problem_in_place(db):
    rows = catalog.read_csv()
    catalog.load(db, rows)
    two_sum_id = snapshot(db)["two-sum"][0]

    renamed = [
        row | {"title": "Two Sum (renamed)"} if row["slug"] == "two-sum" else row for row in rows
    ]
    catalog.load(db, renamed)
    db.expire_all()

    assert snapshot(db)["two-sum"][:2] == (two_sum_id, "Two Sum (renamed)")


def test_command_line_load_is_idempotent(committed_engine, capsys):
    catalog.main(["load"])
    catalog.main(["load"])

    with committed_engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(Problem))
    assert count == 150
    assert capsys.readouterr().out.count("Loaded 150 problems") == 2


def test_command_line_needs_a_command():
    with pytest.raises(SystemExit):
        catalog.main([])
