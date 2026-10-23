from dataclasses import dataclass
from typing import Protocol

import resend
from resend.exceptions import ResendError


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    html: str
    text: str


class EmailRejected(Exception):
    pass


class Mailer(Protocol):
    def send(self, email: Email, idempotency_key: str) -> str: ...


class ResendMailer:
    def __init__(self, api_key: str, sender: str) -> None:
        self.api_key = api_key
        self.sender = sender

    def send(self, email: Email, idempotency_key: str) -> str:
        resend.api_key = self.api_key
        params: resend.Emails.SendParams = {
            "from": self.sender,
            "to": [email.to],
            "subject": email.subject,
            "html": email.html,
            "text": email.text,
        }
        try:
            sent = resend.Emails.send(params, {"idempotency_key": idempotency_key})
        except ResendError as error:
            if _refused(error):
                raise EmailRejected(f"{error.code} {error.error_type}: {error.message}") from error
            raise
        return sent["id"]


def _refused(error: ResendError) -> bool:
    if error.error_type == "HttpClientError":
        return False
    try:
        status = int(str(error.code))
    except ValueError:
        return False
    return 400 <= status < 500
