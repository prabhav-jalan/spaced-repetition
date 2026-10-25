# syntax=docker/dockerfile:1

FROM node:22-slim AS frontend

WORKDIR /srv/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS api

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


FROM api AS production

COPY --from=frontend /srv/frontend/dist ./app/static
