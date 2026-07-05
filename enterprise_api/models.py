import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from evidence_engine.db.models import Base

DEFAULT_RATE_LIMIT_PER_HOUR = 1000


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active")
    rate_limit_per_hour: Mapped[int] = mapped_column(default=DEFAULT_RATE_LIMIT_PER_HOUR)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class RateLimitWindow(Base):
    __tablename__ = "rate_limit_windows"
    __table_args__ = (UniqueConstraint("organization_id", "window_start"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    request_count: Mapped[int] = mapped_column(default=0)
