from datetime import datetime
from unittest.mock import patch

from digest.models import DigestRunStatus
from digest.profiles import create_user
from scripts.run_digests import run_all_due_digests


def test_run_all_due_digests_isolates_per_user_failure_and_commits_others(db_session):
    db_session.commit = lambda: None
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    ok_user = create_user(db_session, "ok@example.com")
    failing_user = create_user(db_session, "failing@example.com")

    def fake_process(session, user, now, sender):
        if user.email == "failing@example.com":
            raise RuntimeError("boom")
        from digest.models import DigestRun

        run = DigestRun(user_id=user.id, window_start=now, window_end=now, status=DigestRunStatus.SKIPPED_NO_CHANGES)
        session.add(run)
        session.flush()
        return run

    with (
        patch("digest.runner.select_due_users", return_value=[ok_user, failing_user]),
        patch("digest.runner.get_email_sender"),
        patch("digest.runner.process_user_digest", side_effect=fake_process) as mock_process,
    ):
        run_all_due_digests(lambda: db_session)

    assert mock_process.call_count == 2
    processed_emails = [call.args[1].email for call in mock_process.call_args_list]
    assert "ok@example.com" in processed_emails
    assert "failing@example.com" in processed_emails
