import hashlib
import secrets
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from enterprise_api.models import DEFAULT_RATE_LIMIT_PER_HOUR, ApiKey, Organization

KEY_PREFIX_LENGTH = 8


def hash_api_key(plaintext_key: str) -> str:
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()


def create_organization(
    session: Session, name: str, rate_limit_per_hour: int = DEFAULT_RATE_LIMIT_PER_HOUR
) -> Organization:
    organization = Organization(name=name, rate_limit_per_hour=rate_limit_per_hour)
    session.add(organization)
    session.flush()
    return organization


def create_api_key(session: Session, organization: Organization) -> tuple[ApiKey, str]:
    plaintext_key = secrets.token_urlsafe(32)
    api_key = ApiKey(
        organization_id=organization.id,
        key_hash=hash_api_key(plaintext_key),
        key_prefix=plaintext_key[:KEY_PREFIX_LENGTH],
    )
    session.add(api_key)
    session.flush()
    return api_key, plaintext_key


def revoke_api_key(session: Session, api_key_id: uuid.UUID) -> None:
    api_key = session.get(ApiKey, api_key_id)
    if api_key is None:
        raise ValueError(f"API key {api_key_id} not found")
    api_key.revoked_at = datetime.utcnow()
    session.flush()
