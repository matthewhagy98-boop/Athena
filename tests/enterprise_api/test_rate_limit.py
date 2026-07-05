from datetime import datetime

import pytest
from sqlalchemy import select

from enterprise_api.models import RateLimitWindow
from enterprise_api.provisioning import create_organization
from enterprise_api.rate_limit import RateLimitExceededError, enforce_rate_limit


def test_enforce_rate_limit_allows_requests_under_limit(db_session):
    organization = create_organization(db_session, "Acme Corp", rate_limit_per_hour=3)
    now = datetime(2026, 7, 5, 10, 15, 0)

    enforce_rate_limit(db_session, organization, now=now)
    enforce_rate_limit(db_session, organization, now=now)
    enforce_rate_limit(db_session, organization, now=now)

    window = db_session.execute(
        select(RateLimitWindow).where(RateLimitWindow.organization_id == organization.id)
    ).scalar_one()
    assert window.request_count == 3


def test_enforce_rate_limit_raises_when_request_pushes_over_limit(db_session):
    organization = create_organization(db_session, "Beta Inc", rate_limit_per_hour=2)
    now = datetime(2026, 7, 5, 10, 15, 0)

    enforce_rate_limit(db_session, organization, now=now)
    enforce_rate_limit(db_session, organization, now=now)

    with pytest.raises(RateLimitExceededError) as exc_info:
        enforce_rate_limit(db_session, organization, now=now)
    assert exc_info.value.limit == 2


def test_enforce_rate_limit_resets_for_new_hour_window(db_session):
    organization = create_organization(db_session, "Gamma LLC", rate_limit_per_hour=1)
    first_hour = datetime(2026, 7, 5, 10, 30, 0)
    next_hour = datetime(2026, 7, 5, 11, 5, 0)

    enforce_rate_limit(db_session, organization, now=first_hour)
    with pytest.raises(RateLimitExceededError):
        enforce_rate_limit(db_session, organization, now=first_hour)

    enforce_rate_limit(db_session, organization, now=next_hour)  # new hour, fresh counter, should not raise

    windows = db_session.execute(
        select(RateLimitWindow).where(RateLimitWindow.organization_id == organization.id)
    ).scalars().all()
    assert len(windows) == 2


def test_enforce_rate_limit_isolates_per_organization(db_session):
    org_a = create_organization(db_session, "Delta Co", rate_limit_per_hour=1)
    org_b = create_organization(db_session, "Epsilon Ltd", rate_limit_per_hour=1)
    now = datetime(2026, 7, 5, 10, 15, 0)

    enforce_rate_limit(db_session, org_a, now=now)
    with pytest.raises(RateLimitExceededError):
        enforce_rate_limit(db_session, org_a, now=now)

    enforce_rate_limit(db_session, org_b, now=now)  # org_b's own limit is untouched by org_a's usage
