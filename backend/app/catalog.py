import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import clock
from app.db import get_sessionmaker
from app.models import Problem, User, UserProblem

CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "neetcode150.csv"
FIELDS = ("title", "slug", "url", "difficulty", "topic")

Status = Literal["new", "scheduled", "due"]


@dataclass(frozen=True)
class CatalogEntry:
    problem: Problem
    status: Status
    due_date: date | None


def read_csv(path: Path = CSV_PATH) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return [{field: row[field] for field in FIELDS} for row in csv.DictReader(file)]


def load(db: Session, rows: list[dict[str, str]]) -> int:
    upsert = insert(Problem).values(rows)
    upsert = upsert.on_conflict_do_update(
        index_elements=[Problem.slug],
        set_={field: upsert.excluded[field] for field in FIELDS if field != "slug"},
    )
    db.execute(upsert)
    return len(rows)


def list_problems(
    db: Session, user: User, now: datetime, topic: str | None = None, query: str | None = None
) -> list[CatalogEntry]:
    today = clock.local_date(now, user.timezone)
    statement = (
        select(Problem, UserProblem.due_date)
        .outerjoin(
            UserProblem,
            and_(UserProblem.problem_id == Problem.id, UserProblem.user_id == user.id),
        )
        .order_by(Problem.id)
    )
    if topic:
        statement = statement.where(Problem.topic == topic)
    if query:
        statement = statement.where(Problem.title.icontains(query, autoescape=True))
    return [
        CatalogEntry(problem, _status(due, today), due) for problem, due in db.execute(statement)
    ]


def _status(due: date | None, today: date) -> Status:
    if due is None:
        return "new"
    return "due" if due <= today else "scheduled"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.catalog")
    commands = parser.add_subparsers(dest="command", required=True)
    load_command = commands.add_parser("load", help="upsert the NeetCode 150 by slug")
    load_command.add_argument("path", nargs="?", type=Path, default=CSV_PATH)
    args = parser.parse_args(argv)

    with get_sessionmaker()() as db:
        count = load(db, read_csv(args.path))
        db.commit()
    print(f"Loaded {count} problems from {args.path.name}")


if __name__ == "__main__":
    main()
