import argparse
import html
import logging
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app import clock, reviews
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.mailer import Email, EmailRejected, Mailer, ResendMailer
from app.models import EmailSend, User
from app.reviews import DueReview

WINDOW_HOURS = 3
TEMPLATES = Path(__file__).parent / "templates"

logger = logging.getLogger("app.digest")


@dataclass
class Summary:
    checked: int = 0
    due: int = 0
    claimed: int = 0
    sent: int = 0
    failed: int = 0
    unknown: int = 0
    seconds: float = 0.0

    def line(self) -> str:
        return (
            f"digest run: checked={self.checked} due={self.due} claimed={self.claimed} "
            f"sent={self.sent} failed={self.failed} unknown={self.unknown} "
            f"duration={self.seconds:.2f}s"
        )


def in_window(local: datetime, email_hour: int) -> bool:
    return email_hour <= local.hour < min(email_hour + WINDOW_HOURS, 24)


def due_now(
    db: Session, user: User, now: datetime, email_hour: int
) -> tuple[date, list[DueReview]] | None:
    if not in_window(now.astimezone(ZoneInfo(user.timezone)), email_hour):
        return None
    today, due = reviews.due_today(db, user, now)
    if not due:
        return None
    existing = db.get(EmailSend, (user.id, today), populate_existing=True)
    if existing is not None and existing.status != "failed":
        return None
    return today, due


def claim(db: Session, user_id: int, local_date: date, review_count: int, now: datetime) -> bool:
    claimed = db.execute(
        insert(EmailSend)
        .values(
            user_id=user_id,
            local_date=local_date,
            status="claimed",
            review_count=review_count,
            claimed_at=now,
        )
        .on_conflict_do_nothing(index_elements=[EmailSend.user_id, EmailSend.local_date])
        .returning(EmailSend.user_id)
    ).first()
    if claimed is None:
        claimed = db.execute(
            update(EmailSend)
            .where(
                EmailSend.user_id == user_id,
                EmailSend.local_date == local_date,
                EmailSend.status == "failed",
            )
            .values(status="claimed", review_count=review_count, claimed_at=now, error=None)
            .returning(EmailSend.user_id)
        ).first()
    db.commit()
    return claimed is not None


def idempotency_key(user_id: int, local_date: date, claimed_at: datetime) -> str:
    return (
        f"digest/{user_id}/{local_date.isoformat()}/{claimed_at.astimezone(ZoneInfo('UTC')):%H%M%S}"
    )


def deliver(
    db: Session,
    mailer: Mailer,
    user: User,
    local_date: date,
    due: list[DueReview],
    claimed_at: datetime,
    settings: Settings,
) -> str:
    email = compose(user, due, settings.app_url, settings.email_hour)
    try:
        message_id = mailer.send(email, idempotency_key(user.id, local_date, claimed_at))
    except EmailRejected as error:
        _finish(db, user.id, local_date, status="failed", error=str(error)[:1000])
        return "failed"
    except Exception:
        logger.exception(
            "Email for user %s on %s may or may not have gone out; leaving it claimed",
            user.id,
            local_date,
        )
        return "unknown"
    _finish(
        db, user.id, local_date, status="sent", sent_at=clock.now(), provider_message_id=message_id
    )
    return "sent"


def _finish(db: Session, user_id: int, local_date: date, **values) -> None:
    db.execute(
        update(EmailSend)
        .where(
            EmailSend.user_id == user_id,
            EmailSend.local_date == local_date,
            EmailSend.status == "claimed",
        )
        .values(**values)
    )
    db.commit()


def run(sessions: sessionmaker[Session], mailer: Mailer, settings: Settings) -> Summary:
    started = time.perf_counter()
    now = clock.now()
    summary = Summary()
    with sessions() as db:
        user_ids = db.scalars(select(User.id).where(User.email_enabled).order_by(User.id)).all()
        for user_id in user_ids:
            user = db.get(User, user_id)
            summary.checked += 1
            plan = due_now(db, user, now, settings.email_hour)
            if plan is None:
                continue
            local_date, due = plan
            summary.due += 1
            if not claim(db, user.id, local_date, len(due), now):
                continue
            summary.claimed += 1
            outcome = deliver(db, mailer, user, local_date, due, now, settings)
            setattr(summary, outcome, getattr(summary, outcome) + 1)
    summary.seconds = time.perf_counter() - started
    logger.info(summary.line())
    return summary


def subject_line(titles: list[str]) -> str:
    count = len(titles)
    noun = "problem" if count == 1 else "problems"
    more = f" +{count - 2}" if count > 2 else ""
    return f"{count} {noun} to review today: {', '.join(titles[:2])}{more}"


def _clock_hour(hour: int) -> str:
    return f"{hour % 12 or 12} {'a.m.' if hour < 12 else 'p.m.'}"


def _overdue(days: int, separator: str) -> str:
    if days == 0:
        return ""
    return f"{separator}1 day overdue" if days == 1 else f"{separator}{days} days overdue"


def compose(user: User, due: list[DueReview], app_url: str, email_hour: int) -> Email:
    base = app_url.rstrip("/")
    count = len(due)
    heading = f"{count} {'problem' if count == 1 else 'problems'} to review today"
    html_rows = "\n".join(
        f'        <li style="margin:0 0 8px"><a href="{html.escape(r.problem.url)}" '
        f'style="color:#2f5bd3;font-weight:600">{html.escape(r.problem.title)}</a> '
        f'<span style="color:#6b6862;font-size:14px">{r.problem.difficulty.capitalize()} · '
        f"{html.escape(r.problem.topic)}{_overdue(r.days_overdue, ' · ')}</span></li>"
        for r in due
    )
    text_rows = "\n".join(
        f"- {r.problem.title} ({r.problem.difficulty.capitalize()}, {r.problem.topic}"
        f"{_overdue(r.days_overdue, ', ')})\n  {r.problem.url}"
        for r in due
    )
    values = {
        "heading": heading,
        "today_url": f"{base}/?src=email",
        "settings_url": f"{base}/settings",
        "email_hour": _clock_hour(email_hour),
    }
    escaped = {key: html.escape(value) for key, value in values.items()}
    return Email(
        to=user.email,
        subject=subject_line([r.problem.title for r in due]),
        html=Template((TEMPLATES / "digest.html").read_text()).substitute(
            escaped, problems=html_rows
        ),
        text=Template((TEMPLATES / "digest.txt").read_text()).substitute(
            values, problems=text_rows
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.digest")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="send due users their morning email (one pass)")
    parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    settings.check_email()
    mailer = ResendMailer(settings.email_api_key, settings.email_from)
    summary = run(get_sessionmaker(), mailer, settings)
    return 1 if summary.failed or summary.unknown else 0


if __name__ == "__main__":
    sys.exit(main())
