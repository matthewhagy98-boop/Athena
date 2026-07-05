from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from enterprise_api.models import ApiKey, Organization, RateLimitWindow


def test_organization_round_trip_with_defaults(db_session):
    organization = Organization(name="Acme Corp")
    db_session.add(organization)
    db_session.flush()

    fetched = db_session.get(Organization, organization.id)
    assert fetched.name == "Acme Corp"
    assert fetched.status == "active"
    assert fetched.rate_limit_per_hour == 1000


def test_api_key_round_trip_and_revocation(db_session):
    organization = Organization(name="Beta Inc")
    db_session.add(organization)
    db_session.flush()

    api_key = ApiKey(organization_id=organization.id, key_hash="hash123", key_prefix="abcd1234")
    db_session.add(api_key)
    db_session.flush()

    fetched = db_session.get(ApiKey, api_key.id)
    assert fetched.key_prefix == "abcd1234"
    assert fetched.revoked_at is None

    fetched.revoked_at = datetime(2026, 7, 5)
    db_session.flush()
    assert db_session.get(ApiKey, api_key.id).revoked_at == datetime(2026, 7, 5)


def test_api_key_hash_uniqueness_enforced(db_session):
    organization = Organization(name="Gamma LLC")
    db_session.add(organization)
    db_session.flush()

    db_session.add(ApiKey(organization_id=organization.id, key_hash="duplicate-hash", key_prefix="aaaa1111"))
    db_session.flush()

    db_session.add(ApiKey(organization_id=organization.id, key_hash="duplicate-hash", key_prefix="bbbb2222"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_rate_limit_window_unique_constraint_rejects_duplicate_window(db_session):
    organization = Organization(name="Delta Co")
    db_session.add(organization)
    db_session.flush()

    window_start = datetime(2026, 7, 5, 10, 0, 0)
    db_session.add(RateLimitWindow(organization_id=organization.id, window_start=window_start, request_count=1))
    db_session.flush()

    db_session.add(RateLimitWindow(organization_id=organization.id, window_start=window_start, request_count=1))
    with pytest.raises(IntegrityError):
        db_session.flush()
