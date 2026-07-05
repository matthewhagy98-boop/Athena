import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from digest.models import User

from webapp.models import SavedSearch
from webapp.search import SearchFilters, SearchPage, search_papers


def create_saved_search(session: Session, user: User, name: str, query_params: dict) -> SavedSearch:
    saved = SavedSearch(user_id=user.id, name=name, query_params=query_params)
    session.add(saved)
    session.flush()
    return saved


def list_saved_searches(session: Session, user: User) -> list[SavedSearch]:
    return (
        session.execute(
            select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.created_at)
        )
        .scalars()
        .all()
    )


def _get_owned_saved_search(session: Session, user: User, saved_search_id: uuid.UUID) -> SavedSearch:
    saved = session.get(SavedSearch, saved_search_id)
    if saved is None or saved.user_id != user.id:
        raise ValueError(f"Saved search {saved_search_id} not found for this user")
    return saved


def delete_saved_search(session: Session, user: User, saved_search_id: uuid.UUID) -> None:
    saved = _get_owned_saved_search(session, user, saved_search_id)
    session.delete(saved)
    session.flush()


def _parse_date_param(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def run_saved_search(session: Session, user: User, saved_search_id: uuid.UUID) -> SearchPage:
    saved = _get_owned_saved_search(session, user, saved_search_id)
    params = dict(saved.query_params)

    query = params.pop("q", None)
    topic_id = params.pop("topic_id", None)
    filters = SearchFilters(
        topic_id=uuid.UUID(topic_id) if topic_id else None,
        tier=params.pop("tier", None),
        study_type=params.pop("study_type", None),
        date_from=_parse_date_param(params.pop("date_from", None)),
        date_to=_parse_date_param(params.pop("date_to", None)),
        include_retracted=params.pop("include_retracted", False),
    )

    page = search_papers(session, query=query, filters=filters)

    saved.last_run_at = datetime.utcnow()
    session.flush()
    return page
