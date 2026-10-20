import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import clock
from tests.conftest import FROZEN_AT


def test_now_is_an_aware_utc_datetime_close_to_real_time():
    now = clock.now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert abs(now.timestamp() - time.time()) < 5


def test_frozen_clock_reads_back_the_frozen_instant(frozen_clock):
    now = clock.now()

    assert now == FROZEN_AT
    assert now.utcoffset() == timedelta(0)


def test_frozen_clock_does_not_tick(frozen_clock):
    first = clock.now()
    time.sleep(0.01)

    assert clock.now() == first


def test_frozen_clock_can_move_and_shift(frozen_clock):
    frozen_clock.move_to(datetime(2026, 11, 1, 5, 59, tzinfo=UTC))
    assert clock.now() == datetime(2026, 11, 1, 5, 59, tzinfo=UTC)

    frozen_clock.shift(timedelta(minutes=15))
    assert clock.now() == datetime(2026, 11, 1, 6, 14, tzinfo=UTC)


def test_frozen_clock_accepts_any_aware_zone(frozen_clock):
    # 08:00 in Kolkata is 02:30 UTC.
    frozen_clock.move_to(datetime(2026, 11, 2, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata")))

    assert clock.now() == datetime(2026, 11, 2, 2, 30, tzinfo=UTC)


def test_frozen_clock_rejects_naive_datetimes(frozen_clock):
    with pytest.raises(ValueError, match="aware"):
        frozen_clock.move_to(datetime(2026, 11, 2, 8, 0))


def test_frozen_instant_gives_each_zone_its_own_local_date(frozen_clock):
    # SPEC Phase 2: 23:30 UTC on Oct 20 is already Oct 21 in Kolkata, still Oct 20 in New York.
    frozen_clock.move_to(datetime(2026, 10, 20, 23, 30, tzinfo=UTC))
    now = clock.now()

    assert now.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat() == "2026-10-21"
    assert now.astimezone(ZoneInfo("America/New_York")).date().isoformat() == "2026-10-20"


@pytest.mark.parametrize(
    "zone",
    [
        "America/Los_Angeles",
        "America/New_York",
        "Europe/London",
        "Asia/Kolkata",
        "Asia/Kathmandu",
        "Pacific/Auckland",
    ],
)
def test_zone_database_has_every_zone_the_email_tests_use(zone):
    assert ZoneInfo(zone).key == zone
