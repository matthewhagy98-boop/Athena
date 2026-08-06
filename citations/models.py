import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from evidence_engine.db.models import Base


class CitationSnapshot(Base):
    """Append-only record of one provider observation. Never updated in place."""

    __tablename__ = "citation_snapshots"
    __table_args__ = (
        UniqueConstraint("paper_id", "observed_on", "source", name="uq_citation_snapshot_paper_day_source"),
        Index("ix_citation_snapshots_paper_observed", "paper_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    influential_citation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="semantic_scholar")
    is_anomalous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CitationVelocityCache(Base):
    """Derived, fully recomputable from snapshots."""

    __tablename__ = "citation_velocity_cache"
    __table_args__ = (
        UniqueConstraint("paper_id", name="uq_citation_velocity_paper"),
        Index("ix_citation_velocity_cohort", "cohort_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="insufficient_history")
    velocity_per_30d: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    window_start_observed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    window_end_observed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_observed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    percentile: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cohort_key: Mapped[str | None] = mapped_column(String, nullable=True)
    refresh_status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    anomaly_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)


class CitationRefreshState(Base):
    """One logical row per job, following the SearchIndexSyncState precedent."""

    __tablename__ = "citation_refresh_state"
    __table_args__ = (UniqueConstraint("job_name", name="uq_citation_refresh_job"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="idle")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    papers_refreshed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    papers_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batches_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rate_limit_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomalies_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
