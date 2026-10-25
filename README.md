# spaced-repetition

[![CI](https://github.com/prabhav-jalan/spaced-repetition/actions/workflows/ci.yml/badge.svg)](https://github.com/prabhav-jalan/spaced-repetition/actions/workflows/ci.yml)

A small app that tells interview-prep students which NeetCode problems to redo each day, using
the SM-2 spaced-repetition algorithm, with one email each morning at 8 a.m. in their own time
zone.

Live at https://prep.prabhavjalan.com.

## Run it locally

You need Docker, Python 3.12 and Node 22.

```bash
cp .env.example .env
docker compose up --build        # Postgres 16 and the API
curl http://localhost:8000/healthz
```

Backend tests (with Postgres from `docker compose up -d db`):

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && alembic upgrade head && pytest
```

Frontend dev server (proxies `/api` to the API on port 8000):

```bash
cd frontend
npm ci
npm run dev
```

## Deploy

`render.yaml` declares everything on Render: the web service, the email job (every 15 minutes)
and the database. Both services build the same `Dockerfile`, whose last stage adds the built
frontend, and they deploy from `main` once CI passes. Secrets are entered in Render, never in
the repo.

Back up the database before changes that matter (Render's free database has no backups), with
the external URL from the database's page in Render:

```bash
pg_dump "$RENDER_EXTERNAL_DATABASE_URL" --format=custom --file=backup.dump
```

## Stack

FastAPI, PostgreSQL 16, SQLAlchemy 2.0 and Alembic; React, Vite and TypeScript; pytest with
time-machine; GitHub Actions; Render.

MIT licensed.
