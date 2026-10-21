from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column

from app import clock, srs
from app.db import Base

DIFFICULTIES = ("easy", "medium", "hard")
EMAIL_STATUSES = ("claimed", "sent", "failed")


def one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str]
    display_name: Mapped[str]
    timezone: Mapped[str]
    email_enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)


class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = (CheckConstraint(one_of("difficulty", DIFFICULTIES), name="difficulty"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True)
    title: Mapped[str]
    url: Mapped[str]
    difficulty: Mapped[str]
    topic: Mapped[str]


class UserProblem(Base):
    __tablename__ = "user_problems"
    __table_args__ = (
        CheckConstraint("repetitions >= 0", name="repetitions_non_negative"),
        CheckConstraint(f"ease_factor >= {srs.MIN_EASE_FACTOR}", name="ease_factor_min"),
        CheckConstraint(
            f"interval_days BETWEEN 1 AND {srs.MAX_INTERVAL_DAYS}", name="interval_days_range"
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), primary_key=True)
    repetitions: Mapped[int]
    ease_factor: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    interval_days: Mapped[int]
    due_date: Mapped[date]
    last_attempt_at: Mapped[datetime]


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint(one_of("result", srs.RESULTS), name="result"),
        Index(
            "uq_attempts_one_reschedule_per_local_day",
            "user_id",
            "problem_id",
            "local_date",
            unique=True,
            postgresql_where=text("rescheduled"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"))
    result: Mapped[str]
    attempted_at: Mapped[datetime]
    local_date: Mapped[date]
    was_due: Mapped[bool]
    rescheduled: Mapped[bool]


class EmailSend(Base):
    __tablename__ = "email_sends"
    __table_args__ = (
        CheckConstraint(one_of("status", EMAIL_STATUSES), name="status"),
        CheckConstraint("review_count > 0", name="review_count_positive"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(primary_key=True)
    status: Mapped[str]
    review_count: Mapped[int]
    claimed_at: Mapped[datetime]
    sent_at: Mapped[datetime | None]
    provider_message_id: Mapped[str | None]
    error: Mapped[str | None]
