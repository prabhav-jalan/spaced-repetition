from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import Base, get_session

pytestmark = pytest.mark.db

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def test_database_answers(db_engine):
    with db_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


def test_database_is_postgres_16(db_engine):
    with db_engine.connect() as connection:
        version = connection.execute(text("SHOW server_version_num")).scalar_one()

    assert int(version) // 10000 == 16


def test_connections_use_utc(db_engine):
    with db_engine.connect() as connection:
        assert connection.execute(text("SHOW timezone")).scalar_one() == "UTC"


def test_get_session_yields_a_working_session(db_engine):
    sessions = get_session()
    session = next(sessions)
    try:
        assert session.execute(text("SELECT 2")).scalar_one() == 2
    finally:
        sessions.close()


def test_alembic_upgrades_to_head_and_models_match_migrations(db_engine):
    config = Config(str(ALEMBIC_INI))

    command.upgrade(config, "head")
    command.check(config)


def test_constraint_names_follow_the_naming_convention():
    convention = Base.metadata.naming_convention

    assert convention["pk"] == "pk_%(table_name)s"
    assert {"ix", "uq", "ck", "fk", "pk"} <= set(convention)
