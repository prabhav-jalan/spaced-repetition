from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import Settings
from app.db import get_session
from app.main import create_app
from app.models import Attempt, User, UserProblem

pytestmark = pytest.mark.db

LATE_UTC = datetime(2026, 10, 20, 23, 30, tzinfo=UTC)
NEW_YORK_9AM = datetime(2026, 10, 20, 13, 0, tzinfo=UTC)


@pytest.fixture
def app(db, problems):
    app = create_app(Settings.from_env({"ENV": "dev"}))

    def same_session():
        yield db

    app.dependency_overrides[get_session] = same_session
    return app


@pytest.fixture
def client(app, frozen_clock):
    return TestClient(app)


def sign_in(client, email="me@example.com", timezone="America/New_York") -> dict:
    response = client.post("/api/dev/login", json={"email": email, "timezone": timezone})
    assert response.status_code == 200, response.text
    return response.json()


def log(client, problem, result) -> dict:
    response = client.post("/api/attempts", json={"problem_id": problem.id, "result": result})
    assert response.status_code == 201, response.text
    return response.json()


def schedule(db, user_id, problem, due, interval_days=6):
    db.add(
        UserProblem(
            user_id=user_id,
            problem_id=problem.id,
            repetitions=2,
            ease_factor=Decimal("2.60"),
            interval_days=interval_days,
            due_date=due,
            last_attempt_at=datetime.combine(
                due - timedelta(days=interval_days), datetime.min.time(), UTC
            ),
        )
    )
    db.flush()


def test_a_late_utc_attempt_counts_from_each_users_local_date(app, problems, frozen_clock):
    frozen_clock.move_to(LATE_UTC)
    kolkata, new_york = TestClient(app), TestClient(app)
    sign_in(kolkata, "kolkata@example.com", "Asia/Kolkata")
    sign_in(new_york, "new-york@example.com", "America/New_York")

    in_kolkata = log(kolkata, problems["two-sum"], "easy")
    in_new_york = log(new_york, problems["two-sum"], "easy")

    assert (in_kolkata["local_date"], in_kolkata["due_date"]) == ("2026-10-21", "2026-10-22")
    assert (in_new_york["local_date"], in_new_york["due_date"]) == ("2026-10-20", "2026-10-21")


def test_the_same_instant_gives_users_in_different_zones_different_today_lists(
    app, db, problems, frozen_clock
):
    frozen_clock.move_to(LATE_UTC)
    kolkata, new_york = TestClient(app), TestClient(app)
    for client, email, zone in (
        (kolkata, "kolkata@example.com", "Asia/Kolkata"),
        (new_york, "new-york@example.com", "America/New_York"),
    ):
        user = sign_in(client, email, zone)
        schedule(db, user["id"], problems["two-sum"], due=date(2026, 10, 21))

    in_kolkata = kolkata.get("/api/reviews/today").json()
    in_new_york = new_york.get("/api/reviews/today").json()

    assert in_kolkata["local_date"] == "2026-10-21"
    assert [review["problem"]["slug"] for review in in_kolkata["reviews"]] == ["two-sum"]
    assert in_new_york["local_date"] == "2026-10-20"
    assert in_new_york["reviews"] == []


def test_a_second_attempt_the_same_local_day_is_logged_but_does_not_reschedule(
    client, db, problems, frozen_clock
):
    frozen_clock.move_to(NEW_YORK_9AM)
    user = sign_in(client)

    first = log(client, problems["two-sum"], "easy")
    frozen_clock.shift(timedelta(hours=10))
    second = log(client, problems["two-sum"], "failed")

    assert (first["rescheduled"], second["rescheduled"]) == (True, False)
    assert (second["due_date"], second["interval_days"]) == ("2026-10-21", 1)
    assert (first["due_date"], first["interval_days"]) == ("2026-10-21", 1)
    logged = db.scalars(select(Attempt).where(Attempt.user_id == user["id"]).order_by(Attempt.id))
    assert [(a.result, a.local_date, a.rescheduled) for a in logged] == [
        ("easy", date(2026, 10, 20), True),
        ("failed", date(2026, 10, 20), False),
    ]


@pytest.mark.parametrize(
    ("zone", "first_utc", "second_utc", "second_reschedules"),
    [
        ("Asia/Kolkata", datetime(2026, 10, 20, 18, 0), datetime(2026, 10, 20, 18, 45), True),
        ("America/New_York", datetime(2026, 10, 20, 23, 30), datetime(2026, 10, 21, 0, 30), False),
    ],
    ids=["kolkata-midnight-same-utc-day", "utc-midnight-same-new-york-day"],
)
def test_a_new_day_starts_at_the_users_midnight_not_utcs(
    client, problems, frozen_clock, zone, first_utc, second_utc, second_reschedules
):
    frozen_clock.move_to(first_utc.replace(tzinfo=UTC))
    sign_in(client, timezone=zone)
    log(client, problems["two-sum"], "easy")

    frozen_clock.move_to(second_utc.replace(tzinfo=UTC))
    second = log(client, problems["two-sum"], "easy")

    assert second["rescheduled"] is second_reschedules


def test_reviewing_a_due_problem_is_marked_was_due(client, db, problems, frozen_clock):
    frozen_clock.move_to(NEW_YORK_9AM)
    user = sign_in(client)
    schedule(db, user["id"], problems["valid-anagram"], due=date(2026, 10, 19))

    due = log(client, problems["valid-anagram"], "struggled")
    new = log(client, problems["two-sum"], "easy")

    assert (due["was_due"], new["was_due"]) == (True, False)
    assert (due["interval_days"], due["due_date"]) == (8, "2026-10-28")


def test_today_lists_the_most_overdue_first_and_skips_future_reviews(
    client, db, problems, frozen_clock
):
    frozen_clock.move_to(NEW_YORK_9AM)
    user = sign_in(client)
    for slug, due in [
        ("two-sum", date(2026, 10, 20)),
        ("valid-anagram", date(2026, 10, 18)),
        ("contains-duplicate", date(2026, 10, 21)),
        ("group-anagrams", date(2026, 10, 19)),
    ]:
        schedule(db, user["id"], problems[slug], due)

    today = client.get("/api/reviews/today").json()

    assert today["local_date"] == "2026-10-20"
    assert [(r["problem"]["slug"], r["due_date"], r["days_overdue"]) for r in today["reviews"]] == [
        ("valid-anagram", "2026-10-18", 2),
        ("group-anagrams", "2026-10-19", 1),
        ("two-sum", "2026-10-20", 0),
    ]
    assert today["reviews"][0]["problem"] == {
        "id": problems["valid-anagram"].id,
        "slug": "valid-anagram",
        "title": "Valid Anagram",
        "url": "https://leetcode.com/problems/valid-anagram/",
        "difficulty": "easy",
        "topic": "Arrays & Hashing",
    }


def test_logging_moves_a_problem_off_todays_list(client, db, problems, frozen_clock):
    frozen_clock.move_to(NEW_YORK_9AM)
    user = sign_in(client)
    schedule(db, user["id"], problems["two-sum"], due=date(2026, 10, 20))

    log(client, problems["two-sum"], "failed")

    assert client.get("/api/reviews/today").json()["reviews"] == []


def test_catalog_lists_all_150_in_roadmap_order_with_my_status(client, db, problems, frozen_clock):
    frozen_clock.move_to(NEW_YORK_9AM)
    user = sign_in(client)
    log(client, problems["two-sum"], "easy")
    schedule(db, user["id"], problems["valid-anagram"], due=date(2026, 10, 20))

    catalog = client.get("/api/problems").json()
    by_slug = {item["slug"]: item for item in catalog}

    assert len(catalog) == 150
    assert [item["slug"] for item in catalog[:3]] == [
        "contains-duplicate",
        "valid-anagram",
        "two-sum",
    ]
    assert (by_slug["two-sum"]["status"], by_slug["two-sum"]["due_date"]) == (
        "scheduled",
        "2026-10-21",
    )
    assert (by_slug["valid-anagram"]["status"], by_slug["valid-anagram"]["due_date"]) == (
        "due",
        "2026-10-20",
    )
    assert (by_slug["contains-duplicate"]["status"], by_slug["contains-duplicate"]["due_date"]) == (
        "new",
        None,
    )


@pytest.mark.parametrize(
    ("query", "slugs"),
    [
        ({"topic": "Two Pointers"}, 5),
        ({"q": "ANAGRAM"}, ["valid-anagram", "group-anagrams"]),
        ({"topic": "Arrays & Hashing", "q": "two"}, ["two-sum"]),
        ({"q": "100%"}, []),
        ({"topic": "Nope"}, []),
    ],
)
def test_catalog_filters_by_topic_and_title(client, query, slugs):
    sign_in(client)

    found = [item["slug"] for item in client.get("/api/problems", params=query).json()]

    assert (len(found) if isinstance(slugs, int) else found) == slugs


def test_me_shows_profile_local_date_and_totals(client, db, problems, frozen_clock):
    frozen_clock.move_to(LATE_UTC)
    user = sign_in(client, "kolkata@example.com", "Asia/Kolkata")
    schedule(db, user["id"], problems["valid-anagram"], due=date(2026, 10, 21))
    log(client, problems["two-sum"], "easy")
    log(client, problems["two-sum"], "easy")

    me = client.get("/api/me").json()

    assert me == {
        "id": user["id"],
        "email": "kolkata@example.com",
        "display_name": "kolkata",
        "timezone": "Asia/Kolkata",
        "email_enabled": True,
        "local_date": "2026-10-21",
        "totals": {"attempts": 2, "problems": 2, "due_today": 1},
    }


def test_patch_me_changes_time_zone_and_emails(client, frozen_clock):
    frozen_clock.move_to(LATE_UTC)
    sign_in(client, timezone="America/New_York")

    response = client.patch("/api/me", json={"timezone": "Asia/Kolkata", "email_enabled": False})

    assert response.status_code == 200
    assert response.json()["timezone"] == "Asia/Kolkata"
    assert response.json()["local_date"] == "2026-10-21"
    me = client.get("/api/me").json()
    assert (me["timezone"], me["email_enabled"]) == ("Asia/Kolkata", False)


def test_patch_me_can_change_one_field_at_a_time(client):
    sign_in(client, timezone="Europe/London")

    client.patch("/api/me", json={"email_enabled": False})
    me = client.patch("/api/me", json={"timezone": "Asia/Kathmandu"}).json()

    assert (me["timezone"], me["email_enabled"]) == ("Asia/Kathmandu", False)


@pytest.mark.parametrize("zone", ["Mars/Olympus_Mons", "", "UTC+5", "America", "../etc/passwd"])
def test_patch_me_rejects_unknown_time_zones(client, zone):
    sign_in(client, timezone="Europe/London")

    response = client.patch("/api/me", json={"timezone": zone})

    assert response.status_code == 422
    assert client.get("/api/me").json()["timezone"] == "Europe/London"


@pytest.mark.parametrize(
    "body", [{"nickname": "x"}, {"timezone": None}, {"email_enabled": "maybe"}]
)
def test_patch_me_rejects_bad_bodies(client, body):
    sign_in(client)

    assert client.patch("/api/me", json=body).status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/me", None),
        ("PATCH", "/api/me", {"email_enabled": False}),
        ("GET", "/api/reviews/today", None),
        ("GET", "/api/problems", None),
        ("POST", "/api/attempts", {"problem_id": 1, "result": "easy"}),
    ],
)
def test_every_endpoint_needs_a_signed_in_user(client, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


def test_logging_an_unknown_problem_is_404(client):
    sign_in(client)

    response = client.post("/api/attempts", json={"problem_id": -1, "result": "easy"})

    assert response.status_code == 404


@pytest.mark.parametrize("result", ["skipped", "Easy", ""])
def test_logging_an_unknown_result_is_422(client, problems, result):
    sign_in(client)

    response = client.post(
        "/api/attempts", json={"problem_id": problems["two-sum"].id, "result": result}
    )

    assert response.status_code == 422


def test_dev_login_creates_the_user_once_with_the_browsers_time_zone(client):
    first = sign_in(client, " Me@Example.com ", "Asia/Kolkata")
    again = sign_in(client, "me@example.com", "America/New_York")

    assert first["id"] == again["id"]
    assert (first["email"], first["display_name"]) == ("me@example.com", "me")
    assert again["timezone"] == "Asia/Kolkata"


def test_chrome_in_india_can_sign_in_with_the_legacy_zone_name(client, problems, frozen_clock):
    frozen_clock.move_to(LATE_UTC)
    sign_in(client, timezone="Asia/Calcutta")

    logged = log(client, problems["two-sum"], "easy")

    assert logged["local_date"] == "2026-10-21"


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "timezone": "UTC"},
        {"email": "me@example.com", "timezone": "Not/AZone"},
        {"email": "me@example.com"},
    ],
)
def test_dev_login_validates_email_and_time_zone(client, body):
    assert client.post("/api/dev/login", json=body).status_code == 422


def test_session_cookie_is_http_only_and_same_site_lax(client):
    response = client.post("/api/dev/login", json={"email": "me@example.com", "timezone": "UTC"})

    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("session=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_signing_out_ends_the_session(client):
    sign_in(client)

    assert client.post("/api/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_a_session_for_a_deleted_user_is_rejected(client, db):
    user = sign_in(client)
    db.execute(delete(User).where(User.id == user["id"]))

    assert client.get("/api/me").status_code == 401


def test_production_has_no_dev_login(db):
    settings = Settings.from_env(
        {
            "ENV": "production",
            "SESSION_SECRET": "s" * 32,
            "GOOGLE_CLIENT_ID": "client-id",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "APP_URL": "https://prep.prabhavjalan.com",
        }
    )
    client = TestClient(create_app(settings), base_url="https://testserver")

    response = client.post("/api/dev/login", json={"email": "me@example.com", "timezone": "UTC"})

    assert response.status_code == 404
