from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from enterprise_api.models import Organization, RateLimitWindow


class RateLimitExceededError(Exception):
    def __init__(self, limit: int, window_start: datetime):
        self.limit = limit
        self.window_start = window_start
        super().__init__(f"Rate limit of {limit} requests/hour exceeded for window starting {window_start.isoformat()}")


def _current_window_start(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def enforce_rate_limit(session: Session, organization: Organization, now: datetime | None = None) -> None:
    now = now if now is not None else datetime.utcnow()
    window_start = _current_window_start(now)

    stmt = (
        pg_insert(RateLimitWindow)
        .values(organization_id=organization.id, window_start=window_start, request_count=1)
        .on_conflict_do_update(
            index_elements=[RateLimitWindow.organization_id, RateLimitWindow.window_start],
            set_={"request_count": RateLimitWindow.request_count + 1},
        )
        .returning(RateLimitWindow.request_count)
    )
    request_count = session.execute(stmt).scalar_one()
    session.flush()

    if request_count > organization.rate_limit_per_hour:
        raise RateLimitExceededError(organization.rate_limit_per_hour, window_start)
