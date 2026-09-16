import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from evidence_engine.db.models import Base


class ComparisonSynthesis(Base):
    """One generated narrative for an exact member set. Content-addressed by cache_key."""

    __tablename__ = "comparison_syntheses"
    __table_args__ = (
        Index(
            "uq_synthesis_active_cache_key",
            "cache_key",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index("ix_synthesis_generated_at", "generated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String, nullable=False)
    subject_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    inputs_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ready")
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    claims: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    disagreements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    strength_ranking: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    retracted_member_indices: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(nullable=True)
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    superseded_at: Mapped[datetime | None] = mapped_column(nullable=True)


class SynthesisGeneration(Base):
    """Cost and outcome telemetry, one row per generation attempt."""

    __tablename__ = "synthesis_generations"
    __table_args__ = (
        Index("ix_synthesis_generation_created", "created_at"),
        Index("ix_synthesis_generation_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    synthesis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comparison_syntheses.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated_member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
