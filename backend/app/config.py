from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache

DEFAULT_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/spaced_repetition"
DEFAULT_EMAIL_HOUR = 8
ENVIRONMENTS = ("dev", "test", "production")

ENV_VARS = (
    "DATABASE_URL",
    "SESSION_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "EMAIL_API_KEY",
    "EMAIL_FROM",
    "APP_URL",
    "ENV",
    "EMAIL_HOUR",
)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    session_secret: str = field(repr=False)
    google_client_id: str
    google_client_secret: str = field(repr=False)
    email_api_key: str = field(repr=False)
    email_from: str
    app_url: str
    env: str
    email_hour: int

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if environ is None else environ

        def get(name: str, default: str = "") -> str:
            return source.get(name, "").strip() or default

        return cls(
            database_url=get("DATABASE_URL", DEFAULT_DATABASE_URL),
            session_secret=get("SESSION_SECRET"),
            google_client_id=get("GOOGLE_CLIENT_ID"),
            google_client_secret=get("GOOGLE_CLIENT_SECRET"),
            email_api_key=get("EMAIL_API_KEY"),
            email_from=get("EMAIL_FROM"),
            app_url=get("APP_URL", "http://localhost:5173"),
            env=_parse_env(get("ENV", "dev")),
            email_hour=_parse_hour(get("EMAIL_HOUR", str(DEFAULT_EMAIL_HOUR))),
        )


def _parse_env(raw: str) -> str:
    if raw not in ENVIRONMENTS:
        raise ValueError(f"ENV must be one of {', '.join(ENVIRONMENTS)}; got {raw!r}")
    return raw


def _parse_hour(raw: str) -> int:
    if not raw.isdigit() or not 0 <= int(raw) <= 23:
        raise ValueError(f"EMAIL_HOUR must be a whole hour from 0 to 23; got {raw!r}")
    return int(raw)


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
