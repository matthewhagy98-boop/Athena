import argparse
import logging

from enterprise_api.models import DEFAULT_RATE_LIMIT_PER_HOUR
from enterprise_api.provisioning import create_api_key, create_organization
from evidence_engine.db.session import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("provision_organization")


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a new organization and its first API key")
    parser.add_argument("name", help="Organization name")
    parser.add_argument("--rate-limit-per-hour", type=int, default=DEFAULT_RATE_LIMIT_PER_HOUR)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        organization = create_organization(session, args.name, rate_limit_per_hour=args.rate_limit_per_hour)
        api_key, plaintext_key = create_api_key(session, organization)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Failed to provision organization %s", args.name)
        raise
    finally:
        session.close()

    print(f"Organization created: {organization.id} ({organization.name})")
    print(f"Rate limit: {organization.rate_limit_per_hour} requests/hour")
    print(f"API key (shown once, store securely): {plaintext_key}")


if __name__ == "__main__":
    main()
