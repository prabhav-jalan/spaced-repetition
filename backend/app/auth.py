from dataclasses import dataclass
from typing import Any

import httpx2
from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.models import User

SESSION_USER_ID = "user_id"
PENDING_TIME_ZONE = "pending_timezone"
GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"
DEV_SUB_PREFIX = "dev:"


@dataclass(frozen=True)
class GoogleProfile:
    sub: str
    email: str
    name: str


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
    google_sub = f"{DEV_SUB_PREFIX}{email}"
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


def google_client(
    settings: Settings, transport: httpx2.AsyncBaseTransport | None = None
) -> StarletteOAuth2App:
    client_kwargs: dict[str, Any] = {"scope": "openid email profile"}
    if transport is not None:
        client_kwargs["transport"] = transport
    return OAuth().register(
        name="google",
        server_metadata_url=GOOGLE_METADATA_URL,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        client_kwargs=client_kwargs,
    )


def google_profile(claims: dict[str, Any] | None) -> GoogleProfile | None:
    if not claims or claims.get("email_verified") is not True:
        return None
    sub, email = claims.get("sub"), claims.get("email")
    if not isinstance(sub, str) or not isinstance(email, str) or "@" not in email:
        return None
    email = email.strip().lower()
    name = claims.get("name")
    if not isinstance(name, str) or not name.strip():
        name = email.split("@")[0]
    return GoogleProfile(sub=sub, email=email, name=name.strip())


def google_user(
    db: Session, profile: GoogleProfile, timezone: str, take_over_dev_account: bool
) -> User:
    user = db.scalar(select(User).where(User.google_sub == profile.sub))
    if user is None and take_over_dev_account:
        dev_sub = f"{DEV_SUB_PREFIX}{profile.email}"
        user = db.scalar(select(User).where(User.google_sub == dev_sub))
        if user is not None:
            user.google_sub = profile.sub
    if user is None:
        user = User(
            google_sub=profile.sub,
            email=profile.email,
            display_name=profile.name,
            timezone=timezone,
        )
        db.add(user)
    else:
        user.email = profile.email
        user.display_name = profile.name
    db.flush()
    return user
