from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def now() -> datetime:
    """The current instant, as an aware datetime in UTC."""
    return datetime.now(UTC)


def local_date(instant: datetime, timezone: str) -> date:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(f"local_date needs an aware datetime, got naive {instant!r}")
    return instant.astimezone(ZoneInfo(timezone)).date()
