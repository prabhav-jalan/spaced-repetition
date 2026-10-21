from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import count

import pytest
from alembic import command
from sqlalchemy import delete, func, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app import srs
from app.models import Attempt, EmailSend, Problem, User, UserProblem
from tests.conftest import FROZEN_AT, alembic_config

pytestmark = pytest.mark.db

TABLES = {"users", "problems", "user_problems", "attempts", "email_sends"}
INSTANT = datetime(2026, 10, 20, 23, 30, tzinfo=UTC)
LOCAL_DATE = date(2026, 10, 21)
_numbers = count(1)


def add_user(db, **values) -> User:
    n = next(_numbers)
    fields = {
        "google_sub": f"google-{n}",
        "email": f"user{n}@example.com",
        "display_name": f"User {n}",
        "timezone": "Asia/Kolkata",
    }
    user = User(**(fields | values))
    db.add(user)
    db.flush()
    return user


def problem_row(**values) -> dict:
    n = next(_numbers)
    return {
        "slug": f"problem-{n}",
        "title": f"Problem {n}",
        "url": f"https://leetcode.com/problems/problem-{n}/",
        "difficulty": "easy",
        "topic": "Arrays & Hashing",
    } | values


def add_problem(db, **values) -> Problem:
    problem = Problem(**problem_row(**values))
    db.add(problem)
    db.flush()
    return problem


def user_problem_row(user, problem, **values) -> dict:
    return {
        "user_id": user.id,
        "problem_id": problem.id,
        "repetitions": 1,
        "ease_factor": Decimal("2.50"),
        "interval_days": 1,
        "due_date": LOCAL_DATE + timedelta(days=1),
        "last_attempt_at": INSTANT,
    } | values


def attempt_row(user, problem, **values) -> dict:
    return {
        "user_id": user.id,
        "problem_id": problem.id,
        "result": "easy",
        "attempted_at": INSTANT,
        "local_date": LOCAL_DATE,
        "was_due": False,
        "rescheduled": True,
    } | values


def email_send_row(user, **values) -> dict:
    return {
        "user_id": user.id,
        "local_date": LOCAL_DATE,
        "status": "claimed",
        "review_count": 3,
        "claimed_at": INSTANT,
    } | values


def violated_constraint(db, model, row) -> str:
    with pytest.raises(IntegrityError) as caught:
        db.execute(insert(model).values(**row))
    return caught.value.orig.diag.constraint_name


@pytest.fixture
def user(db) -> User:
    return add_user(db)


@pytest.fixture
def problem(db) -> Problem:
    return add_problem(db)


def test_migration_downgrades_and_upgrades_cleanly(migrated_engine):
    config = alembic_config()

    command.downgrade(config, "base")
    assert TABLES.isdisjoint(inspect(migrated_engine).get_table_names())

    command.upgrade(config, "head")
    assert TABLES <= set(inspect(migrated_engine).get_table_names())


def test_instants_are_timestamptz_and_days_are_dates(migrated_engine):
    with migrated_engine.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
            )
        ).all()
    types = {(table, column): data_type for table, column, data_type in columns}

    instants = {key for key in types if key[1].endswith("_at")}
    days = {key for key in types if key[1].endswith("date")}
    assert instants == {
        ("users", "created_at"),
        ("user_problems", "last_attempt_at"),
        ("attempts", "attempted_at"),
        ("email_sends", "claimed_at"),
        ("email_sends", "sent_at"),
    }
    assert days == {
        ("user_problems", "due_date"),
        ("attempts", "local_date"),
        ("email_sends", "local_date"),
    }
    assert {types[key] for key in instants} == {"timestamp with time zone"}
    assert {types[key] for key in days} == {"date"}
    assert "timestamp without time zone" not in types.values()


def test_ease_factor_is_numeric_4_2(migrated_engine):
    with migrated_engine.connect() as connection:
        precision, scale = connection.execute(
            text(
                "SELECT numeric_precision, numeric_scale FROM information_schema.columns "
                "WHERE table_name = 'user_problems' AND column_name = 'ease_factor'"
            )
        ).one()

    assert (precision, scale) == (4, 2)


def test_valid_rows_round_trip_exactly(db, user, problem):
    db.add_all(
        [
            UserProblem(**user_problem_row(user, problem, ease_factor=Decimal("2.36"))),
            Attempt(**attempt_row(user, problem)),
            EmailSend(**email_send_row(user)),
        ]
    )
    db.flush()
    db.expire_all()

    stored = db.get(UserProblem, (user.id, problem.id))
    attempt = db.scalars(select(Attempt).where(Attempt.user_id == user.id)).one()
    send = db.get(EmailSend, (user.id, LOCAL_DATE))
    assert str(stored.ease_factor) == "2.36"
    assert attempt.attempted_at == INSTANT
    assert attempt.attempted_at.utcoffset() == timedelta(0)
    assert attempt.local_date == LOCAL_DATE
    assert send.status == "claimed"
    assert send.sent_at is None


def test_new_user_gets_created_at_from_the_clock_and_emails_on(db, frozen_clock):
    user = add_user(db)
    db.refresh(user)

    assert user.created_at == FROZEN_AT
    assert user.email_enabled is True


def test_boundary_and_allowed_values_are_accepted(db, user):
    db.execute(
        insert(UserProblem),
        [
            user_problem_row(
                user,
                add_problem(db),
                repetitions=0,
                interval_days=1,
                ease_factor=srs.MIN_EASE_FACTOR,
            ),
            user_problem_row(user, add_problem(db), interval_days=srs.MAX_INTERVAL_DAYS),
        ],
    )
    db.execute(
        insert(Attempt),
        [attempt_row(user, add_problem(db), result=result) for result in srs.RESULTS],
    )
    db.execute(
        insert(EmailSend),
        [
            email_send_row(user, local_date=LOCAL_DATE + timedelta(days=n), status=status)
            for n, status in enumerate(("claimed", "sent", "failed"))
        ],
    )
    db.execute(insert(Problem), [problem_row(difficulty=d) for d in ("easy", "medium", "hard")])


@pytest.mark.parametrize(
    ("model", "overrides", "constraint"),
    [
        (
            UserProblem,
            {"ease_factor": srs.MIN_EASE_FACTOR - Decimal("0.01")},
            "ck_user_problems_ease_factor_min",
        ),
        (UserProblem, {"interval_days": 0}, "ck_user_problems_interval_days_range"),
        (
            UserProblem,
            {"interval_days": srs.MAX_INTERVAL_DAYS + 1},
            "ck_user_problems_interval_days_range",
        ),
        (UserProblem, {"repetitions": -1}, "ck_user_problems_repetitions_non_negative"),
        (Attempt, {"result": "skipped"}, "ck_attempts_result"),
        (Attempt, {"result": "Easy"}, "ck_attempts_result"),
        (Problem, {"difficulty": "Easy"}, "ck_problems_difficulty"),
        (EmailSend, {"status": "queued"}, "ck_email_sends_status"),
        (EmailSend, {"review_count": 0}, "ck_email_sends_review_count_positive"),
    ],
    ids=lambda value: value.__name__ if isinstance(value, type) else None,
)
def test_check_constraints_reject_bad_values(db, user, problem, model, overrides, constraint):
    valid = {
        UserProblem: user_problem_row(user, problem),
        Attempt: attempt_row(user, problem),
        Problem: problem_row(),
        EmailSend: email_send_row(user),
    }[model]

    assert violated_constraint(db, model, valid | overrides) == constraint


def test_one_user_problems_row_per_user_and_problem(db, user, problem):
    db.execute(insert(UserProblem).values(**user_problem_row(user, problem)))

    row = user_problem_row(user, problem, interval_days=6)
    assert violated_constraint(db, UserProblem, row) == "pk_user_problems"


def test_one_email_sends_row_per_user_and_local_date(db, user):
    other_user = add_user(db)
    db.execute(
        insert(EmailSend),
        [
            email_send_row(user),
            email_send_row(user, local_date=LOCAL_DATE + timedelta(days=1)),
            email_send_row(other_user),
        ],
    )

    row = email_send_row(user, status="sent")
    assert violated_constraint(db, EmailSend, row) == "pk_email_sends"


def test_google_sub_is_unique(db, user):
    row = {"google_sub": user.google_sub, "email": "x@example.com", "display_name": "X"}

    assert violated_constraint(db, User, row | {"timezone": "UTC"}) == "uq_users_google_sub"


def test_problem_slug_is_unique(db, problem):
    assert violated_constraint(db, Problem, problem_row(slug=problem.slug)) == "uq_problems_slug"


def test_only_one_rescheduling_attempt_per_problem_per_local_day(db, user, problem):
    db.execute(
        insert(Attempt),
        [
            attempt_row(user, problem, rescheduled=True),
            attempt_row(user, problem, rescheduled=False),
            attempt_row(user, problem, rescheduled=False, result="failed"),
            attempt_row(user, problem, rescheduled=True, local_date=LOCAL_DATE + timedelta(days=1)),
            attempt_row(add_user(db), problem, rescheduled=True),
        ],
    )

    row = attempt_row(user, problem, rescheduled=True, result="struggled")
    assert violated_constraint(db, Attempt, row) == "uq_attempts_one_reschedule_per_local_day"


@pytest.mark.parametrize(
    ("column", "constraint"),
    [("user_id", "fk_attempts_user_id_users"), ("problem_id", "fk_attempts_problem_id_problems")],
)
def test_attempts_must_point_at_a_real_user_and_problem(db, user, problem, column, constraint):
    row = attempt_row(user, problem) | {column: -1}

    assert violated_constraint(db, Attempt, row) == constraint


def test_deleting_a_user_deletes_their_rows_but_keeps_the_problem(db, user, problem):
    db.execute(insert(UserProblem).values(**user_problem_row(user, problem)))
    db.execute(insert(Attempt).values(**attempt_row(user, problem)))
    db.execute(insert(EmailSend).values(**email_send_row(user)))

    db.execute(delete(User).where(User.id == user.id))

    for model in (UserProblem, Attempt, EmailSend):
        remaining = select(func.count()).select_from(model).where(model.user_id == user.id)
        assert db.scalar(remaining) == 0, model.__name__
    assert db.get(Problem, problem.id) is not None


def test_a_problem_with_history_cannot_be_deleted(db, user, problem):
    db.execute(insert(Attempt).values(**attempt_row(user, problem)))

    with pytest.raises(IntegrityError) as caught:
        db.execute(delete(Problem).where(Problem.id == problem.id))
    assert caught.value.orig.diag.constraint_name == "fk_attempts_problem_id_problems"
