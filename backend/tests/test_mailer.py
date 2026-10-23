import json

import pytest
import resend
from resend.exceptions import ResendError

from app.mailer import Email, EmailRejected, ResendMailer, _refused

EMAIL = Email(
    to="prabhav@example.com",
    subject="1 problem to review today: Two Sum",
    html="<p>Two Sum</p>",
    text="Two Sum",
)


class FakeHttpClient:
    def __init__(self, status=200, body=None, error=None):
        self.status = status
        self.body = {"id": "re-message-1"} if body is None else body
        self.error = error
        self.requests = []

    def request(self, method, url, headers, json=None, files=None, data=None):
        self.requests.append({"method": method, "url": url, "headers": headers, "json": json})
        if self.error is not None:
            raise self.error
        content = __import__("json").dumps(self.body).encode()
        return content, self.status, {"content-type": "application/json"}


@pytest.fixture
def mailer() -> ResendMailer:
    return ResendMailer(api_key="re_test_key", sender="Prep reviews <reviews@mail.example.com>")


def use(monkeypatch, client: FakeHttpClient) -> FakeHttpClient:
    monkeypatch.setattr(resend, "default_http_client", client)
    return client


def test_send_posts_both_parts_with_the_idempotency_key(monkeypatch, mailer):
    client = use(monkeypatch, FakeHttpClient())

    message_id = mailer.send(EMAIL, "digest/1/2026-11-02/0230")

    [request] = client.requests
    assert message_id == "re-message-1"
    assert request["method"] == "post"
    assert request["url"].endswith("/emails")
    assert request["headers"]["Idempotency-Key"] == "digest/1/2026-11-02/0230"
    assert request["headers"]["Authorization"] == "Bearer re_test_key"
    assert request["json"] == {
        "from": "Prep reviews <reviews@mail.example.com>",
        "to": ["prabhav@example.com"],
        "subject": EMAIL.subject,
        "html": EMAIL.html,
        "text": EMAIL.text,
    }


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (429, "daily_quota_exceeded"),
        (422, "validation_error"),
        (403, "invalid_api_key"),
        (409, "invalid_idempotent_request"),
    ],
)
def test_an_answer_from_resend_refusing_the_email_is_a_rejection(
    monkeypatch, mailer, status, error_type
):
    body = {"statusCode": status, "name": error_type, "message": "refused"}
    use(monkeypatch, FakeHttpClient(status=status, body=body))

    with pytest.raises(EmailRejected, match=error_type):
        mailer.send(EMAIL, "digest/1/2026-11-02/0230")


@pytest.mark.parametrize(
    "client",
    [
        FakeHttpClient(error=TimeoutError("read timed out")),
        FakeHttpClient(error=ConnectionError("connection reset")),
        FakeHttpClient(status=500, body={"statusCode": 500, "name": "application_error"}),
        FakeHttpClient(status=502, body={"message": "Bad gateway"}),
    ],
    ids=["timeout", "connection-reset", "resend-500", "gateway-502"],
)
def test_no_clear_answer_from_resend_is_not_a_rejection(monkeypatch, mailer, client):
    use(monkeypatch, client)

    with pytest.raises(ResendError) as caught:
        mailer.send(EMAIL, "digest/1/2026-11-02/0230")
    assert not isinstance(caught.value, EmailRejected)


def test_the_fake_client_speaks_json():
    assert json.loads(FakeHttpClient().request("post", "u", {})[0]) == {"id": "re-message-1"}


def test_an_error_without_a_numeric_status_is_not_a_rejection():
    error = ResendError(code="unknown", error_type="odd", message="?", suggested_action="")

    assert _refused(error) is False
