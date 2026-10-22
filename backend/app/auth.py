from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User

SESSION_USER_ID = "user_id"


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    user_id = request.session.get(SESSION_USER_ID)
    user = db.get(User, user_id) if isinstance(user_id, int) else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first")
    return user


def sign_in(request: Request, user: User) -> None:
    request.session.clear()
    request.session[SESSION_USER_ID] = user.id


def sign_out(request: Request) -> None:
    request.session.clear()


def dev_user(db: Session, email: str, timezone: str) -> User:
    google_sub = f"dev:{email}"
    user = db.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        user = User(
            google_sub=google_sub,
            email=email,
            display_name=email.split("@")[0],
            timezone=timezone,
        )
        db.add(user)
        db.flush()
    return user
