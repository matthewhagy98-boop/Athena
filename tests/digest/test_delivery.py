from unittest.mock import MagicMock, patch

from digest.delivery import ConsoleSender, SmtpSender, persist_digest_email
from digest.models import DigestEmail, DigestRun, DigestRunStatus, EmailSendResult, User


def test_console_sender_captures_send_and_returns_success():
    sender = ConsoleSender()

    outcome = sender.send("researcher@example.com", "Subject", "<html>body</html>", "body")

    assert outcome.result == EmailSendResult.SUCCESS
    assert sender.sent == [{"to": "researcher@example.com", "subject": "Subject", "html_body": "<html>body</html>", "text_body": "body"}]


def test_smtp_sender_success_calls_sendmail():
    sender = SmtpSender()

    with patch("digest.delivery.smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        outcome = sender.send("researcher@example.com", "Subject", "<html>body</html>", "body")

    assert outcome.result == EmailSendResult.SUCCESS

    # Verify sendmail was called with correct arguments
    mock_server.sendmail.assert_called_once()
    call_args = mock_server.sendmail.call_args

    # Unpack positional arguments: from_address, recipients, message_string
    from_address = call_args[0][0]
    recipients = call_args[0][1]
    message_string = call_args[0][2]

    # Assert from-address is correct
    assert from_address == "digest@example.com"

    # Assert recipient list is correct
    assert recipients == ["researcher@example.com"]

    # Assert message contains expected subject and body content
    assert "Subject: Subject" in message_string
    assert "body" in message_string
    assert "<html>body</html>" in message_string


def test_smtp_sender_failure_returns_failure_outcome():
    sender = SmtpSender()

    with patch("digest.delivery.smtplib.SMTP", side_effect=OSError("connection refused")):
        outcome = sender.send("researcher@example.com", "Subject", "<html>body</html>", "body")

    assert outcome.result == EmailSendResult.FAILURE
    assert "connection refused" in outcome.detail


def test_persist_digest_email_writes_row_with_sent_at_on_success(db_session):
    user = User(email="researcher@example.com")
    db_session.add(user)
    db_session.flush()
    run = DigestRun(user_id=user.id, window_start=user.created_at, window_end=user.created_at, status=DigestRunStatus.SENT)
    db_session.add(run)
    db_session.flush()

    sender = ConsoleSender()
    outcome = sender.send("researcher@example.com", "Subject", "<html></html>", "text")

    email = persist_digest_email(db_session, run, "Subject", "<html></html>", "text", sender.name, outcome)

    fetched = db_session.get(DigestEmail, email.id)
    assert fetched.send_result == EmailSendResult.SUCCESS
    assert fetched.sent_at is not None


def test_persist_digest_email_leaves_sent_at_none_on_failure(db_session):
    user = User(email="researcher2@example.com")
    db_session.add(user)
    db_session.flush()
    run = DigestRun(user_id=user.id, window_start=user.created_at, window_end=user.created_at, status=DigestRunStatus.FAILED)
    db_session.add(run)
    db_session.flush()

    from digest.delivery import EmailSendOutcome

    outcome = EmailSendOutcome(result=EmailSendResult.FAILURE, detail="smtp down")
    email = persist_digest_email(db_session, run, "Subject", "<html></html>", "text", "smtp", outcome)

    fetched = db_session.get(DigestEmail, email.id)
    assert fetched.send_result == EmailSendResult.FAILURE
    assert fetched.send_detail == "smtp down"
    assert fetched.sent_at is None
