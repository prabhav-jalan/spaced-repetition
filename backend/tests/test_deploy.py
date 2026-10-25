from pathlib import Path

import pytest
import yaml

from app.config import ENV_VARS, Settings

ROOT = Path(__file__).resolve().parents[2]
SECRETS = {"SESSION_SECRET", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "EMAIL_API_KEY"}
PASTED_INTO_RENDER = "pasted-into-render-" + "x" * 32
RENDER_DATABASE_URL = "postgresql://user:password@dpg-internal-a:5432/spaced_repetition"
SITE = "https://prep.prabhavjalan.com"


def load(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text())


@pytest.fixture(scope="module")
def blueprint() -> dict:
    return load("render.yaml")


def service(blueprint: dict, kind: str) -> dict:
    [found] = [s for s in blueprint["services"] if s["type"] == kind]
    return found


def variables(blueprint: dict, svc: dict) -> dict[str, dict]:
    groups = {group["name"]: group["envVars"] for group in blueprint["envVarGroups"]}
    found = {}
    for entry in svc["envVars"]:
        if "fromGroup" in entry:
            found.update({variable["key"]: variable for variable in groups[entry["fromGroup"]]})
        else:
            found[entry["key"]] = entry
    return found


def as_render_sets_them(entries: dict[str, dict]) -> dict[str, str]:
    values = {}
    for key, entry in entries.items():
        if entry.get("sync") is False:
            values[key] = PASTED_INTO_RENDER
        elif "fromDatabase" in entry:
            values[key] = RENDER_DATABASE_URL
        else:
            values[key] = str(entry["value"])
    return values


def test_the_web_app_starts_with_what_render_gives_it(blueprint):
    settings = Settings.from_env(
        as_render_sets_them(variables(blueprint, service(blueprint, "web")))
    )

    settings.check_web()
    assert settings.is_production
    assert settings.app_url == SITE
    assert settings.google_redirect_uri == f"{SITE}/api/auth/google/callback"
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_the_email_job_runs_with_what_render_gives_it(blueprint):
    settings = Settings.from_env(
        as_render_sets_them(variables(blueprint, service(blueprint, "cron")))
    )

    settings.check_email()
    assert settings.is_production
    assert settings.app_url == SITE
    assert settings.email_from == "reviews@mail.prabhavjalan.com"
    assert settings.database_url.startswith("postgresql+psycopg://")


@pytest.mark.parametrize("kind", ["web", "cron"])
def test_every_variable_is_one_the_app_reads(blueprint, kind):
    assert set(variables(blueprint, service(blueprint, kind))) <= set(ENV_VARS)


@pytest.mark.parametrize("kind", ["web", "cron"])
def test_secrets_are_pasted_into_render_never_written_down(blueprint, kind):
    for key, entry in variables(blueprint, service(blueprint, kind)).items():
        if key in SECRETS:
            assert entry == {"key": key, "sync": False}


def test_the_shared_group_holds_no_secrets(blueprint):
    for group in blueprint["envVarGroups"]:
        for entry in group["envVars"]:
            assert entry["key"] not in SECRETS
            assert "sync" not in entry


def test_the_web_service_serves_the_site_and_reports_health(blueprint):
    web = service(blueprint, "web")

    assert web["runtime"] == "docker"
    assert web["healthCheckPath"] == "/healthz"
    assert web["domains"] == ["prep.prabhavjalan.com"]


def test_the_email_job_runs_every_15_minutes_from_the_same_image(blueprint):
    cron = service(blueprint, "cron")

    assert cron["runtime"] == "docker"
    assert cron["schedule"] == "*/15 * * * *"
    assert cron["dockerCommand"] == "python -m app.digest run"
    assert "dockerfilePath" not in cron


@pytest.mark.parametrize("kind", ["web", "cron"])
def test_deploys_wait_for_ci_to_pass(blueprint, kind):
    assert service(blueprint, kind)["autoDeployTrigger"] == "checksPass"


def test_both_services_use_the_one_database_over_the_private_network(blueprint):
    [database] = blueprint["databases"]
    for kind in ["web", "cron"]:
        svc = service(blueprint, kind)
        assert variables(blueprint, svc)["DATABASE_URL"]["fromDatabase"] == {
            "name": database["name"],
            "property": "connectionString",
        }
        assert svc["region"] == database["region"]


def test_production_runs_the_postgres_version_tested_in_ci(blueprint):
    [database] = blueprint["databases"]
    compose = load("docker-compose.yml")
    ci = load(".github/workflows/ci.yml")

    assert database["postgresMajorVersion"] == "16"
    assert compose["services"]["db"]["image"] == "postgres:16"
    assert ci["jobs"]["backend"]["services"]["postgres"]["image"] == "postgres:16"


def test_ci_runs_the_tests_and_builds_the_image_on_every_pull_request():
    ci = load(".github/workflows/ci.yml")
    triggers = ci.get("on", ci.get(True))

    assert "pull_request" in triggers
    assert {"backend", "frontend", "image"} <= set(ci["jobs"])
    assert any("docker build" in step.get("run", "") for step in ci["jobs"]["image"]["steps"])


def test_ci_checks_out_the_whole_history_for_the_secrets_test():
    ci = load(".github/workflows/ci.yml")
    steps = ci["jobs"]["backend"]["steps"]
    [checkout] = [step for step in steps if "actions/checkout" in step.get("uses", "")]

    assert checkout["with"]["fetch-depth"] == 0


def test_the_readme_shows_the_ci_badge():
    workflow = "https://github.com/prabhav-jalan/spaced-repetition/actions/workflows/ci.yml"

    assert f"[![CI]({workflow}/badge.svg)]({workflow})" in (ROOT / "README.md").read_text()


def test_the_privacy_policy_google_requires_is_public_and_linked():
    policy = (ROOT / "frontend" / "public" / "privacy.html").read_text()
    pages = ROOT / "frontend" / "src" / "pages"

    assert "<title>Privacy policy · Prep reviews</title>" in policy
    assert "mailto:prabhavjalan12@gmail.com" in policy
    for service in ["Google", "Render", "Resend"]:
        assert service in policy
    for page in ["SignInPage.tsx", "SettingsPage.tsx"]:
        assert 'href="/privacy.html"' in (pages / page).read_text()
