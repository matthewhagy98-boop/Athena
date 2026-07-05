import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from evidence_engine.db.models import Base


class PaperSearchIndex(Base):
    __tablename__ = "paper_search_index"
    __table_args__ = (Index("ix_paper_search_index_vector", "search_vector", postgresql_using="gin"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id"), unique=True)
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    topic_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    evidence_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    study_type: Mapped[str | None] = mapped_column(String, nullable=True)
    publication_date: Mapped[date | None] = mapped_column(nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class SearchIndexSyncState(Base):
    __tablename__ = "search_index_sync_state"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    last_synced_at: Mapped[datetime] = mapped_column(nullable=False)


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    query_params: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
