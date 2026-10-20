# spaced-repetition

A small app that tells interview-prep students which NeetCode problems to redo each day, using
the SM-2 spaced-repetition algorithm, with one email each morning at 8 a.m. in their own time
zone.

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

## Stack

FastAPI, PostgreSQL 16, SQLAlchemy 2.0 and Alembic; React, Vite and TypeScript; pytest with
time-machine; GitHub Actions; Render.

MIT licensed.
