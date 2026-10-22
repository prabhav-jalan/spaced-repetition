from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from zoneinfo import available_timezones

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.models import Attempt, User, UserProblem


@dataclass(frozen=True)
class Profile:
    user: User
    local_date: date
    attempts: int
    problems: int
    due_today: int


@lru_cache
def _time_zones() -> frozenset[str]:
    return frozenset(available_timezones())


def is_valid_time_zone(name: str) -> bool:
    return name in _time_zones()


def profile(db: Session, user: User, now: datetime) -> Profile:
    today = clock.local_date(now, user.timezone)

    def count(model, *conditions) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*conditions))

    return Profile(
        user=user,
        local_date=today,
        attempts=count(Attempt, Attempt.user_id == user.id),
        problems=count(UserProblem, UserProblem.user_id == user.id),
        due_today=count(UserProblem, UserProblem.user_id == user.id, UserProblem.due_date <= today),
    )


def update(
    db: Session, user: User, timezone: str | None = None, email_enabled: bool | None = None
) -> None:
    if timezone is not None:
        if not is_valid_time_zone(timezone):
            raise ValueError(f"unknown time zone {timezone!r}")
        user.timezone = timezone
    if email_enabled is not None:
        user.email_enabled = email_enabled
    db.flush()
