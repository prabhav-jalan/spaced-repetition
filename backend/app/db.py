from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_db_engine(url: str, **kwargs: Any) -> Engine:
    """Every connection runs in UTC, so timestamptz values come back as UTC instants."""
    return create_engine(
        url,
        connect_args={"options": "-c timezone=UTC"},
        pool_pre_ping=True,
        **kwargs,
    )


@lru_cache
def get_engine() -> Engine:
    return create_db_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards."""
    with get_sessionmaker()() as session:
        yield session
