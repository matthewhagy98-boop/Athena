import uuid
from collections.abc import Generator
from datetime import date, datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from citations.aggregate import saved_search_velocity
from citations.read import get_citation_history, get_paper_velocities
from dashboard import flags as dashboard_flags
from dashboard.activity import read_current_activity
from dashboard.changes import read_change_feed
from dashboard.interests import RateLimitExceeded, add_user_interest, remove_user_interest
from dashboard.personal import personal_topic_summary, render_blurb
from digest.models import User
from digest.profiles import create_anonymous_user
from evidence_engine.db.models import EvidenceTier, Paper, PaperTopic, StudyType, Topic
from evidence_engine.db.session import SessionLocal

from synthesis.service import get_or_create_synthesis
from webapp.compare import compare_papers, compare_topics
from webapp.saved_searches import (
    _get_owned_saved_search,
    create_saved_search,
    delete_saved_search,
    list_saved_searches,
    run_saved_search,
)
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


def _topics_by_paper(db: Session, paper_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    if not paper_ids:
        return {}
    rows = db.execute(
        select(PaperTopic.paper_id, Topic.id, Topic.canonical_label)
        .join(Topic, Topic.id == PaperTopic.topic_id)
        .where(PaperTopic.paper_id.in_(paper_ids))
        .order_by(Topic.canonical_label)
    ).all()
    out: dict[uuid.UUID, list[dict]] = {}
    for paper_id, topic_id, label in rows:
        out.setdefault(paper_id, []).append({"id": str(topic_id), "canonical_label": label})
    return out


def _paper_out(row, topics_by_paper: dict) -> dict:
    return {
        "paper": {
            "id": str(row.paper.id),
            "title": row.paper.title,
            "abstract": row.paper.abstract,
            "pub_date": row.paper.pub_date.isoformat() if row.paper.pub_date else None,
        },
        "score": {
            "evidence_tier": row.score.evidence_tier.value,
            "study_type": row.score.study_type.value if row.score.study_type else None,
            "final_score": row.score.final_score,
        }
        if row.score and not row.score.is_pending
        else None,
        "topics": topics_by_paper.get(row.paper.id, []),
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
    topics_map = _topics_by_paper(db, [row.paper.id for row in result.rows])
    return {
        "rows": [_paper_out(row, topics_map) for row in result.rows],
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
    }


@app.get("/compare/papers")
def compare_papers_endpoint(paper_ids: list[uuid.UUID] = Query(default_factory=list), db: Session = Depends(get_db)) -> dict:
    result = compare_papers(db, paper_ids)
    topics_map = _topics_by_paper(db, [row.paper.id for row in result.rows])
    return {
        "rows": [_paper_out(row, topics_map) for row in result.rows],
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
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "query_params": s.query_params,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        }
        for s in list_saved_searches(db, user)
    ]


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
    topics_map = _topics_by_paper(db, [row.paper.id for row in page.rows])
    return {
        "rows": [_paper_out(row, topics_map) for row in page.rows],
        "total": page.total,
        "page": page.page,
        "page_size": page.page_size,
    }


@app.post("/users/anonymous", status_code=201)
def create_anonymous_user_endpoint(db: Session = Depends(get_db)) -> dict:
    user = create_anonymous_user(db)
    return {"user_id": str(user.id)}


@app.get("/topics")
def list_topics_endpoint(db: Session = Depends(get_db)) -> list[dict]:
    topics = db.execute(select(Topic).order_by(Topic.canonical_label)).scalars().all()
    return [{"id": str(t.id), "canonical_label": t.canonical_label} for t in topics]


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


MAX_VELOCITY_IDS = 100


@app.get("/papers/velocity")
def paper_velocity_endpoint(
    paper_ids: list[uuid.UUID] = Query(default_factory=list), db: Session = Depends(get_db)
) -> dict:
    if not paper_ids or len(paper_ids) > MAX_VELOCITY_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"paper_ids must contain between 1 and {MAX_VELOCITY_IDS} identifiers",
        )
    velocities = get_paper_velocities(db, paper_ids)
    return {"velocities": {str(pid): block for pid, block in velocities.items()}}


@app.get("/papers/{paper_id}/citation-history")
def citation_history_endpoint(
    paper_id: uuid.UUID, days: int = Query(default=365, ge=30, le=1095), db: Session = Depends(get_db)
) -> dict:
    if db.get(Paper, paper_id) is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
    return get_citation_history(db, paper_id, days=days)


@app.get("/saved-searches/{saved_search_id}/velocity")
def saved_search_velocity_endpoint(
    saved_search_id: uuid.UUID,
    user_id: uuid.UUID,
    weeks: int = Query(default=12, ge=4, le=52),
    db: Session = Depends(get_db),
) -> dict:
    user = _require_user(db, user_id)
    try:
        saved = _get_owned_saved_search(db, user, saved_search_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return saved_search_velocity(db, saved, weeks=weeks)


MAX_SYNTHESIS_MEMBERS = 10


def _synthesis_out(row) -> dict:
    return {
        "id": str(row.id),
        "status": row.status,
        "narrative": row.narrative,
        "claims": row.claims,
        "disagreements": row.disagreements,
        "strength_ranking": row.strength_ranking,
        "retracted_member_indices": row.retracted_member_indices,
        "failure_reason": row.failure_reason,
        "subject_ids": [str(i) for i in row.subject_ids],
        # Provenance: spec line 16 requires a visible line naming the model and when the
        # narrative was generated. A reader deciding how much weight to give AI-written
        # prose needs to know which model wrote it and how stale it is.
        "model_id": row.model_id,
        "generated_at": row.generated_at.isoformat() + "Z" if row.generated_at else None,
    }


@app.post("/synthesis/papers")
def synthesis_papers_endpoint(payload: dict, db: Session = Depends(get_db)) -> dict:
    raw_ids = payload.get("paper_ids") or []
    if not raw_ids or len(raw_ids) > MAX_SYNTHESIS_MEMBERS:
        raise HTTPException(
            status_code=422,
            detail=f"paper_ids must contain between 1 and {MAX_SYNTHESIS_MEMBERS} ids",
        )
    try:
        paper_ids = [uuid.UUID(str(i)) for i in raw_ids]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="paper_ids must be UUIDs") from exc

    # Parsed outside the block below on purpose. A ValueError from the service means
    # "that paper id does not exist", which is a 404; a malformed user_id is a bad
    # request shape. Parsing it inside that try mapped it to "paper not found", which is
    # both the wrong status and a misleading message about the wrong field.
    raw_user_id = payload.get("user_id")
    try:
        user_id = uuid.UUID(raw_user_id) if raw_user_id else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="user_id must be a UUID") from exc

    # An id that is well-formed but no longer in `users` is dropped rather than passed
    # through. SynthesisGeneration.user_id is a FK, so an unknown id raises IntegrityError
    # from the telemetry insert -- after the model call, and not a ValueError, so the
    # handler below misses it and get_db rolls the whole transaction back. The result is
    # one paid generation discarded, no cached row, no cooldown, a 500, and a panel
    # message inviting the user to try again at full price, forever.
    #
    # Deliberately not _require_user: this is attribution for a telemetry row, and the
    # column is nullable with ON DELETE SET NULL. Losing the attribution is the correct
    # degradation; failing the request is not. Anonymous ids live in localStorage
    # indefinitely, so a stale one long outlives the row it names.
    if user_id is not None and db.get(User, user_id) is None:
        user_id = None

    try:
        row = get_or_create_synthesis(db, "paper", paper_ids, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if row is None:
        raise HTTPException(status_code=503, detail="Synthesis is not enabled")
    return _synthesis_out(row)


def require_dashboard_enabled() -> None:
    """404, per spec section 20: a disabled dashboard is indistinguishable from a
    deployment where it was never added.

    The plan originally said 503, reasoning by analogy with /synthesis/papers. That
    analogy does not hold: the synthesis route is permanently present and merely declines
    to generate, whereas this feature is meant to be invisible until it is turned on. 503
    also advertises the feature's existence to anyone probing, which is the thing the
    spec's reasoning cares about. The plan contradicted the spec; the spec wins.

    Wired as a route-level `dependencies=[Depends(...)]`, NOT called from the handler
    body. That distinction is the whole point and the first version got it wrong.

    FastAPI validates a route's declared parameters before the handler body runs, so an
    in-body check never executes for a route with required params. Measured against the
    in-body version with the flag off: /dashboard/activity returned 503, but
    /dashboard/personal with a missing or malformed user_id returned 422, and
    DELETE /interests likewise for both its path and query params -- four of five routes
    disclosing parameter names, locations and types to a caller who cannot use the route.
    The previous docstring claimed the ordering prevented exactly that.

    Decorator dependencies are inserted at the front of the dependant tree, so this runs
    before the endpoint's own validation -- and before `Depends(get_db)`, so a disabled
    route no longer opens and closes a database session either.
    """
    if not dashboard_flags.dashboard_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


def _is_gated_path(path: str) -> bool:
    """The five routes the flag hides.

    `/features` is deliberately absent: the client has to be able to ask whether the
    dashboard exists, so it is never gated. There was a `_GATED_PREFIXES` tuple here that
    this function never consulted -- dead, and worse, it stated the rule a second time
    where the two could drift apart.
    """
    return path == "/interests" or path.startswith("/interests/") or path.startswith("/dashboard/")


@app.middleware("http")
async def gate_dashboard_before_the_body_is_read(request: Request, call_next):
    """The gate, moved in front of request parsing entirely.

    The route-level dependency below precedes every query and path validation, which is
    what it was written for. It cannot precede body *parsing*: FastAPI reads and
    JSON-decodes a declared body before it solves dependencies. So `POST /interests` with
    a malformed body still answered, flag off,

        422 {"detail":[{"type":"json_invalid","loc":["body",1],"msg":"JSON decode error"...

    while every other probe returned 404 -- and since an unrouted path answers 405 from
    the StaticFiles mount, that 422 was a positive existence signal for the one route the
    spec wants indistinguishable from never-deployed.

    Middleware runs before routing, so nothing about the request has been interpreted yet.
    The route dependency stays as well: it keeps the guarantee local to each route where
    the next reader will look, and two cheap checks are worth more than one for a kill
    switch.

    "It is independently tested" is what this comment used to say, and it was false:
    either layer alone produces the same 404s, so no behavioural test could distinguish
    them. Deleting all five dependencies left the suite at 549 passed, and neutering this
    middleware left the five discriminating-input tests passing. Both are now pinned --
    the dependencies structurally (there is no behavioural way), the middleware by the one
    request shape only it can intercept, a malformed body.

    A `bytes` body was tried first and does not work -- FastAPI still JSON-decodes it. An
    `async def` handler awaiting `request.json()` would work but would put this route's
    blocking SQLAlchemy calls on the event loop, since every other handler here is sync
    and runs in the threadpool.
    """
    if _is_gated_path(request.url.path) and not dashboard_flags.dashboard_enabled():
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return await call_next(request)


def _openapi_without_disabled_routes():
    """Keep the gated routes out of the published schema while the flag is off.

    `/openapi.json` and `/docs` listed all five routes with every parameter name,
    location, type and default -- strictly more disclosure than the 422s the gate was
    written to suppress, and the one thing that made "indistinguishable from a deployment
    where it was never added" plainly false. Nothing covered it.

    Computed per request rather than cached, because the flag is read at call time
    everywhere else in this module and a cached schema would answer for the wrong state
    after a restart-free flip in a test or a reload.
    """
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    if not dashboard_flags.dashboard_enabled():
        schema["paths"] = {
            path: item
            for path, item in schema.get("paths", {}).items()
            if not _is_gated_path(path)
        }
    return schema


app.openapi = _openapi_without_disabled_routes


@app.get("/dashboard/activity", dependencies=[Depends(require_dashboard_enabled)])
def dashboard_activity_endpoint(
    limit: int = Query(default=10), db: Session = Depends(get_db)
) -> dict:
    if not 1 <= limit <= 25:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 25")
    return read_current_activity(db, limit=limit)


@app.get("/dashboard/changes", dependencies=[Depends(require_dashboard_enabled)])
def dashboard_changes_endpoint(
    days: int = Query(default=7), limit: int = Query(default=20), db: Session = Depends(get_db)
) -> dict:
    if not 1 <= days <= 30:
        raise HTTPException(status_code=422, detail="days must be between 1 and 30")
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50")
    return read_change_feed(db, days=days, limit=limit)


@app.get("/dashboard/personal", dependencies=[Depends(require_dashboard_enabled)])
def dashboard_personal_endpoint(
    user_id: uuid.UUID, days: int = Query(default=7), db: Session = Depends(get_db)
) -> dict:
    if not 1 <= days <= 30:
        raise HTTPException(status_code=422, detail="days must be between 1 and 30")
    try:
        summary = personal_topic_summary(db, user_id, days=days)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # The blurb is deterministic and computed here rather than client-side, so the copy
    # rules live in one tested place. `days` is passed explicitly: the sentence names its
    # own window, and without it a 30-day request was described as "this week".
    summary["blurb"] = render_blurb(summary, days)
    return summary


@app.get("/features")
def features_endpoint() -> dict:
    """Flags the client needs in order to decide what to render.

    Not gated: a client must be able to ask whether a feature is on. Returns only
    booleans that are already public in effect -- never secrets, and never anything
    user-specific, so it stays cacheable and needs no auth.
    """
    return {"dashboard_enabled": dashboard_flags.dashboard_enabled()}


@app.post("/interests", status_code=201, dependencies=[Depends(require_dashboard_enabled)])
def add_interest_endpoint(payload: dict, response: Response, db: Session = Depends(get_db)) -> dict:
    raw_user_id = payload.get("user_id")
    try:
        user_id = uuid.UUID(str(raw_user_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="user_id must be a UUID") from exc

    try:
        topic, created = add_user_interest(db, user_id, payload.get("free_text") or "")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RateLimitExceeded as exc:
        # 429, not 422: the request is well-formed and will succeed later.
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not created:
        response.status_code = 200
    return {
        "topic": {"id": str(topic.id), "canonical_label": topic.canonical_label},
        "created": created,
    }


@app.delete("/interests/{topic_id}", status_code=204, dependencies=[Depends(require_dashboard_enabled)])
def remove_interest_endpoint(
    topic_id: uuid.UUID, user_id: uuid.UUID, db: Session = Depends(get_db)
) -> Response:
    try:
        remove_user_interest(db, user_id, topic_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


from pathlib import Path

from fastapi.staticfiles import StaticFiles

_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
