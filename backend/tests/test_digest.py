import re
import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app import catalog, digest
from app.config import Settings
from app.mailer import Email, EmailRejected
from app.models import EmailSend, Problem, User, UserProblem
from app.reviews import DueReview

pytestmark = pytest.mark.db

RESULTS_SQL = Path(__file__).resolve().parents[2] / "analysis" / "results.sql"
SETTINGS = Settings.from_env(
    {"ENV": "test", "APP_URL": "https://prep.prabhavjalan.com", "EMAIL_HOUR": "8"}
)
NOV_2_0230_UTC = datetime(2026, 11, 2, 2, 30, tzinfo=UTC)


class FakeMailer:
    def __init__(self, mode: str = "ok", delay: float = 0.0) -> None:
        self.mode = mode
        self.delay = delay
        self.sent: list[tuple[Email, str]] = []
        self._lock = threading.Lock()

    def send(self, email: Email, idempotency_key: str) -> str:
        if self.mode == "reject":
            raise EmailRejected("429 daily_quota_exceeded: You have reached your daily quota")
        time.sleep(self.delay)
        with self._lock:
            self.sent.append((email, idempotency_key))
            message_id = f"msg-{len(self.sent)}"
        if self.mode == "crash-after-send":
            raise RuntimeError("connection reset after the provider accepted the email")
        return message_id

    def recipients(self) -> list[str]:
        return [email.to for email, _ in self.sent]


@pytest.fixture
def sessions(committed_engine):
    factory = sessionmaker(bind=committed_engine, expire_on_commit=False)
    with factory() as db:
        catalog.load(db, catalog.read_csv())
        db.commit()
    return factory


def add_user(sessions, timezone, *, due=1, email_enabled=True, email=None, due_date=None) -> int:
    with sessions() as db:
        n = db.scalar(select(func.count()).select_from(User)) + 1
        user = User(
            google_sub=f"sub-{n}",
            email=email or f"user{n}@example.com",
            display_name=f"User {n}",
            timezone=timezone,
            email_enabled=email_enabled,
        )
        db.add(user)
        db.flush()
        problems = db.scalars(select(Problem).order_by(Problem.id).limit(due)).all()
        for offset, problem in enumerate(problems):
            db.add(
                UserProblem(
                    user_id=user.id,
                    problem_id=problem.id,
                    repetitions=1,
                    ease_factor=Decimal("2.50"),
                    interval_days=1,
                    due_date=due_date or date(2026, 10, 1) + timedelta(days=offset),
                    last_attempt_at=datetime(2026, 9, 30, tzinfo=UTC),
                )
            )
        db.commit()
        return user.id


def sends(sessions) -> list[EmailSend]:
    with sessions() as db:
        return db.scalars(select(EmailSend).order_by(EmailSend.user_id, EmailSend.local_date)).all()


def run_at(sessions, mailer, frozen_clock, when, settings=SETTINGS):
    frozen_clock.move_to(when)
    return digest.run(sessions, mailer, settings)


def stuck_emails_query() -> str:
    blocks = RESULTS_SQL.read_text().split("-- name: ")
    return next(block for block in blocks if block.startswith("stuck_emails")).split("\n", 1)[1]


@pytest.mark.parametrize(
    ("hour", "minute", "email_hour", "expected"),
    [
        (7, 59, 8, False),
        (8, 0, 8, True),
        (10, 59, 8, True),
        (11, 0, 8, False),
        (22, 0, 22, True),
        (23, 59, 22, True),
        (0, 30, 22, False),
        (23, 0, 23, True),
        (0, 0, 23, False),
        (0, 0, 0, True),
        (2, 59, 0, True),
        (3, 0, 0, False),
    ],
)
def test_the_send_window_is_three_hours_from_email_hour_and_stops_at_midnight(
    hour, minute, email_hour, expected
):
    local = datetime(2026, 11, 2, hour, minute, tzinfo=ZoneInfo("Asia/Kolkata"))

    assert digest.in_window(local, email_hour) is expected


def test_each_user_is_due_at_eight_in_their_own_zone(sessions, frozen_clock):
    kolkata = add_user(sessions, "Asia/Kolkata", email="kolkata@example.com")
    new_york = add_user(sessions, "America/New_York", email="new-york@example.com")
    mailer = FakeMailer()

    run_at(sessions, mailer, frozen_clock, NOV_2_0230_UTC)
    assert mailer.recipients() == ["kolkata@example.com"]

    run_at(sessions, mailer, frozen_clock, datetime(2026, 11, 2, 13, 0, tzinfo=UTC))
    assert mailer.recipients() == ["kolkata@example.com", "new-york@example.com"]
    assert [(s.user_id, s.local_date) for s in sends(sessions)] == [
        (kolkata, date(2026, 11, 2)),
        (new_york, date(2026, 11, 2)),
    ]


@pytest.mark.parametrize(
    ("instant", "due"),
    [
        (datetime(2026, 10, 31, 12, 0, tzinfo=UTC), True),
        (datetime(2026, 11, 2, 12, 0, tzinfo=UTC), False),
        (datetime(2026, 11, 2, 13, 0, tzinfo=UTC), True),
    ],
    ids=["08:00-EDT", "07:00-EST", "08:00-EST"],
)
def test_new_york_stays_at_eight_across_the_clock_change(sessions, frozen_clock, instant, due):
    add_user(sessions, "America/New_York")
    mailer = FakeMailer()

    summary = run_at(sessions, mailer, frozen_clock, instant)

    assert (summary.due, len(mailer.sent)) == ((1, 1) if due else (0, 0))


def test_seventy_two_simulated_hours_send_one_email_per_local_day_at_eight(sessions, frozen_clock):
    zones = [
        "America/Los_Angeles",
        "America/New_York",
        "Europe/London",
        "Asia/Kolkata",
        "Asia/Kathmandu",
        "Pacific/Auckland",
    ]
    users = {add_user(sessions, zone): zone for zone in zones}
    mailer = FakeMailer()
    start = datetime(2026, 10, 31, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=72)

    instant = start
    while instant < end:
        run_at(sessions, mailer, frozen_clock, instant)
        instant += timedelta(minutes=15)

    rows = sends(sessions)
    expected_total = 0
    for user_id, zone in users.items():
        tz = ZoneInfo(zone)
        expected_days = set()
        day = start.astimezone(tz).date() - timedelta(days=1)
        while day <= end.astimezone(tz).date():
            eight = datetime(day.year, day.month, day.day, 8, 0, tzinfo=tz)
            if start <= eight < end:
                expected_days.add(day)
            day += timedelta(days=1)

        expected_total += len(expected_days)
        mine = [row for row in rows if row.user_id == user_id]
        assert {row.local_date for row in mine} == expected_days, zone
        assert len(mine) == len(expected_days), zone
        for row in mine:
            local = row.sent_at.astimezone(tz)
            assert row.status == "sent", zone
            assert local.date() == row.local_date, zone
            assert (
                timedelta(0) <= local - local.replace(hour=8, minute=0) < timedelta(minutes=15)
            ), (
                zone,
                local,
            )
    assert len(rows) == len(mailer.sent) == expected_total


def test_two_runs_at_once_send_one_email_per_due_user(sessions, frozen_clock, monkeypatch):
    for zone in ("Asia/Kolkata", "Asia/Kathmandu", "Asia/Dubai"):
        add_user(sessions, zone)
    add_user(sessions, "America/New_York")
    mailer = FakeMailer(delay=0.02)
    frozen_clock.move_to(datetime(2026, 11, 2, 4, 0, tzinfo=UTC))
    start = threading.Barrier(2)
    both_found_it_due = threading.Barrier(2, timeout=10)
    real_claim = digest.claim

    def claim_together(*args, **kwargs):
        both_found_it_due.wait()
        return real_claim(*args, **kwargs)

    monkeypatch.setattr(digest, "claim", claim_together)
    summaries = []

    def one_run():
        start.wait()
        summaries.append(digest.run(sessions, mailer, SETTINGS))

    threads = [threading.Thread(target=one_run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    rows = sends(sessions)
    assert len(mailer.sent) == len(set(mailer.recipients())) == 3
    assert len(rows) == 3
    assert len({(row.user_id, row.local_date) for row in rows}) == 3
    assert [summary.due for summary in summaries] == [3, 3]
    assert sum(summary.claimed for summary in summaries) == 3

    monkeypatch.setattr(digest, "claim", real_claim)
    run_at(sessions, mailer, frozen_clock, datetime(2026, 11, 2, 5, 0, tzinfo=UTC))
    assert len(mailer.sent) == 3


def test_a_crash_after_sending_leaves_the_row_claimed_and_never_resends(sessions, frozen_clock):
    user_id = add_user(sessions, "Asia/Kolkata")
    crashing = FakeMailer(mode="crash-after-send")

    summary = run_at(sessions, crashing, frozen_clock, NOV_2_0230_UTC)

    assert (summary.claimed, summary.sent, summary.failed, summary.unknown) == (1, 0, 0, 1)
    assert [row.status for row in sends(sessions)] == ["claimed"]

    healthy = FakeMailer()
    later = run_at(sessions, healthy, frozen_clock, NOV_2_0230_UTC + timedelta(minutes=15))
    assert healthy.sent == []
    assert later.due == 0
    assert [row.status for row in sends(sessions)] == ["claimed"]

    with sessions() as db:
        stuck = db.execute(text(stuck_emails_query())).mappings().all()
    assert [(row["user_id"], row["local_date"], row["status"]) for row in stuck] == [
        (user_id, date(2026, 11, 2), "claimed")
    ]


def test_a_rejected_email_is_marked_failed_and_retried_by_the_next_run(sessions, frozen_clock):
    add_user(sessions, "Asia/Kolkata")
    rejecting = FakeMailer(mode="reject")

    first = run_at(sessions, rejecting, frozen_clock, NOV_2_0230_UTC)
    [row] = sends(sessions)
    assert (first.claimed, first.failed) == (1, 1)
    assert row.status == "failed"
    assert "daily_quota_exceeded" in row.error

    healthy = FakeMailer()
    second = run_at(sessions, healthy, frozen_clock, NOV_2_0230_UTC + timedelta(minutes=15))
    [row] = sends(sessions)
    assert (second.claimed, second.sent) == (1, 1)
    assert len(healthy.sent) == 1
    assert (row.status, row.error, row.provider_message_id) == ("sent", None, "msg-1")

    third = run_at(sessions, healthy, frozen_clock, NOV_2_0230_UTC + timedelta(minutes=30))
    assert (third.claimed, len(healthy.sent)) == (0, 1)


def test_failed_rows_stop_retrying_when_the_window_closes(sessions, frozen_clock):
    add_user(sessions, "Asia/Kolkata")
    last_run_in_window = datetime(2026, 11, 2, 5, 15, tzinfo=UTC)
    run_at(sessions, FakeMailer(mode="reject"), frozen_clock, last_run_in_window)

    healthy = FakeMailer()
    run_at(sessions, healthy, frozen_clock, last_run_in_window + timedelta(minutes=15))

    assert healthy.sent == []
    assert [row.status for row in sends(sessions)] == ["failed"]


def test_each_attempt_gets_its_own_idempotency_key(sessions, frozen_clock):
    user_id = add_user(sessions, "Asia/Kolkata")
    run_at(sessions, FakeMailer(mode="reject"), frozen_clock, NOV_2_0230_UTC)
    healthy = FakeMailer()

    run_at(sessions, healthy, frozen_clock, NOV_2_0230_UTC + timedelta(minutes=15))

    [(_, key)] = healthy.sent
    assert key == f"digest/{user_id}/2026-11-02/024500"


def test_quiet_days_send_nothing_and_leave_no_row(sessions, frozen_clock):
    add_user(sessions, "Asia/Kolkata", due=0)
    add_user(sessions, "Asia/Kolkata", email_enabled=False)
    add_user(sessions, "Asia/Kolkata", due_date=date(2026, 11, 3))
    mailer = FakeMailer()

    summary = run_at(sessions, mailer, frozen_clock, NOV_2_0230_UTC)

    assert (summary.checked, summary.due) == (2, 0)
    assert mailer.sent == []
    assert sends(sessions) == []


def test_the_email_lists_due_problems_with_links_back_to_the_app(sessions, frozen_clock):
    add_user(sessions, "Asia/Kolkata", due=3, email="prabhav@example.com")
    mailer = FakeMailer()

    run_at(sessions, mailer, frozen_clock, NOV_2_0230_UTC)

    [(email, _)] = mailer.sent
    assert email.to == "prabhav@example.com"
    assert email.subject == "3 problems to review today: Contains Duplicate, Valid Anagram +1"
    for part in (email.html, email.text):
        assert "https://leetcode.com/problems/contains-duplicate/" in part
        assert "https://leetcode.com/problems/valid-anagram/" in part
        assert "https://leetcode.com/problems/two-sum/" in part
        assert "https://prep.prabhavjalan.com/?src=email" in part
        assert "https://prep.prabhavjalan.com/settings" in part
    assert email.text.index("Contains Duplicate") < email.text.index("Two Sum")
    assert "<html" in email.html and "<html" not in email.text


def problem(title: str) -> Problem:
    return Problem(
        id=1,
        slug="x",
        title=title,
        url="https://leetcode.com/problems/x/?a=1&b=2",
        difficulty="easy",
        topic="Arrays & Hashing",
    )


@pytest.mark.parametrize(
    ("titles", "subject"),
    [
        (["Two Sum"], "1 problem to review today: Two Sum"),
        (["Two Sum", "Valid Anagram"], "2 problems to review today: Two Sum, Valid Anagram"),
        (["A", "B", "C", "D"], "4 problems to review today: A, B +2"),
    ],
)
def test_subject_lines(titles, subject):
    assert digest.subject_line(titles) == subject


def test_the_html_part_escapes_titles_and_urls():
    user = User(id=1, email="x@example.com", display_name="x", timezone="UTC")
    reviews = [DueReview(problem("A <b> & C"), date(2026, 11, 1), 1)]

    email = digest.compose(user, reviews, "https://prep.prabhavjalan.com", 8)

    assert "A &lt;b&gt; &amp; C" in email.html
    assert "?a=1&amp;b=2" in email.html
    assert "A <b> & C" in email.text


def test_each_run_logs_one_summary_line(sessions, frozen_clock, caplog):
    add_user(sessions, "Asia/Kolkata")
    add_user(sessions, "America/New_York")

    with caplog.at_level("INFO", logger="app.digest"):
        run_at(sessions, FakeMailer(), frozen_clock, NOV_2_0230_UTC)

    lines = [record.getMessage() for record in caplog.records if record.name == "app.digest"]
    assert len(lines) == 1
    assert re.fullmatch(
        r"digest run: checked=2 due=1 claimed=1 sent=1 failed=0 unknown=0 duration=\d+\.\d{2}s",
        lines[0],
    )


def test_the_command_line_runs_once_and_exits_zero(
    sessions, frozen_clock, monkeypatch, fresh_settings
):
    add_user(sessions, "Asia/Kolkata")
    mailer = FakeMailer()
    monkeypatch.setenv("EMAIL_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "Prep reviews <reviews@mail.prabhavjalan.com>")
    monkeypatch.setattr(digest, "ResendMailer", lambda api_key, sender: mailer)
    frozen_clock.move_to(NOV_2_0230_UTC)

    assert digest.main(["run"]) == 0
    assert len(mailer.sent) == 1


def test_the_command_line_exits_nonzero_when_a_send_fails(
    sessions, frozen_clock, monkeypatch, fresh_settings
):
    add_user(sessions, "Asia/Kolkata")
    monkeypatch.setenv("EMAIL_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "reviews@mail.prabhavjalan.com")
    monkeypatch.setattr(digest, "ResendMailer", lambda api_key, sender: FakeMailer("reject"))
    frozen_clock.move_to(NOV_2_0230_UTC)

    assert digest.main(["run"]) == 1


@pytest.mark.parametrize("missing", ["EMAIL_API_KEY", "EMAIL_FROM"])
def test_the_command_line_needs_resend_settings(monkeypatch, fresh_settings, missing):
    monkeypatch.setenv("EMAIL_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "reviews@mail.prabhavjalan.com")
    monkeypatch.setenv(missing, "")

    with pytest.raises(ValueError, match=missing):
        digest.main(["run"])


def test_the_email_names_the_configured_send_hour(sessions, frozen_clock):
    add_user(sessions, "Asia/Kolkata")
    nine_am = Settings.from_env(
        {"ENV": "test", "APP_URL": "https://prep.prabhavjalan.com", "EMAIL_HOUR": "9"}
    )
    mailer = FakeMailer()

    run_at(sessions, mailer, frozen_clock, NOV_2_0230_UTC + timedelta(hours=1), nine_am)

    [(email, _)] = mailer.sent
    assert "at 9 a.m. your time" in email.text
    assert "at 9 a.m. your time" in email.html


@pytest.mark.parametrize(
    ("days_overdue", "html_detail", "text_detail"),
    [
        (0, "Easy · Arrays &amp; Hashing</span>", "(Easy, Arrays & Hashing)"),
        (
            1,
            "Easy · Arrays &amp; Hashing · 1 day overdue</span>",
            "(Easy, Arrays & Hashing, 1 day overdue)",
        ),
        (
            5,
            "Easy · Arrays &amp; Hashing · 5 days overdue</span>",
            "(Easy, Arrays & Hashing, 5 days overdue)",
        ),
    ],
)
def test_each_problem_says_how_overdue_it_is(days_overdue, html_detail, text_detail):
    user = User(id=1, email="x@example.com", display_name="x", timezone="UTC")
    reviews = [DueReview(problem("Two Sum"), date(2026, 11, 1), days_overdue)]

    email = digest.compose(user, reviews, "https://prep.prabhavjalan.com", 8)

    assert html_detail in email.html
    assert text_detail in email.text


@pytest.mark.parametrize(
    ("hour", "label"), [(0, "12 a.m."), (8, "8 a.m."), (12, "12 p.m."), (13, "1 p.m.")]
)
def test_the_send_hour_reads_like_a_clock(hour, label):
    user = User(id=1, email="x@example.com", display_name="x", timezone="UTC")
    reviews = [DueReview(problem("Two Sum"), date(2026, 11, 1), 0)]

    email = digest.compose(user, reviews, "https://prep.prabhavjalan.com", hour)

    assert f"at {label} your time" in email.text
