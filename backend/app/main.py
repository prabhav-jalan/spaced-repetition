from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Spaced repetition for interview prep")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
