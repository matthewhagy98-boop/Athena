import uuid
from collections.abc import Generator
from datetime import date, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy.orm import Session

from enterprise_api.auth import AuthenticationError, OrganizationSuspendedError, authenticate_api_key
from enterprise_api.models import Organization
from enterprise_api.rate_limit import RateLimitExceededError, enforce_rate_limit
from evidence_engine.db.models import EvidenceTier, StudyType, Topic
from evidence_engine.db.session import SessionLocal

from webapp.compare import compare_papers, compare_topics
from webapp.search import SearchFilters, search_papers
from webapp.visualizations import change_timeline, tier_distribution

app = FastAPI(title="Research Intelligence Platform — Enterprise API")


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_authenticated_organization(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Organization:
    try:
        organization = authenticate_api_key(db, authorization)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except OrganizationSuspendedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        enforce_rate_limit(db, organization)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail={"message": str(exc), "limit": exc.limit, "window_start": exc.window_start.isoformat()},
        ) from exc

    return organization


def _paper_out(row) -> dict:
    return {
        "paper": {
            "id": str(row.paper.id),
            "title": row.paper.title,
            "pub_date": row.paper.pub_date.isoformat() if row.paper.pub_date else None,
        },
        "score": {"evidence_tier": row.score.evidence_tier.value, "final_score": row.score.final_score}
        if row.score
        else None,
    }


@app.get("/v1/search")
def search_endpoint(
    q: str | None = None,
    topic_id: uuid.UUID | None = None,
    tier: EvidenceTier | None = None,
    study_type: StudyType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_retracted: bool = False,
    page: int = 1,
    page_size: int = 20,
    organization: Organization = Depends(get_authenticated_organization),
    db: Session = Depends(get_db),
) -> dict:
    filters = SearchFilters(
        topic_id=topic_id,
        tier=tier.value if tier else None,
        study_type=study_type.value if study_type else None,
        date_from=date_from,
        date_to=date_to,
        include_retracted=include_retracted,
    )
    result = search_papers(db, query=q, filters=filters, page=page, page_size=page_size)
    return {
        "rows": [_paper_out(row) for row in result.rows],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
    }


@app.get("/v1/compare/papers")
def compare_papers_endpoint(
    paper_ids: list[uuid.UUID] = Query(default_factory=list),
    organization: Organization = Depends(get_authenticated_organization),
    db: Session = Depends(get_db),
) -> dict:
    result = compare_papers(db, paper_ids)
    return {
        "rows": [_paper_out(row) for row in result.rows],
        "unresolved_ids": [str(pid) for pid in result.unresolved_ids],
    }


@app.get("/v1/compare/topics")
def compare_topics_endpoint(
    topic_ids: list[uuid.UUID] = Query(default_factory=list),
    organization: Organization = Depends(get_authenticated_organization),
    db: Session = Depends(get_db),
) -> dict:
    result = compare_topics(db, topic_ids)
    return {
        "rows": [
            {
                "topic": {"id": str(row.topic.id), "canonical_label": row.topic.canonical_label},
                "consensus": {"consensus_text": row.consensus.consensus_text} if row.consensus else None,
            }
            for row in result.rows
        ],
        "unresolved_ids": [str(tid) for tid in result.unresolved_ids],
    }


@app.get("/v1/topics/{topic_id}/tier-distribution")
def tier_distribution_endpoint(
    topic_id: uuid.UUID,
    organization: Organization = Depends(get_authenticated_organization),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(Topic, topic_id) is None:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    distribution = tier_distribution(db, topic_id)
    return {
        "established": distribution.established,
        "emerging": distribution.emerging,
        "speculative": distribution.speculative,
    }


@app.get("/v1/topics/{topic_id}/timeline")
def timeline_endpoint(
    topic_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
    organization: Organization = Depends(get_authenticated_organization),
    db: Session = Depends(get_db),
) -> list[dict]:
    if db.get(Topic, topic_id) is None:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    buckets = change_timeline(db, topic_id, window_start, window_end)
    return [
        {"bucket_date": b.bucket_date.isoformat(), "event_type": b.event_type.value, "count": b.count}
        for b in buckets
    ]
