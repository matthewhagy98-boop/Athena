import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from digest.aggregate import aggregate_changes_for_user
from digest.compose import ComposeError, compose_digest
from digest.delivery import EmailSender, get_email_sender, persist_digest_email
from digest.models import DeliveryPreference, DigestFrequency, DigestRun, DigestRunStatus, EmailSendResult, User
from digest.profiles import get_delivery_preference, list_interests
from digest.render import render_digest

logger = logging.getLogger("digest_runner")


def _is_due(preference: DeliveryPreference, now: datetime) -> bool:
    if preference.last_digest_sent_at is None:
        return True
    elapsed = now - preference.last_digest_sent_at
    if preference.frequency == DigestFrequency.WEEKLY:
        return elapsed >= timedelta(days=7) and now.weekday() == preference.send_day
    raise ValueError(f"Unsupported digest frequency: {preference.frequency}")


def select_due_users(session: Session, now: datetime) -> list[User]:
    active_users = session.execute(select(User).where(User.status == "active")).scalars().all()
    due = []
    for user in active_users:
        if not list_interests(session, user):
            continue
        preference = get_delivery_preference(session, user)
        if _is_due(preference, now):
            due.append(user)
    return due


def process_user_digest(session: Session, user: User, now: datetime, sender: EmailSender) -> DigestRun:
    preference = get_delivery_preference(session, user)
    window_start = preference.last_digest_sent_at or user.created_at
    window_end = now

    topic_digests = aggregate_changes_for_user(session, user, window_start, window_end)

    if not topic_digests:
        run = DigestRun(
            user_id=user.id, window_start=window_start, window_end=window_end, status=DigestRunStatus.SKIPPED_NO_CHANGES
        )
        session.add(run)
        preference.last_digest_sent_at = window_end
        session.flush()
        return run

    run = DigestRun(user_id=user.id, window_start=window_start, window_end=window_end, status=DigestRunStatus.FAILED)
    session.add(run)
    session.flush()

    try:
        composed = compose_digest(topic_digests)
    except ComposeError:
        logger.exception("Failed to compose digest for user %s", user.id)
        return run

    rendered = render_digest(composed, user.email)
    outcome = sender.send(user.email, rendered.subject, rendered.html_body, rendered.text_body)
    persist_digest_email(session, run, rendered.subject, rendered.html_body, rendered.text_body, sender.name, outcome)

    if outcome.result == EmailSendResult.SUCCESS:
        run.status = DigestRunStatus.SENT
        preference.last_digest_sent_at = window_end

    session.flush()
    return run


def run_all_due_digests(session_factory) -> None:
    now = datetime.utcnow()
    session = session_factory()
    try:
        due_user_ids = [u.id for u in select_due_users(session, now)]
    finally:
        session.close()

    for user_id in due_user_ids:
        session = session_factory()
        try:
            user = session.get(User, user_id)
            sender = get_email_sender()
            process_user_digest(session, user, now, sender)
            session.commit()
            logger.info("Completed digest run for user %s", user.email)
        except Exception:
            session.rollback()
            logger.exception("Failed digest run for user %s", user_id)
        finally:
            session.close()
