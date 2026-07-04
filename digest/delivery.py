import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol

from sqlalchemy.orm import Session

from digest.config import get_digest_settings
from digest.models import DigestEmail, DigestRun, EmailSendResult


@dataclass
class EmailSendOutcome:
    result: EmailSendResult
    detail: str | None = None


class EmailSender(Protocol):
    name: str

    def send(self, to_email: str, subject: str, html_body: str, text_body: str) -> EmailSendOutcome: ...


class ConsoleSender:
    name = "console"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, to_email: str, subject: str, html_body: str, text_body: str) -> EmailSendOutcome:
        self.sent.append({"to": to_email, "subject": subject, "html_body": html_body, "text_body": text_body})
        return EmailSendOutcome(result=EmailSendResult.SUCCESS)


class SmtpSender:
    name = "smtp"

    def send(self, to_email: str, subject: str, html_body: str, text_body: str) -> EmailSendOutcome:
        settings = get_digest_settings()
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = settings.smtp_from_address
        message["To"] = to_email
        message.attach(MIMEText(text_body, "plain"))
        message.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.sendmail(settings.smtp_from_address, [to_email], message.as_string())
        except Exception as exc:
            return EmailSendOutcome(result=EmailSendResult.FAILURE, detail=str(exc))
        return EmailSendOutcome(result=EmailSendResult.SUCCESS)


def get_email_sender() -> EmailSender:
    settings = get_digest_settings()
    if settings.email_sender == "smtp":
        return SmtpSender()
    return ConsoleSender()


def persist_digest_email(
    session: Session,
    digest_run: DigestRun,
    subject: str,
    html_body: str,
    text_body: str,
    sender_name: str,
    outcome: EmailSendOutcome,
) -> DigestEmail:
    email = DigestEmail(
        digest_run_id=digest_run.id,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        sender_name=sender_name,
        send_result=outcome.result,
        send_detail=outcome.detail,
        sent_at=datetime.utcnow() if outcome.result == EmailSendResult.SUCCESS else None,
    )
    session.add(email)
    session.flush()
    return email
