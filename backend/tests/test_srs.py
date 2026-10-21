import random
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app import srs
from app.srs import NEW_STATE, State, due_date, next_state

EXACT_SEQUENCES = {
    "easy x5 from new": (
        ["easy"] * 5,
        [1, 6, 16, 45, 60],
        ["2.60", "2.70", "2.80", "2.90", "3.00"],
        [1, 2, 3, 4, 5],
    ),
    "struggled x4 from new": (
        ["struggled"] * 4,
        [1, 3, 4, 4],
        ["2.36", "2.22", "2.08", "1.94"],
        [1, 2, 3, 4],
    ),
    "easy x3 then failed": (
        ["easy", "easy", "easy", "failed"],
        [1, 6, 16, 1],
        ["2.60", "2.70", "2.80", "2.26"],
        [1, 2, 3, 0],
    ),
    "failed x4 from new": (
        ["failed"] * 4,
        [1, 1, 1, 1],
        ["1.96", "1.42", "1.30", "1.30"],
        [0, 0, 0, 0],
    ),
}


@pytest.mark.parametrize(
    ("results", "intervals", "ease_factors", "repetitions"),
    EXACT_SEQUENCES.values(),
    ids=EXACT_SEQUENCES.keys(),
)
def test_exact_sequences_from_the_spec(results, intervals, ease_factors, repetitions):
    states = []
    state = NEW_STATE
    for result in results:
        state = next_state(state, result)
        states.append(state)

    assert [s.interval_days for s in states] == intervals
    assert [s.ease_factor for s in states] == [Decimal(ef) for ef in ease_factors]
    assert [s.repetitions for s in states] == repetitions


def test_new_problems_start_at_0_repetitions_ease_2_50_interval_0():
    assert NEW_STATE == State(repetitions=0, ease_factor=Decimal("2.50"), interval_days=0)


def test_state_is_immutable():
    with pytest.raises(FrozenInstanceError):
        NEW_STATE.interval_days = 6


def test_buttons_map_to_supermemo_quality():
    assert srs.QUALITY == {"easy": 5, "struggled": 3, "failed": 1}
    assert srs.RESULTS == ("easy", "struggled", "failed")


@pytest.mark.parametrize(
    ("result", "ease_factor"),
    [("easy", "2.60"), ("struggled", "2.36"), ("failed", "1.96")],
)
def test_ease_factor_changes_by_button(result, ease_factor):
    state = State(repetitions=3, ease_factor=Decimal("2.50"), interval_days=10)

    assert next_state(state, result).ease_factor == Decimal(ease_factor)


def test_round_half_up_unlike_pythons_round():
    assert round(130.5) == 130
    assert srs.round_half_up(Decimal("130.5")) == 131
    assert srs.round_half_up(Decimal("130.49")) == 130


@pytest.mark.parametrize(
    ("interval_days", "ease_factor", "expected"),
    [(5, "2.50", 13), (3, "1.50", 5), (10, "2.45", 25)],
)
def test_next_interval_rounds_half_up(interval_days, ease_factor, expected):
    state = State(repetitions=2, ease_factor=Decimal(ease_factor), interval_days=interval_days)

    assert next_state(state, "easy").interval_days == expected


def test_struggled_halves_the_second_interval():
    state = State(repetitions=1, ease_factor=Decimal("2.50"), interval_days=1)

    assert next_state(state, "easy").interval_days == 6
    assert next_state(state, "struggled").interval_days == 3


def test_struggled_halves_after_the_cap_so_it_still_comes_back_sooner():
    state = State(repetitions=5, ease_factor=Decimal("3.00"), interval_days=60)

    assert next_state(state, "easy").interval_days == srs.MAX_INTERVAL_DAYS
    assert next_state(state, "struggled").interval_days == srs.MAX_INTERVAL_DAYS // 2


def test_failed_resets_repetitions_and_interval():
    state = State(repetitions=7, ease_factor=Decimal("2.80"), interval_days=45)

    assert next_state(state, "failed") == State(
        repetitions=0, ease_factor=Decimal("2.26"), interval_days=1
    )


def test_unknown_result_is_rejected():
    with pytest.raises(ValueError, match="result"):
        next_state(NEW_STATE, "skipped")


SEQUENCE_COUNT = 1_000


def random_sequences() -> list[list[str]]:
    rng = random.Random(42)
    return [
        [rng.choice(srs.RESULTS) for _ in range(rng.randint(1, 30))] for _ in range(SEQUENCE_COUNT)
    ]


SEQUENCES = random_sequences()


def walk(sequence):
    state = NEW_STATE
    for step, result in enumerate(sequence):
        yield sequence[:step], state
        state = next_state(state, result)
    yield sequence, state


def test_property_tests_use_1000_seeded_sequences():
    assert len(SEQUENCES) == SEQUENCE_COUNT
    assert random_sequences() == SEQUENCES


def test_ease_factor_never_drops_below_1_30():
    for sequence in SEQUENCES:
        for history, state in walk(sequence):
            assert state.ease_factor >= Decimal("1.30"), history


def test_ease_factor_is_always_exact_to_the_cent():
    for sequence in SEQUENCES:
        for history, state in walk(sequence):
            assert state.ease_factor.as_tuple().exponent == -2, history
            assert state.ease_factor < 100, history


def test_interval_is_always_between_1_and_60():
    for sequence in SEQUENCES:
        for history, state in walk(sequence):
            if history:
                assert 1 <= state.interval_days <= 60, history


def test_failed_always_gives_interval_1_and_repetitions_0():
    for sequence in SEQUENCES:
        for history, state in walk(sequence):
            after = next_state(state, "failed")
            assert (after.interval_days, after.repetitions) == (1, 0), history


def test_struggled_never_gives_a_longer_interval_than_easy():
    for sequence in SEQUENCES:
        for history, state in walk(sequence):
            struggled = next_state(state, "struggled").interval_days
            easy = next_state(state, "easy").interval_days
            assert struggled <= easy, history


@pytest.mark.parametrize(
    ("start", "days", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 1)),
        (date(2026, 2, 28), 1, date(2026, 3, 1)),
        (date(2028, 2, 28), 1, date(2028, 2, 29)),
        (date(2026, 4, 30), 6, date(2026, 5, 6)),
        (date(2026, 12, 31), 1, date(2027, 1, 1)),
        (date(2026, 12, 15), 60, date(2027, 2, 13)),
    ],
)
def test_due_date_adds_days_across_month_and_year_ends(start, days, expected):
    assert due_date(start, days) == expected


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (date(2026, 3, 7), date(2026, 3, 8)),
        (date(2026, 3, 28), date(2026, 3, 29)),
        (date(2026, 4, 4), date(2026, 4, 5)),
        (date(2026, 10, 24), date(2026, 10, 25)),
        (date(2026, 10, 31), date(2026, 11, 1)),
    ],
    ids=["us-spring", "eu-spring", "nz-autumn", "eu-autumn", "us-autumn"],
)
def test_due_date_ignores_clock_changes(start, expected):
    assert due_date(start, 1) == expected


def test_due_date_is_exactly_n_calendar_days_later_all_year():
    start = date(2026, 1, 1)
    while start.year == 2026:
        for days in range(1, srs.MAX_INTERVAL_DAYS + 1):
            due = due_date(start, days)
            assert type(due) is date
            assert due - start == timedelta(days=days)
        start += timedelta(days=1)


def test_due_date_refuses_a_datetime():
    with pytest.raises(TypeError, match="date"):
        due_date(datetime(2026, 10, 20, 23, 30, tzinfo=UTC), 1)
