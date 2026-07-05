import pytest

from enterprise_api.auth import AuthenticationError, OrganizationSuspendedError, authenticate_api_key
from enterprise_api.provisioning import create_api_key, create_organization, revoke_api_key


def test_authenticate_api_key_resolves_organization_for_valid_key(db_session):
    organization = create_organization(db_session, "Acme Corp")
    _, plaintext_key = create_api_key(db_session, organization)

    resolved = authenticate_api_key(db_session, f"Bearer {plaintext_key}")

    assert resolved.id == organization.id


def test_authenticate_api_key_raises_for_missing_header(db_session):
    with pytest.raises(AuthenticationError):
        authenticate_api_key(db_session, None)


def test_authenticate_api_key_raises_for_malformed_header(db_session):
    organization = create_organization(db_session, "Beta Inc")
    _, plaintext_key = create_api_key(db_session, organization)

    with pytest.raises(AuthenticationError):
        authenticate_api_key(db_session, plaintext_key)  # missing "Bearer " prefix


def test_authenticate_api_key_raises_for_unknown_key(db_session):
    with pytest.raises(AuthenticationError):
        authenticate_api_key(db_session, "Bearer not-a-real-key")


def test_authenticate_api_key_raises_for_revoked_key(db_session):
    organization = create_organization(db_session, "Gamma LLC")
    api_key, plaintext_key = create_api_key(db_session, organization)
    revoke_api_key(db_session, api_key.id)

    with pytest.raises(AuthenticationError):
        authenticate_api_key(db_session, f"Bearer {plaintext_key}")


def test_authenticate_api_key_raises_organization_suspended_for_suspended_org(db_session):
    organization = create_organization(db_session, "Delta Co")
    _, plaintext_key = create_api_key(db_session, organization)
    organization.status = "suspended"
    db_session.flush()

    with pytest.raises(OrganizationSuspendedError):
        authenticate_api_key(db_session, f"Bearer {plaintext_key}")
