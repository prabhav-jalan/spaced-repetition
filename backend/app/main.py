from pathlib import Path

import httpx2
from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app import api, auth
from app.config import Settings, get_settings

SESSION_MAX_AGE = 30 * 24 * 60 * 60
STATIC_DIR = Path(__file__).parent / "static"
CACHE_FOREVER = "public, max-age=31536000, immutable"


class SinglePageApp(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        if path.split("/", 1)[0] == "api":
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or path.startswith("assets/"):
                raise
            path = "index.html"
            response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = (
            CACHE_FOREVER if path.startswith("assets/") else "no-cache"
        )
        return response


def create_app(
    settings: Settings | None = None,
    google_transport: httpx2.AsyncBaseTransport | None = None,
    static_dir: Path = STATIC_DIR,
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

    if (static_dir / "index.html").is_file():
        app.mount("/", SinglePageApp(directory=static_dir), name="frontend")

    return app


app = create_app()
