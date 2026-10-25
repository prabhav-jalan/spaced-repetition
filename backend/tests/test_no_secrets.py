import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECRET_PATTERNS = {
    "Resend API key": re.compile(r"\bre_[A-Za-z0-9]{8,}_[A-Za-z0-9]{16,}"),
    "Google OAuth client secret": re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
    "Render API key": re.compile(r"\brnd_[A-Za-z0-9]{20,}"),
}
ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]+)?$")
SECRET_SETTINGS = ("SESSION_SECRET", "GOOGLE_CLIENT_SECRET", "EMAIL_API_KEY")


@pytest.fixture(scope="module")
def git():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")

    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True
        ).stdout

    return run


def secrets_in(text: str) -> list[str]:
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]


def is_env_file(path: str) -> bool:
    return bool(ENV_FILE.search(path)) and not path.endswith(".env.example")


def test_no_env_file_is_tracked_or_ever_was(git):
    tracked = git("ls-files").splitlines()
    ever_added = git("log", "--all", "--name-only", "--format=").splitlines()

    assert [path for path in tracked + ever_added if is_env_file(path)] == []


def test_no_secret_in_the_tracked_files(git):
    found = []
    for path in git("ls-files").splitlines():
        file = ROOT / path
        if file.is_file():
            found += [f"{path}: {secret}" for secret in secrets_in(file.read_text(errors="ignore"))]

    assert found == []


def test_no_secret_anywhere_in_the_history(git):
    found = secrets_in(git("log", "--all", "-p", "--no-color", "--no-ext-diff"))

    assert found == []


def test_the_env_example_leaves_every_secret_blank():
    lines = (ROOT / ".env.example").read_text().splitlines()
    values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))

    assert {key: values[key] for key in SECRET_SETTINGS} == dict.fromkeys(SECRET_SETTINGS, "")
