import re
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app import attempts, auth, catalog, clock, reviews, users
from app.db import get_session
from app.models import User

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _known_time_zone(value: str) -> str:
    if not users.is_valid_time_zone(value):
        raise ValueError("Unknown time zone. Use an IANA name such as America/New_York.")
    return value


def _email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(value):
        raise ValueError("Enter an email address.")
    return value


TimeZone = Annotated[str, AfterValidator(_known_time_zone)]
Email = Annotated[str, AfterValidator(_email)]
Result = Literal["easy", "struggled", "failed"]
DbSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(auth.current_user)]


class ProblemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    url: str
    difficulty: str
    topic: str


class CatalogProblemOut(ProblemOut):
    status: catalog.Status
    due_date: date | None


class AttemptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_id: int
    result: Result


class AttemptOut(BaseModel):
    id: int
    problem_id: int
    result: Result
    local_date: date
    was_due: bool
    rescheduled: bool
    due_date: date
    interval_days: int


class ReviewOut(BaseModel):
    problem: ProblemOut
    due_date: date
    days_overdue: int


class TodayOut(BaseModel):
    local_date: date
    reviews: list[ReviewOut]


class TotalsOut(BaseModel):
    attempts: int
    problems: int
    due_today: int


class MeOut(BaseModel):
    id: int
    email: str
    display_name: str
    timezone: str
    email_enabled: bool
    local_date: date
    totals: TotalsOut


class MeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: TimeZone | None = None
    email_enabled: bool | None = None

    @field_validator("timezone", "email_enabled")
    @classmethod
    def _not_null(cls, value):
        if value is None:
            raise ValueError("Leave the field out instead of sending null.")
        return value


class DevLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    timezone: TimeZone


router = APIRouter(prefix="/api")
dev_router = APIRouter(prefix="/api/dev")


def _me(db: Session, user: User) -> MeOut:
    profile = users.profile(db, user, clock.now())
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        timezone=user.timezone,
        email_enabled=user.email_enabled,
        local_date=profile.local_date,
        totals=TotalsOut(
            attempts=profile.attempts, problems=profile.problems, due_today=profile.due_today
        ),
    )


@router.get("/me")
def get_me(db: DbSession, user: CurrentUser) -> MeOut:
    return _me(db, user)


@router.patch("/me")
def patch_me(body: MeUpdate, db: DbSession, user: CurrentUser) -> MeOut:
    users.update(db, user, **body.model_dump(exclude_unset=True))
    db.commit()
    return _me(db, user)


@router.post("/attempts", status_code=status.HTTP_201_CREATED)
def post_attempt(body: AttemptIn, db: DbSession, user: CurrentUser) -> AttemptOut:
    try:
        logged = attempts.log_attempt(db, user, body.problem_id, body.result, clock.now())
    except attempts.ProblemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such problem") from None
    db.commit()
    attempt, progress = logged.attempt, logged.progress
    return AttemptOut(
        id=attempt.id,
        problem_id=attempt.problem_id,
        result=attempt.result,
        local_date=attempt.local_date,
        was_due=attempt.was_due,
        rescheduled=attempt.rescheduled,
        due_date=progress.due_date,
        interval_days=progress.interval_days,
    )


@router.get("/reviews/today")
def get_today(db: DbSession, user: CurrentUser) -> TodayOut:
    today, due = reviews.due_today(db, user, clock.now())
    return TodayOut(
        local_date=today,
        reviews=[
            ReviewOut(
                problem=ProblemOut.model_validate(review.problem),
                due_date=review.due_date,
                days_overdue=review.days_overdue,
            )
            for review in due
        ],
    )


@router.get("/problems")
def get_problems(
    db: DbSession, user: CurrentUser, topic: str | None = None, q: str | None = None
) -> list[CatalogProblemOut]:
    return [
        CatalogProblemOut(
            **ProblemOut.model_validate(entry.problem).model_dump(),
            status=entry.status,
            due_date=entry.due_date,
        )
        for entry in catalog.list_problems(db, user, clock.now(), topic, q)
    ]


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    auth.sign_out(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@dev_router.post("/login")
def dev_login(body: DevLoginIn, request: Request, db: DbSession) -> MeOut:
    user = auth.dev_user(db, body.email, body.timezone)
    db.commit()
    auth.sign_in(request, user)
    return _me(db, user)
