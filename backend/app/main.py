from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app import api
from app.config import Settings, get_settings

SESSION_MAX_AGE = 30 * 24 * 60 * 60


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Spaced repetition for interview prep")
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
