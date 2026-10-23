import httpx2
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app import api, auth
from app.config import Settings, get_settings

SESSION_MAX_AGE = 30 * 24 * 60 * 60


def create_app(
    settings: Settings | None = None, google_transport: httpx2.AsyncBaseTransport | None = None
) -> FastAPI:
    settings = settings or get_settings()
    settings.check_web()
    app = FastAPI(title="Spaced repetition for interview prep")
    app.state.settings = settings
    app.state.google = (
        auth.google_client(settings, google_transport) if settings.google_configured else None
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=settings.is_production,
    )
    app.include_router(api.router)
    if settings.env == "dev":
        app.include_router(api.dev_router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
