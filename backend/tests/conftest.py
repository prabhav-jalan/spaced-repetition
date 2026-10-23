from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import time_machine
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app import catalog
from app.config import DEFAULT_DATABASE_URL, get_settings
from app.db import get_engine, get_sessionmaker
from app.models import Problem

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
TEST_DATABASE_SUFFIX = "_test"


def database_url_for_tests(url: str) -> str:
    parsed = make_url(url)
    if not (parsed.database or "").endswith(TEST_DATABASE_SUFFIX):
        parsed = parsed.set(database=f"{parsed.database}{TEST_DATABASE_SUFFIX}")
    return parsed.render_as_string(hide_password=False)


# Tests commit and empty tables, so they get their own database next to the dev one
# (spaced_repetition -> spaced_repetition_test) and never touch the data you use the app with.
os.environ["DATABASE_URL"] = database_url_for_tests(
    os.environ.get("DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL
)

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


def create_database(url: URL) -> None:
    server = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        with server.connect() as connection:
            found = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            )
            if not found:
                name = connection.dialect.identifier_preparer.quote(url.database)
                connection.execute(text(f"CREATE DATABASE {name}"))
    finally:
        server.dispose()


def truncate_tables(engine: Engine) -> None:
    database = engine.url.database or ""
    if not database.endswith(TEST_DATABASE_SUFFIX):
        raise RuntimeError(
            f"Refusing to empty the tables in {database!r}: "
            f"tests only empty databases whose names end in {TEST_DATABASE_SUFFIX!r}"
        )
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE users, problems, user_problems, attempts, email_sends "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture(scope="session")
def db_engine() -> Engine:
    engine = get_engine()
    try:
        create_database(engine.url)
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
    truncate_tables(migrated_engine)


@pytest.fixture
def problems(db: Session) -> dict[str, Problem]:
    catalog.load(db, catalog.read_csv())
    return {problem.slug: problem for problem in db.scalars(select(Problem))}
