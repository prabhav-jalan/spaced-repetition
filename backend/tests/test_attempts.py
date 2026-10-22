import threading
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import attempts
from app.models import Attempt, Problem, User, UserProblem

NOW = datetime(2026, 10, 20, 13, 0, tzinfo=UTC)


def committed_user_and_problem(engine, existing_progress: bool) -> tuple[int, int]:
    with sessionmaker(bind=engine)() as db:
        user = User(
            google_sub="dev:tap@example.com",
            email="tap@example.com",
            display_name="tap",
            timezone="America/New_York",
        )
        problem = Problem(
            slug="two-sum",
            title="Two Sum",
            url="https://leetcode.com/problems/two-sum/",
            difficulty="easy",
            topic="Arrays & Hashing",
        )
        db.add_all([user, problem])
        db.flush()
        if existing_progress:
            db.add(
                UserProblem(
                    user_id=user.id,
                    problem_id=problem.id,
                    repetitions=2,
                    ease_factor=Decimal("2.70"),
                    interval_days=6,
                    due_date=date(2026, 10, 20),
                    last_attempt_at=datetime(2026, 10, 14, 13, 0, tzinfo=UTC),
                )
            )
        db.commit()
        return user.id, problem.id


@pytest.mark.parametrize("existing_progress", [False, True], ids=["new-problem", "due-problem"])
def test_a_double_tap_reschedules_only_once(committed_engine, existing_progress):
    user_id, problem_id = committed_user_and_problem(committed_engine, existing_progress)
    Session = sessionmaker(bind=committed_engine)
    first_tap, second_tap = Session(), Session()
    outcome = {}

    attempts.log_attempt(first_tap, first_tap.get(User, user_id), problem_id, "easy", NOW)

    def tap_again():
        logged = attempts.log_attempt(
            second_tap, second_tap.get(User, user_id), problem_id, "easy", NOW
        )
        second_tap.commit()
        outcome["rescheduled"] = logged.attempt.rescheduled
        outcome["was_due"] = logged.attempt.was_due
        outcome["due_date"] = logged.progress.due_date

    thread = threading.Thread(target=tap_again)
    thread.start()
    thread.join(timeout=0.5)
    assert thread.is_alive(), "the second tap should wait for the first one's transaction"

    first_tap.commit()
    thread.join(timeout=10)
    assert not thread.is_alive()
    first_tap.close()
    second_tap.close()

    with Session() as db:
        logged = db.execute(select(Attempt.rescheduled).order_by(Attempt.id)).scalars().all()
        progress = db.get(UserProblem, (user_id, problem_id))
    assert logged == [True, False]
    assert outcome == {"rescheduled": False, "was_due": False, "due_date": progress.due_date}
    assert progress.repetitions == (3 if existing_progress else 1)


def test_logging_an_unknown_problem_raises(db, problems):
    user = User(
        google_sub="dev:x@example.com", email="x@example.com", display_name="x", timezone="UTC"
    )
    db.add(user)
    db.flush()

    with pytest.raises(attempts.ProblemNotFound):
        attempts.log_attempt(db, user, -1, "easy", NOW)
