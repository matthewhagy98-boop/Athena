import enum
import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class StudyType(str, enum.Enum):
    META_ANALYSIS = "meta_analysis"
    SYSTEMATIC_REVIEW = "systematic_review"
    RCT = "rct"
    COHORT = "cohort"
    CASE_CONTROL = "case_control"
    CASE_SERIES = "case_series"
    OPINION_EDITORIAL = "opinion_editorial"
    UNKNOWN = "unknown"


class EvidenceTier(str, enum.Enum):
    ESTABLISHED = "established"
    EMERGING = "emerging"
    SPECULATIVE = "speculative"


class ChangeEventType(str, enum.Enum):
    NEW_PAPER = "new_paper"
    CONSENSUS_UPDATED = "consensus_updated"
    CONTRADICTION_FLAGGED = "contradiction_flagged"
    PAPER_RETRACTED = "paper_retracted"


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mesh_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    canonical_label: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    status: Mapped[str] = mapped_column(String, default="active")
    last_checked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pmid: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    doi: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    nct_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    semantic_scholar_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    abstract: Mapped[str | None] = mapped_column(String, nullable=True)
    authors: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    journal: Mapped[str | None] = mapped_column(String, nullable=True)
    journal_issn: Mapped[str | None] = mapped_column(String, nullable=True)
    pub_date: Mapped[date | None] = mapped_column(nullable=True)
    publication_types: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    is_retracted: Mapped[bool] = mapped_column(default=False)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)


class PaperTopic(Base):
    __tablename__ = "paper_topics"
    __table_args__ = (UniqueConstraint("paper_id", "topic_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id"))
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"))


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id"), unique=True)
    study_type: Mapped[StudyType] = mapped_column(default=StudyType.UNKNOWN)
    sample_size: Mapped[int | None] = mapped_column(nullable=True)
    citation_count: Mapped[int] = mapped_column(default=0)
    journal_sjr: Mapped[float | None] = mapped_column(nullable=True)
    base_score: Mapped[float] = mapped_column(default=0.0)
    risk_of_bias_flags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    final_score: Mapped[float] = mapped_column(default=0.0)
    evidence_tier: Mapped[EvidenceTier] = mapped_column(default=EvidenceTier.SPECULATIVE)
    quality_breakdown: Mapped[str | None] = mapped_column(String, nullable=True)
    is_pending: Mapped[bool] = mapped_column(default=False)
    scored_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    model_version: Mapped[str] = mapped_column(String, nullable=False)

    paper: Mapped["Paper"] = relationship()


class ConsensusSnapshot(Base):
    __tablename__ = "consensus_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"))
    consensus_text: Mapped[str | None] = mapped_column(String, nullable=True)
    is_insufficient_evidence: Mapped[bool] = mapped_column(default=False)
    supporting_paper_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    contradiction_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    model_version: Mapped[str] = mapped_column(String, nullable=False)


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"))
    paper_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("papers.id"), nullable=True)
    event_type: Mapped[ChangeEventType] = mapped_column()
    detected_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
