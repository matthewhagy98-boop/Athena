from sqlalchemy import select
from sqlalchemy.orm import Session

from enterprise_api.models import ApiKey, Organization
from enterprise_api.provisioning import hash_api_key


class AuthenticationError(Exception):
    pass


class OrganizationSuspendedError(Exception):
    pass


def authenticate_api_key(session: Session, authorization_header: str | None) -> Organization:
    if not authorization_header or not authorization_header.startswith("Bearer "):
        raise AuthenticationError("Missing or malformed Authorization header")

    plaintext_key = authorization_header.removeprefix("Bearer ").strip()
    key_hash = hash_api_key(plaintext_key)

    api_key = session.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    ).scalar_one_or_none()
    if api_key is None:
        raise AuthenticationError("Invalid or revoked API key")

    # api_key.organization_id is a non-nullable FK to organizations.id, and nothing in this
    # package ever deletes an Organization, so this lookup cannot return None in practice.
    organization = session.get(Organization, api_key.organization_id)
    if organization.status == "suspended":
        raise OrganizationSuspendedError(f"Organization {organization.id} is suspended")

    return organization
