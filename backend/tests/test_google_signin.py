import time
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy import func, select

from app import auth
from app.config import Settings
from app.db import get_session
from app.main import create_app
from app.models import User

pytestmark = pytest.mark.db

CLIENT_ID = "test-client.apps.googleusercontent.com"
DEV = {
    "ENV": "dev",
    "GOOGLE_CLIENT_ID": CLIENT_ID,
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "APP_URL": "http://localhost:5173",
}
PRODUCTION = DEV | {
    "ENV": "production",
    "SESSION_SECRET": "s" * 32,
    "APP_URL": "https://prep.prabhavjalan.com",
}
ISSUER = "https://accounts.google.com"
METADATA = {
    "issuer": ISSUER,
    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_endpoint": "https://oauth2.googleapis.com/token",
    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    "id_token_signing_alg_values_supported": ["RS256"],
}


class FakeGoogle:
    def __init__(self) -> None:
        self.key = RSAKey.generate_key(2048, {"kid": "google-key", "use": "sig", "alg": "RS256"})
        self.signing_key = self.key
        self.nonce: str | None = None
        self.claims: dict = {}
        self.token_status = 200
        self.token_requests: list[dict[str, str]] = []
        self.transport = httpx2.MockTransport(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url).split("?")[0]
        if url == auth.GOOGLE_METADATA_URL:
            return httpx2.Response(200, json=METADATA)
        if url == METADATA["jwks_uri"]:
            return httpx2.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if url == METADATA["token_endpoint"]:
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if self.token_status != 200:
                return httpx2.Response(self.token_status, text="Google is having a bad day")
            return httpx2.Response(200, json=self.token_response())
        return httpx2.Response(404)

    def token_response(self) -> dict:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "100000000000000000001",
            "email": "prabhav@example.com",
            "email_verified": True,
            "name": "Prabhav Jalan",
            "iat": now,
            "exp": now + 3600,
            "nonce": self.nonce,
        } | self.claims
        header = {"alg": "RS256", "kid": "google-key"}
        return {
            "access_token": "ya29.test-access-token",
            "token_type": "Bearer",
            "expires_in": 3599,
            "scope": "openid email profile",
            "id_token": jwt.encode(header, claims, self.signing_key),
        }


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


def make_client(db, google, env, **client_kwargs) -> TestClient:
    app = create_app(Settings.from_env(env), google_transport=google.transport)

    def same_session():
        yield db

    app.dependency_overrides[get_session] = same_session
    return TestClient(app, **client_kwargs)


@pytest.fixture
def client(db, problems, google, frozen_clock) -> TestClient:
    return make_client(db, google, DEV)


def start(client, timezone="Asia/Kolkata") -> dict[str, str]:
    params = {} if timezone is None else {"timezone": timezone}
    response = client.get("/api/auth/google/login", params=params, follow_redirects=False)
    assert response.status_code == 302, response.text
    return {k: v[0] for k, v in parse_qs(urlparse(response.headers["location"]).query).items()}


def callback(client, **params):
    return client.get("/api/auth/google/callback", params=params, follow_redirects=False)


def google_sign_in(client, google, timezone="Asia/Kolkata", **claims):
    sent = start(client, timezone)
    google.nonce = sent["nonce"]
    google.claims = claims
    return callback(client, code="4/test-code", state=sent["state"])


def user_count(db) -> int:
    return db.scalar(select(func.count()).select_from(User))


def test_login_sends_the_browser_to_google_with_our_callback(client):
    response = client.get(
        "/api/auth/google/login", params={"timezone": "Asia/Kolkata"}, follow_redirects=False
    )

    location = urlparse(response.headers["location"])
    query = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert response.status_code == 302
    assert (
        f"{location.scheme}://{location.netloc}{location.path}"
        == METADATA["authorization_endpoint"]
    )
    assert query["client_id"] == CLIENT_ID
    assert query["response_type"] == "code"
    assert query["scope"] == "openid email profile"
    assert query["redirect_uri"] == "http://localhost:5173/api/auth/google/callback"
    assert query["state"] and query["nonce"]


def test_first_sign_in_creates_the_user_with_the_browsers_time_zone(client, google, db):
    response = google_sign_in(client, google, timezone="Asia/Kolkata", sub="111")

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/"
    me = client.get("/api/me").json()
    assert (me["email"], me["display_name"], me["timezone"]) == (
        "prabhav@example.com",
        "Prabhav Jalan",
        "Asia/Kolkata",
    )
    assert db.scalar(select(User.google_sub).where(User.id == me["id"])) == "111"
    exchange = google.token_requests[0]
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["code"] == "4/test-code"
    assert exchange["redirect_uri"] == "http://localhost:5173/api/auth/google/callback"


def test_signing_in_again_keeps_the_account_and_time_zone_but_refreshes_the_profile(
    client, google, db
):
    google_sign_in(client, google, timezone="Asia/Kolkata", sub="111")
    first = client.get("/api/me").json()
    client.post("/api/logout")

    google_sign_in(
        client,
        google,
        timezone="America/New_York",
        sub="111",
        email="prabhav.jalan@example.com",
        name="Prabhav J.",
    )
    again = client.get("/api/me").json()

    assert again["id"] == first["id"]
    assert again["timezone"] == "Asia/Kolkata"
    assert (again["email"], again["display_name"]) == ("prabhav.jalan@example.com", "Prabhav J.")
    assert user_count(db) == 1


@pytest.mark.parametrize("zone", [None, "", "Mars/Olympus_Mons", "undefined"])
def test_a_missing_or_unknown_browser_time_zone_falls_back_to_utc(client, google, zone):
    google_sign_in(client, google, timezone=zone)

    assert client.get("/api/me").json()["timezone"] == "UTC"


def test_the_legacy_zone_name_chrome_reports_is_kept_as_sent(client, google):
    google_sign_in(client, google, timezone="Asia/Calcutta")

    assert client.get("/api/me").json()["timezone"] == "Asia/Calcutta"


def test_a_name_falls_back_to_the_email(client, google):
    google_sign_in(client, google, name=None, email="first.last@example.com")

    assert client.get("/api/me").json()["display_name"] == "first.last"


def test_cancelling_at_google_returns_to_the_app_signed_out(client, google, db):
    sent = start(client)

    response = callback(client, error="access_denied", state=sent["state"])

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/?signin=cancelled"
    assert client.get("/api/me").status_code == 401
    assert google.token_requests == []
    assert user_count(db) == 0


@pytest.mark.parametrize("state", ["forged-state", None])
def test_a_forged_or_missing_state_is_refused_before_any_token_exchange(client, google, db, state):
    start(client)

    params = {"code": "4/test-code"} | ({} if state is None else {"state": state})
    response = callback(client, **params)

    assert response.headers["location"] == "http://localhost:5173/?signin=failed"
    assert google.token_requests == []
    assert client.get("/api/me").status_code == 401
    assert user_count(db) == 0


def test_a_callback_without_starting_sign_in_is_refused(client, google):
    response = callback(client, code="4/test-code", state="never-issued")

    assert response.headers["location"] == "http://localhost:5173/?signin=failed"


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "someone-elses-client.apps.googleusercontent.com"},
        {"iss": "https://evil.example.com"},
        {"nonce": "replayed-nonce"},
        {"exp": "an hour ago"},
        {"email_verified": False},
        {"email": None},
    ],
    ids=[
        "wrong-audience",
        "wrong-issuer",
        "wrong-nonce",
        "expired",
        "unverified-email",
        "no-email",
    ],
)
def test_an_untrustworthy_id_token_is_refused(client, google, db, claims):
    if claims.get("exp") == "an hour ago":
        claims = {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}

    response = google_sign_in(client, google, **claims)

    assert response.headers["location"] == "http://localhost:5173/?signin=failed"
    assert client.get("/api/me").status_code == 401
    assert user_count(db) == 0


def test_an_id_token_signed_with_someone_elses_key_is_refused(client, google, db):
    google.signing_key = RSAKey.generate_key(2048, {"kid": "google-key", "alg": "RS256"})

    response = google_sign_in(client, google)

    assert response.headers["location"] == "http://localhost:5173/?signin=failed"
    assert user_count(db) == 0


@pytest.mark.parametrize("status", [400, 500, 503])
def test_google_failing_to_exchange_the_code_is_a_failed_sign_in(client, google, db, status):
    google.token_status = status

    response = google_sign_in(client, google)

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/?signin=failed"
    assert user_count(db) == 0


def test_in_dev_google_sign_in_takes_over_the_dev_account_with_the_same_email(
    client, google, db, problems
):
    dev = client.post(
        "/api/dev/login", json={"email": "prabhav@example.com", "timezone": "Asia/Kolkata"}
    ).json()
    client.post("/api/attempts", json={"problem_id": problems["two-sum"].id, "result": "easy"})
    client.post("/api/logout")

    google_sign_in(client, google, sub="111", email="Prabhav@Example.com", timezone="UTC")
    me = client.get("/api/me").json()

    assert me["id"] == dev["id"]
    assert me["timezone"] == "Asia/Kolkata"
    assert me["totals"]["attempts"] == 1
    assert db.scalar(select(User.google_sub).where(User.id == dev["id"])) == "111"
    assert user_count(db) == 1


def test_production_never_takes_over_dev_accounts(db, problems, google, frozen_clock):
    dev_user = User(
        google_sub="dev:prabhav@example.com",
        email="prabhav@example.com",
        display_name="prabhav",
        timezone="Asia/Kolkata",
    )
    db.add(dev_user)
    db.flush()
    client = make_client(db, google, PRODUCTION, base_url="https://testserver")

    response = google_sign_in(client, google, sub="111")

    assert response.headers["location"] == "https://prep.prabhavjalan.com/"
    assert client.get("/api/me").json()["id"] != dev_user.id
    assert (
        db.scalar(select(User.google_sub).where(User.id == dev_user.id))
        == "dev:prabhav@example.com"
    )
    assert user_count(db) == 2


def test_signing_in_with_google_replaces_a_dev_session(client, google):
    client.post("/api/dev/login", json={"email": "someone@example.com", "timezone": "UTC"})

    google_sign_in(client, google, sub="222", email="prabhav@example.com")

    assert client.get("/api/me").json()["email"] == "prabhav@example.com"


def test_production_session_cookie_is_secure_http_only_and_same_site_lax(db, google, frozen_clock):
    client = make_client(db, google, PRODUCTION, base_url="https://testserver")

    response = client.get("/api/auth/google/login", follow_redirects=False)

    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("session=")
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (DEV, {"google": True, "dev": True}),
        ({"ENV": "dev"}, {"google": False, "dev": True}),
        (PRODUCTION, {"google": True, "dev": False}),
    ],
    ids=["dev-with-google", "dev-without-google", "production"],
)
def test_providers_tell_the_sign_in_page_what_to_show(db, google, env, expected):
    client = make_client(db, google, env, base_url="https://testserver")

    assert client.get("/api/auth/providers").json() == expected


@pytest.mark.parametrize("path", ["/api/auth/google/login", "/api/auth/google/callback"])
def test_google_routes_say_so_when_google_isnt_configured(db, google, path):
    client = make_client(db, google, {"ENV": "dev"})

    assert client.get(path, follow_redirects=False).status_code == 503


@pytest.mark.parametrize(
    ("missing", "variable"),
    [
        ({"SESSION_SECRET": ""}, "SESSION_SECRET"),
        ({"SESSION_SECRET": "too-short"}, "SESSION_SECRET"),
        ({"GOOGLE_CLIENT_ID": ""}, "GOOGLE_CLIENT_ID"),
        ({"GOOGLE_CLIENT_SECRET": ""}, "GOOGLE_CLIENT_SECRET"),
        ({"APP_URL": "http://prep.prabhavjalan.com"}, "APP_URL"),
    ],
)
def test_the_production_web_app_refuses_to_start_misconfigured(missing, variable):
    with pytest.raises(ValueError, match=variable):
        create_app(Settings.from_env(PRODUCTION | missing))
