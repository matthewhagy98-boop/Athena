from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from evidence_engine.db.models import Topic


@dataclass
class RawPaper:
    source: str
    pmid: str | None = None
    doi: str | None = None
    nct_id: str | None = None
    semantic_scholar_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = field(default_factory=list)
    journal: str | None = None
    journal_issn: str | None = None
    pub_date: date | None = None
    publication_types: list[str] = field(default_factory=list)
    citation_count: int | None = None
    registered_sample_size: int | None = None
    trial_status: str | None = None
    raw_metadata: dict = field(default_factory=dict)


class SourceAdapter(Protocol):
    def fetch_new(self, topic: Topic, since: datetime | None) -> list[RawPaper]: ...
