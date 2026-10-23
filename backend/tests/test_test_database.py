import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.config import DEFAULT_DATABASE_URL, get_settings
from tests.conftest import database_url_for_tests, truncate_tables


def test_tests_get_their_own_database_next_to_the_dev_one():
    assert database_url_for_tests(DEFAULT_DATABASE_URL) == (
        "postgresql+psycopg://app:app@localhost:5432/spaced_repetition_test"
    )


def test_a_url_already_naming_a_test_database_is_kept():
    url = "postgresql+psycopg://u:p@db:5432/ci_test"
    assert database_url_for_tests(url) == url


def test_the_suite_never_runs_against_the_dev_database(db_engine):
    assert db_engine.url.database.endswith("_test")
    assert make_url(get_settings().database_url).database == db_engine.url.database


def test_emptying_the_tables_refuses_a_database_not_named_for_tests():
    engine = create_engine("postgresql+psycopg://nobody:nothing@127.0.0.1:1/spaced_repetition")
    try:
        with pytest.raises(RuntimeError, match="spaced_repetition"):
            truncate_tables(engine)
    finally:
        engine.dispose()
