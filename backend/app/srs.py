from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

QUALITY = {"easy": 5, "struggled": 3, "failed": 1}
RESULTS = tuple(QUALITY)
PASSING_QUALITY = 3
MIN_EASE_FACTOR = Decimal("1.30")
MAX_INTERVAL_DAYS = 60
STRUGGLED_DIVISOR = 2

CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class State:
    repetitions: int
    ease_factor: Decimal
    interval_days: int


NEW_STATE = State(repetitions=0, ease_factor=Decimal("2.50"), interval_days=0)


def round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ease_change(quality: int) -> Decimal:
    misses = 5 - quality
    return Decimal("0.1") - misses * (Decimal("0.08") + misses * Decimal("0.02"))


def next_state(state: State, result: str) -> State:
    if result not in QUALITY:
        raise ValueError(f"result must be one of {', '.join(RESULTS)}; got {result!r}")
    quality = QUALITY[result]

    if quality >= PASSING_QUALITY:
        if state.repetitions == 0:
            interval = 1
        elif state.repetitions == 1:
            interval = 6
        else:
            interval = round_half_up(state.interval_days * state.ease_factor)
        interval = min(interval, MAX_INTERVAL_DAYS)
        if result == "struggled" and interval > 1:
            interval = round_half_up(Decimal(interval) / STRUGGLED_DIVISOR)
        repetitions = state.repetitions + 1
    else:
        interval = 1
        repetitions = 0

    ease_factor = max(MIN_EASE_FACTOR, state.ease_factor + ease_change(quality))
    return State(repetitions, ease_factor.quantize(CENT), interval)


def due_date(local_date: date, interval_days: int) -> date:
    if isinstance(local_date, datetime):
        raise TypeError("due_date takes the user's local date, not a datetime")
    return local_date + timedelta(days=interval_days)
