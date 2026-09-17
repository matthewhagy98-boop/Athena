import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from evidence_engine.db.models import Base


class TopicActivitySnapshot(Base):
    """One topic's activity for one 7-day window, within one job generation.

    Rows are immutable and disposable: the job writes a whole generation, then flips
    dashboard_job_state.current_generation_id to point at it. Readers only ever see a
    completed generation, which is what keeps a half-written run invisible.
    """

    __tablename__ = "topic_activity_snapshots"
    __table_args__ = (
        UniqueConstraint("generation_id", "topic_id", name="uq_activity_generation_topic"),
        # The exact shape of the read query: newest generation, ordered by rank.
        Index("ix_activity_generation_rank", "generation_id", "rank"),
        Index("ix_activity_computed_at", "computed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    window_end: Mapped[datetime] = mapped_column(nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_paper_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consensus_updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradiction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retraction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_mean: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    baseline_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Null exactly when baseline_weeks < 8. NUMERIC rather than float so a stored rank
    # cannot drift with binary-float representation.
    trend_score: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    is_newly_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)


class DashboardJobState(Base):
    """Single logical row per job name.

    Follows the single-row-watermark precedent of SearchIndexSyncState
    (webapp/models.py:25). current_generation_id is the contract with readers: it is
    advanced only after a run completes.
    """

    __tablename__ = "dashboard_job_state"
    __table_args__ = (UniqueConstraint("job_name", name="uq_dashboard_job_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(String, nullable=False)
    current_generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    running_generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="idle")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    topics_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    topics_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DashboardRateWindow(Base):
    """Per-user request counter for POST /interests.

    C owns this rather than sharing a table with sub-project B: B shipped without a
    rate-window table, and its rate limiting is separate in-flight work (plan decision,
    OQ-C-004). A later consolidation can merge the two.
    """

    __tablename__ = "dashboard_rate_windows"
    __table_args__ = (
        UniqueConstraint("subject", "window_start", name="uq_dashboard_rate_subject_window"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Opaque so the table is not FK-bound to users: an anonymous id that is later purged
    # must not take its counter rows with it, and must not fail an insert either.
    subject: Mapped[str] = mapped_column(String, nullable=False)
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
