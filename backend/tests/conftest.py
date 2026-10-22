from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import time_machine
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import catalog
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.models import Problem

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

# A Tuesday at noon UTC: 08:00 in New York (EDT), 17:30 in Kolkata.
FROZEN_AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class FrozenClock:
    def __init__(self, coordinates: time_machine.Coordinates) -> None:
        self._coordinates = coordinates

    def move_to(self, when: datetime) -> None:
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError(f"frozen_clock needs an aware datetime, got naive {when!r}")
        self._coordinates.move_to(when)

    def shift(self, delta: timedelta) -> None:
        self._coordinates.shift(delta)


@pytest.fixture
def frozen_clock() -> Iterator[FrozenClock]:
    traveller = time_machine.travel(FROZEN_AT, tick=False)
    coordinates = traveller.start()
    try:
        yield FrozenClock(coordinates)
    finally:
        traveller.stop()


def _clear_caches() -> None:
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def fresh_settings() -> Iterator[None]:
    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture(scope="session")
def db_engine() -> Engine:
    engine = get_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.fail(
            "PostgreSQL isn't reachable at DATABASE_URL "
            f"({engine.url.render_as_string(hide_password=True)}). "
            "Start it with `docker compose up -d db`.\n"
            f"{exc.orig}",
            pytrace=False,
        )
    return engine


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


@pytest.fixture(scope="session")
def migrated_engine(db_engine: Engine) -> Engine:
    command.upgrade(alembic_config(), "head")
    return db_engine


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Session]:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def committed_engine(migrated_engine: Engine) -> Iterator[Engine]:
    yield migrated_engine
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE users, problems, user_problems, attempts, email_sends "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def problems(db: Session) -> dict[str, Problem]:
    catalog.load(db, catalog.read_csv())
    return {problem.slug: problem for problem in db.scalars(select(Problem))}
