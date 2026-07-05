import uuid
from collections.abc import Generator
from datetime import date, datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from digest.models import User
from evidence_engine.db.models import EvidenceTier, StudyType, Topic
from evidence_engine.db.session import SessionLocal

from webapp.compare import compare_papers, compare_topics
from webapp.saved_searches import create_saved_search, delete_saved_search, list_saved_searches, run_saved_search
from webapp.search import SearchFilters, search_papers
from webapp.visualizations import change_timeline, tier_distribution

app = FastAPI(title="Research Intelligence Platform — Search API")


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


def _paper_out(row) -> dict:
    return {
        "paper": {"id": str(row.paper.id), "title": row.paper.title, "pub_date": row.paper.pub_date.isoformat() if row.paper.pub_date else None},
        "score": {"evidence_tier": row.score.evidence_tier.value, "final_score": row.score.final_score} if row.score else None,
    }


@app.get("/search")
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


@app.get("/compare/papers")
def compare_papers_endpoint(paper_ids: list[uuid.UUID] = Query(default_factory=list), db: Session = Depends(get_db)) -> dict:
    result = compare_papers(db, paper_ids)
    return {
        "rows": [_paper_out(row) for row in result.rows],
        "unresolved_ids": [str(pid) for pid in result.unresolved_ids],
    }


@app.get("/compare/topics")
def compare_topics_endpoint(topic_ids: list[uuid.UUID] = Query(default_factory=list), db: Session = Depends(get_db)) -> dict:
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


def _require_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


@app.post("/saved-searches")
def create_saved_search_endpoint(payload: dict, db: Session = Depends(get_db)) -> dict:
    user = _require_user(db, uuid.UUID(payload["user_id"]))
    saved = create_saved_search(db, user, payload["name"], payload["query_params"])
    return {"id": str(saved.id), "name": saved.name, "query_params": saved.query_params}


@app.get("/saved-searches")
def list_saved_searches_endpoint(user_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict]:
    user = _require_user(db, user_id)
    return [{"id": str(s.id), "name": s.name, "query_params": s.query_params} for s in list_saved_searches(db, user)]


@app.delete("/saved-searches/{saved_search_id}", status_code=204)
def delete_saved_search_endpoint(saved_search_id: uuid.UUID, user_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    user = _require_user(db, user_id)
    try:
        delete_saved_search(db, user, saved_search_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/saved-searches/{saved_search_id}/run")
def run_saved_search_endpoint(saved_search_id: uuid.UUID, user_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    user = _require_user(db, user_id)
    try:
        page = run_saved_search(db, user, saved_search_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "rows": [_paper_out(row) for row in page.rows],
        "total": page.total,
        "page": page.page,
        "page_size": page.page_size,
    }


@app.get("/topics/{topic_id}/tier-distribution")
def tier_distribution_endpoint(topic_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    if db.get(Topic, topic_id) is None:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    distribution = tier_distribution(db, topic_id)
    return {"established": distribution.established, "emerging": distribution.emerging, "speculative": distribution.speculative}


@app.get("/topics/{topic_id}/timeline")
def timeline_endpoint(
    topic_id: uuid.UUID, window_start: datetime, window_end: datetime, db: Session = Depends(get_db)
) -> list[dict]:
    if db.get(Topic, topic_id) is None:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    buckets = change_timeline(db, topic_id, window_start, window_end)
    return [
        {"bucket_date": b.bucket_date.isoformat(), "event_type": b.event_type.value, "count": b.count} for b in buckets
    ]
