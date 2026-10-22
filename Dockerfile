# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/backend

COPY backend/ ./
RUN pip install -e . \
    && useradd --create-home --uid 10001 app

USER app

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python -m app.catalog load && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
