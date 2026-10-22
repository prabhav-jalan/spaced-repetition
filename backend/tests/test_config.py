from pathlib import Path

import pytest

from app.config import DEFAULT_DATABASE_URL, ENV_VARS, Settings, get_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

FULL_ENV = {
    "DATABASE_URL": "postgresql+psycopg://u:p@host:5432/db",
    "SESSION_SECRET": "session-secret-0123456789-abcdefghij",
    "GOOGLE_CLIENT_ID": "client-id",
    "GOOGLE_CLIENT_SECRET": "client-secret",
    "EMAIL_API_KEY": "re_123",
    "EMAIL_FROM": "reviews@mail.prabhavjalan.com",
    "APP_URL": "https://prep.prabhavjalan.com",
    "ENV": "production",
    "EMAIL_HOUR": "9",
}


def test_reads_every_variable_from_the_environment():
    settings = Settings.from_env(FULL_ENV)

    assert settings.database_url == "postgresql+psycopg://u:p@host:5432/db"
    assert settings.session_secret == "session-secret-0123456789-abcdefghij"
    assert settings.google_client_id == "client-id"
    assert settings.google_client_secret == "client-secret"
    assert settings.email_api_key == "re_123"
    assert settings.email_from == "reviews@mail.prabhavjalan.com"
    assert settings.app_url == "https://prep.prabhavjalan.com"
    assert settings.env == "production"
    assert settings.is_production
    assert settings.email_hour == 9


def test_defaults_suit_local_development():
    settings = Settings.from_env({})

    assert settings.env == "dev"
    assert not settings.is_production
    assert settings.email_hour == 8
    assert settings.database_url == DEFAULT_DATABASE_URL


@pytest.mark.parametrize("raw", ["", "  "])
def test_blank_email_hour_means_the_default(raw):
    assert Settings.from_env({"EMAIL_HOUR": raw}).email_hour == 8


@pytest.mark.parametrize("raw", ["-1", "24", "eight", "8.5"])
def test_rejects_an_invalid_email_hour(raw):
    with pytest.raises(ValueError, match="EMAIL_HOUR"):
        Settings.from_env({"EMAIL_HOUR": raw})


@pytest.mark.parametrize("raw", ["prod", "Production", "staging"])
def test_rejects_an_unknown_env(raw):
    # A typo must not quietly run production as dev (Phase 3's dev login keys off ENV=dev).
    with pytest.raises(ValueError, match="ENV"):
        Settings.from_env({"ENV": raw})


def test_secrets_stay_out_of_repr():
    shown = repr(Settings.from_env(FULL_ENV))

    for secret in ("session-secret-0123", "client-secret", "re_123", "u:p@"):
        assert secret not in shown


def test_get_settings_reads_os_environ(monkeypatch, fresh_settings):
    monkeypatch.setenv("EMAIL_HOUR", "7")

    assert get_settings().email_hour == 7


def test_env_example_lists_exactly_the_settings_variables():
    keys = {
        line.split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert keys == set(ENV_VARS)


@pytest.mark.parametrize("secret", ["", "too-short"])
def test_production_needs_a_long_session_secret(secret):
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings.from_env(FULL_ENV | {"SESSION_SECRET": secret})


def test_dev_and_test_fall_back_to_a_fixed_session_secret():
    dev = Settings.from_env({}).session_secret
    test = Settings.from_env({"ENV": "test"}).session_secret

    assert dev == test
    assert len(dev) >= 32
