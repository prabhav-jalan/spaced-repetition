from datetime import UTC, datetime


def now() -> datetime:
    """The current instant, as an aware datetime in UTC."""
    return datetime.now(UTC)
