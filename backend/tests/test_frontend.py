import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

INDEX = '<!doctype html><html><body><div id="root"></div></body></html>'
PRODUCTION = {
    "ENV": "production",
    "SESSION_SECRET": "s" * 32,
    "GOOGLE_CLIENT_ID": "client-id",
    "GOOGLE_CLIENT_SECRET": "client-secret",
    "APP_URL": "https://prep.prabhavjalan.com",
}


@pytest.fixture
def built_frontend(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX)
    (static / "assets" / "index-3f9a1c.js").write_text("console.log('app')")
    (static / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("not for the web")
    return static


@pytest.fixture
def client(built_frontend):
    app = create_app(Settings.from_env(PRODUCTION), static_dir=built_frontend)
    return TestClient(app, base_url="https://testserver")


def is_the_app(response) -> bool:
    return response.status_code == 200 and 'id="root"' in response.text


def test_the_home_page_is_the_built_app(client):
    response = client.get("/")

    assert is_the_app(response)
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    "path", ["/catalog", "/settings", "/?src=email", "/?signin=failed", "/no-such-page"]
)
def test_deep_links_load_the_app(client, path):
    response = client.get(path)

    assert is_the_app(response)
    assert response.headers["cache-control"] == "no-cache"


def test_built_assets_are_served_and_cached_for_good(client):
    response = client.get("/assets/index-3f9a1c.js")

    assert response.status_code == 200
    assert response.text == "console.log('app')"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_a_missing_asset_is_a_404_not_the_app(client):
    assert client.get("/assets/index-from-an-old-deploy.js").status_code == 404


def test_other_files_in_the_build_are_served(client):
    assert client.get("/favicon.svg").text == "<svg/>"


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_unknown_api_paths_stay_json_404s(client, method):
    response = client.request(method, "/api/no-such-endpoint")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_production_still_refuses_the_dev_login(client):
    response = client.post("/api/dev/login", json={"email": "me@example.com", "timezone": "UTC"})

    assert response.status_code == 404


def test_the_api_and_health_check_still_answer(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/auth/providers").json() == {"google": True, "dev": False}
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"]
)
def test_files_outside_the_build_are_never_served(client, path):
    assert "not for the web" not in client.get(path).text


def test_without_a_build_the_api_runs_alone(tmp_path):
    app = create_app(Settings.from_env({"ENV": "dev"}), static_dir=tmp_path / "no-build")
    client = TestClient(app)

    assert client.get("/").status_code == 404
    assert client.get("/healthz").status_code == 200
