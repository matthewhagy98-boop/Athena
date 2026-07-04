import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from evidence_engine.db.models import Base


class DigestFrequency(str, enum.Enum):
    WEEKLY = "weekly"
    DAILY = "daily"


class DigestRunStatus(str, enum.Enum):
    SENT = "sent"
    SKIPPED_NO_CHANGES = "skipped_no_changes"
    FAILED = "failed"


class EmailSendResult(str, enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class InterestProfile(Base):
    __tablename__ = "interest_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class ProfileTopic(Base):
    __tablename__ = "profile_topics"
    __table_args__ = (UniqueConstraint("profile_id", "topic_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interest_profiles.id"))
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"))
    added_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class DeliveryPreference(Base):
    __tablename__ = "delivery_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    frequency: Mapped[DigestFrequency] = mapped_column(default=DigestFrequency.WEEKLY)
    send_day: Mapped[int] = mapped_column(default=0)
    last_digest_sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class DigestRun(Base):
    __tablename__ = "digest_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    window_start: Mapped[datetime] = mapped_column()
    window_end: Mapped[datetime] = mapped_column()
    status: Mapped[DigestRunStatus] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class DigestEmail(Base):
    __tablename__ = "digest_emails"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    digest_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("digest_runs.id"), unique=True)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    html_body: Mapped[str] = mapped_column(String, nullable=False)
    text_body: Mapped[str] = mapped_column(String, nullable=False)
    sender_name: Mapped[str] = mapped_column(String, nullable=False)
    send_result: Mapped[EmailSendResult] = mapped_column()
    send_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
