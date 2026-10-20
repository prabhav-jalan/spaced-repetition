from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_returns_200_and_ok():
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_answers_without_a_database(monkeypatch, fresh_settings):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")
    client = TestClient(create_app())

    assert client.get("/healthz").status_code == 200
