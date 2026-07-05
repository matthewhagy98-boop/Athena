import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from evidence_engine.db.models import Paper, Score

from webapp.models import PaperSearchIndex


@dataclass
class SearchFilters:
    topic_id: uuid.UUID | None = None
    tier: str | None = None
    study_type: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    include_retracted: bool = False


@dataclass
class SearchResultRow:
    paper: Paper
    score: Score | None


@dataclass
class SearchPage:
    rows: list[SearchResultRow] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


def search_papers(
    session: Session,
    query: str | None,
    filters: SearchFilters,
    page: int = 1,
    page_size: int = 20,
) -> SearchPage:
    stmt = select(PaperSearchIndex, Paper).join(Paper, Paper.id == PaperSearchIndex.paper_id)

    if not filters.include_retracted:
        stmt = stmt.where(Paper.is_retracted.is_(False))
    if filters.topic_id is not None:
        stmt = stmt.where(PaperSearchIndex.topic_ids.contains([filters.topic_id]))
    if filters.tier is not None:
        stmt = stmt.where(PaperSearchIndex.evidence_tier == filters.tier)
    if filters.study_type is not None:
        stmt = stmt.where(PaperSearchIndex.study_type == filters.study_type)
    if filters.date_from is not None:
        stmt = stmt.where(PaperSearchIndex.publication_date >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(PaperSearchIndex.publication_date <= filters.date_to)

    rank_column = None
    if query:
        tsquery = func.plainto_tsquery("english", query)
        stmt = stmt.where(PaperSearchIndex.search_vector.op("@@")(tsquery))
        rank_column = func.ts_rank(PaperSearchIndex.search_vector, tsquery)
        stmt = stmt.order_by(rank_column.desc(), PaperSearchIndex.id)
    else:
        stmt = stmt.order_by(PaperSearchIndex.publication_date.desc().nulls_last(), PaperSearchIndex.id)

    total = session.execute(
        select(func.count()).select_from(stmt.with_only_columns(PaperSearchIndex.id).subquery())
    ).scalar_one()

    paged_stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = []
    for index_row, paper in session.execute(paged_stmt).all():
        score = session.execute(select(Score).where(Score.paper_id == paper.id)).scalar_one_or_none()
        rows.append(SearchResultRow(paper=paper, score=score))

    return SearchPage(rows=rows, total=total, page=page, page_size=page_size)
