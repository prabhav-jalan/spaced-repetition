from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock, srs
from app.models import Attempt, Problem, User, UserProblem


class ProblemNotFound(LookupError):
    pass


@dataclass(frozen=True)
class LoggedAttempt:
    attempt: Attempt
    progress: UserProblem


def log_attempt(
    db: Session, user: User, problem_id: int, result: str, now: datetime
) -> LoggedAttempt:
    if db.get(Problem, problem_id) is None:
        raise ProblemNotFound(problem_id)
    today = clock.local_date(now, user.timezone)
    progress = db.get(UserProblem, (user.id, problem_id))

    if not _attempted_on(db, user.id, problem_id, today):
        attempt = Attempt(
            user_id=user.id,
            problem_id=problem_id,
            result=result,
            attempted_at=now,
            local_date=today,
            was_due=progress is not None and progress.due_date <= today,
            rescheduled=True,
        )
        try:
            with db.begin_nested():
                db.add(attempt)
                db.flush()
                progress = _reschedule(db, user.id, problem_id, progress, result, today, now)
            return LoggedAttempt(attempt, progress)
        except IntegrityError:
            progress = db.get(UserProblem, (user.id, problem_id), populate_existing=True)

    attempt = Attempt(
        user_id=user.id,
        problem_id=problem_id,
        result=result,
        attempted_at=now,
        local_date=today,
        was_due=False,
        rescheduled=False,
    )
    db.add(attempt)
    db.flush()
    return LoggedAttempt(attempt, progress)


def _attempted_on(db: Session, user_id: int, problem_id: int, local_date: date) -> bool:
    return db.scalar(
        select(
            exists().where(
                Attempt.user_id == user_id,
                Attempt.problem_id == problem_id,
                Attempt.local_date == local_date,
            )
        )
    )


def _reschedule(
    db: Session,
    user_id: int,
    problem_id: int,
    progress: UserProblem | None,
    result: str,
    today: date,
    now: datetime,
) -> UserProblem:
    if progress is None:
        state = srs.NEW_STATE
        progress = UserProblem(user_id=user_id, problem_id=problem_id)
        db.add(progress)
    else:
        state = srs.State(progress.repetitions, progress.ease_factor, progress.interval_days)

    after = srs.next_state(state, result)
    progress.repetitions = after.repetitions
    progress.ease_factor = after.ease_factor
    progress.interval_days = after.interval_days
    progress.due_date = srs.due_date(today, after.interval_days)
    progress.last_attempt_at = now
    db.flush()
    return progress
