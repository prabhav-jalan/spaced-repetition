from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache

DEFAULT_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/spaced_repetition"
DRIVERLESS_SCHEMES = ("postgres://", "postgresql://")
DEFAULT_EMAIL_HOUR = 8
ENVIRONMENTS = ("dev", "test", "production")
DEV_SESSION_SECRET = "dev-only-session-secret-never-use-in-production"
MIN_SESSION_SECRET_LENGTH = 32

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

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.app_url.rstrip('/')}/api/auth/google/callback"

    def check_email(self) -> None:
        missing = [
            name
            for name, value in (
                ("EMAIL_API_KEY", self.email_api_key),
                ("EMAIL_FROM", self.email_from),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"The email job needs {' and '.join(missing)}")

    def check_web(self) -> None:
        if not self.is_production:
            return
        problems = []
        if len(self.session_secret) < MIN_SESSION_SECRET_LENGTH:
            problems.append(
                f"SESSION_SECRET must be at least {MIN_SESSION_SECRET_LENGTH} characters"
            )
        if not self.google_client_id:
            problems.append("GOOGLE_CLIENT_ID must be set")
        if not self.google_client_secret:
            problems.append("GOOGLE_CLIENT_SECRET must be set")
        if not self.app_url.startswith("https://"):
            problems.append("APP_URL must start with https://")
        if problems:
            raise ValueError("In production, " + "; ".join(problems))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if environ is None else environ

        def get(name: str, default: str = "") -> str:
            return source.get(name, "").strip() or default

        env = _parse_env(get("ENV", "dev"))
        return cls(
            database_url=_parse_database_url(get("DATABASE_URL", DEFAULT_DATABASE_URL)),
            session_secret=_parse_session_secret(get("SESSION_SECRET"), env),
            google_client_id=get("GOOGLE_CLIENT_ID"),
            google_client_secret=get("GOOGLE_CLIENT_SECRET"),
            email_api_key=get("EMAIL_API_KEY"),
            email_from=get("EMAIL_FROM"),
            app_url=get("APP_URL", "http://localhost:5173"),
            env=env,
            email_hour=_parse_hour(get("EMAIL_HOUR", str(DEFAULT_EMAIL_HOUR))),
        )


def _parse_database_url(raw: str) -> str:
    for scheme in DRIVERLESS_SCHEMES:
        if raw.startswith(scheme):
            return "postgresql+psycopg://" + raw.removeprefix(scheme)
    return raw


def _parse_env(raw: str) -> str:
    if raw not in ENVIRONMENTS:
        raise ValueError(f"ENV must be one of {', '.join(ENVIRONMENTS)}; got {raw!r}")
    return raw


def _parse_session_secret(raw: str, env: str) -> str:
    return raw if env == "production" else raw or DEV_SESSION_SECRET


def _parse_hour(raw: str) -> int:
    if not raw.isdigit() or not 0 <= int(raw) <= 23:
        raise ValueError(f"EMAIL_HOUR must be a whole hour from 0 to 23; got {raw!r}")
    return int(raw)


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
