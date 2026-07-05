import uuid

import pytest

from enterprise_api.models import ApiKey, Organization
from enterprise_api.provisioning import create_api_key, create_organization, hash_api_key, revoke_api_key


def test_create_organization_sets_defaults(db_session):
    organization = create_organization(db_session, "Acme Corp")

    assert organization.name == "Acme Corp"
    assert organization.status == "active"
    assert organization.rate_limit_per_hour == 1000


def test_create_organization_accepts_custom_rate_limit(db_session):
    organization = create_organization(db_session, "Beta Inc", rate_limit_per_hour=50)

    assert organization.rate_limit_per_hour == 50


def test_create_api_key_returns_plaintext_once_and_stores_only_hash(db_session):
    organization = create_organization(db_session, "Gamma LLC")

    api_key, plaintext_key = create_api_key(db_session, organization)

    assert len(plaintext_key) > 20
    assert api_key.key_hash == hash_api_key(plaintext_key)
    assert api_key.key_hash != plaintext_key
    assert api_key.key_prefix == plaintext_key[:8]
    assert api_key.revoked_at is None


def test_create_api_key_generates_distinct_keys_per_call(db_session):
    organization = create_organization(db_session, "Delta Co")

    _, plaintext_key_one = create_api_key(db_session, organization)
    _, plaintext_key_two = create_api_key(db_session, organization)

    assert plaintext_key_one != plaintext_key_two


def test_revoke_api_key_sets_revoked_at(db_session):
    organization = create_organization(db_session, "Epsilon Ltd")
    api_key, _ = create_api_key(db_session, organization)

    revoke_api_key(db_session, api_key.id)

    fetched = db_session.get(ApiKey, api_key.id)
    assert fetched.revoked_at is not None


def test_revoke_api_key_raises_for_unknown_id(db_session):
    with pytest.raises(ValueError):
        revoke_api_key(db_session, uuid.uuid4())
