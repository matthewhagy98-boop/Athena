from datetime import datetime, timedelta
from unittest.mock import patch

import httpx
import respx
from sqlalchemy import select

from digest.compose import ComposeError
from digest.delivery import ConsoleSender, EmailSendOutcome
from digest.models import DigestFrequency, DigestRunStatus, EmailSendResult
from digest.profiles import add_interest, create_user
from digest.runner import _is_due, process_user_digest, select_due_users
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic
from evidence_engine.topics.mesh import MeshResolution

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _tool_use_response(narrative: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-4-6",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "compose_topic_narrative", "input": {"narrative": narrative}}],
            "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 10},
        },
    )


def test_is_due_true_when_never_sent_regardless_of_weekday():
    from digest.models import DeliveryPreference

    preference = DeliveryPreference(frequency=DigestFrequency.WEEKLY, send_day=3, last_digest_sent_at=None)
    assert _is_due(preference, datetime(2026, 7, 6)) is True  # a Monday, not send_day=3


def test_is_due_false_when_elapsed_but_wrong_weekday():
    from digest.models import DeliveryPreference

    preference = DeliveryPreference(frequency=DigestFrequency.WEEKLY, send_day=3, last_digest_sent_at=datetime(2026, 6, 20))
    assert _is_due(preference, datetime(2026, 6, 29)) is False  # 9 days elapsed but a Monday (weekday 0), not Thursday (3)


def test_is_due_true_when_elapsed_and_correct_weekday():
    from digest.models import DeliveryPreference

    preference = DeliveryPreference(frequency=DigestFrequency.WEEKLY, send_day=0, last_digest_sent_at=datetime(2026, 6, 22))
    assert _is_due(preference, datetime(2026, 6, 29)) is True  # exactly 7 days later, a Monday


def test_is_due_false_when_not_enough_time_elapsed():
    from digest.models import DeliveryPreference

    preference = DeliveryPreference(frequency=DigestFrequency.WEEKLY, send_day=0, last_digest_sent_at=datetime(2026, 6, 25))
    assert _is_due(preference, datetime(2026, 6, 29)) is False  # 4 days elapsed, right weekday but too soon


def test_select_due_users_excludes_users_with_no_interests(db_session):
    create_user(db_session, "no_interests@example.com")
    with_interest = create_user(db_session, "has_interest@example.com")
    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="D000005", canonical_label="Some Topic"),
    ):
        add_interest(db_session, with_interest, "some topic")

    due = select_due_users(db_session, datetime(2026, 7, 6))

    assert [u.email for u in due] == ["has_interest@example.com"]


def test_select_due_users_excludes_paused_users(db_session):
    active_user = create_user(db_session, "active@example.com")
    paused_user = create_user(db_session, "paused@example.com")
    paused_user.status = "paused"
    db_session.flush()

    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="D000010", canonical_label="Some Other Topic"),
    ):
        add_interest(db_session, active_user, "some other topic")
        add_interest(db_session, paused_user, "some other topic")

    due = select_due_users(db_session, datetime(2026, 7, 6))

    assert [u.email for u in due] == ["active@example.com"]


@respx.mock
def test_process_user_digest_marks_skipped_and_advances_watermark_when_no_changes(db_session):
    user = create_user(db_session, "quiet@example.com")
    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="D000006", canonical_label="Quiet Topic"),
    ):
        add_interest(db_session, user, "quiet topic")

    now = datetime(2026, 7, 6)
    sender = ConsoleSender()
    run = process_user_digest(db_session, user, now, sender)

    assert run.status == DigestRunStatus.SKIPPED_NO_CHANGES
    assert sender.sent == []
    from digest.profiles import get_delivery_preference

    assert get_delivery_preference(db_session, user).last_digest_sent_at == now


@respx.mock
def test_process_user_digest_sends_and_advances_watermark_on_success(db_session):
    user = create_user(db_session, "active@example.com")
    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="D000007", canonical_label="Active Topic"),
    ):
        topic = add_interest(db_session, user, "active topic")
    db_session.add(ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.CONSENSUS_UPDATED, detected_at=datetime(2026, 7, 5)))
    db_session.flush()

    respx.post(MESSAGES_URL).mock(return_value=_tool_use_response("Consensus was refreshed this week."))

    now = datetime(2026, 7, 6)
    sender = ConsoleSender()
    run = process_user_digest(db_session, user, now, sender)

    assert run.status == DigestRunStatus.SENT
    assert len(sender.sent) == 1
    from digest.profiles import get_delivery_preference

    assert get_delivery_preference(db_session, user).last_digest_sent_at == now


def test_process_user_digest_marks_failed_and_does_not_advance_watermark_on_compose_error(db_session):
    user = create_user(db_session, "flaky@example.com")
    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="D000008", canonical_label="Flaky Topic"),
    ):
        topic = add_interest(db_session, user, "flaky topic")
    db_session.add(ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.CONSENSUS_UPDATED, detected_at=datetime(2026, 7, 5)))
    db_session.flush()

    now = datetime(2026, 7, 6)
    sender = ConsoleSender()

    with patch("digest.runner.compose_digest", side_effect=ComposeError("boom")):
        run = process_user_digest(db_session, user, now, sender)

    assert run.status == DigestRunStatus.FAILED
    assert sender.sent == []
    from digest.profiles import get_delivery_preference

    assert get_delivery_preference(db_session, user).last_digest_sent_at is None


@respx.mock
def test_process_user_digest_marks_failed_and_does_not_advance_watermark_on_send_failure(db_session):
    user = create_user(db_session, "send_flaky@example.com")
    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="D000011", canonical_label="Send Flaky Topic"),
    ):
        topic = add_interest(db_session, user, "send flaky topic")
    db_session.add(ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.CONSENSUS_UPDATED, detected_at=datetime(2026, 7, 5)))
    db_session.flush()

    respx.post(MESSAGES_URL).mock(return_value=_tool_use_response("Consensus was refreshed this week."))

    now = datetime(2026, 7, 6)

    class FailingSender:
        name = "failing"

        def send(self, to_email, subject, html_body, text_body):
            return EmailSendOutcome(result=EmailSendResult.FAILURE, detail="smtp timeout")

    run = process_user_digest(db_session, user, now, FailingSender())

    assert run.status == DigestRunStatus.FAILED
    from digest.models import DigestEmail
    from digest.profiles import get_delivery_preference

    persisted_email = db_session.execute(select(DigestEmail).where(DigestEmail.digest_run_id == run.id)).scalar_one()
    assert persisted_email.send_result == EmailSendResult.FAILURE
    assert persisted_email.send_detail == "smtp timeout"
    assert get_delivery_preference(db_session, user).last_digest_sent_at is None
