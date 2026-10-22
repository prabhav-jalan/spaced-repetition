from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.models import Problem, User, UserProblem


@dataclass(frozen=True)
class DueReview:
    problem: Problem
    due_date: date
    days_overdue: int


def due_today(db: Session, user: User, now: datetime) -> tuple[date, list[DueReview]]:
    today = clock.local_date(now, user.timezone)
    rows = db.execute(
        select(Problem, UserProblem.due_date)
        .join(UserProblem, UserProblem.problem_id == Problem.id)
        .where(UserProblem.user_id == user.id, UserProblem.due_date <= today)
        .order_by(UserProblem.due_date, Problem.id)
    )
    return today, [DueReview(problem, due, (today - due).days) for problem, due in rows]
