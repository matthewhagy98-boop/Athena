import logging

from digest.runner import run_all_due_digests
from evidence_engine.db.session import SessionLocal

logging.basicConfig(level=logging.INFO)


def main() -> None:
    run_all_due_digests(SessionLocal)


if __name__ == "__main__":
    main()
