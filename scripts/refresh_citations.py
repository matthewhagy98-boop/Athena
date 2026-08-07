"""Collect daily citation snapshots and recompute velocity.

Run as a module from the repo root, matching the other scripts in this directory:

    CITATION_TRACKING_ENABLED=true python -m scripts.refresh_citations

Invoking the file by path fails to import the packages, since the repo root is
not on sys.path that way.

Gated by CITATION_TRACKING_ENABLED. Safe to run more than once a day: snapshots
are unique per (paper, day, source), so repeat runs are no-ops for papers already
observed today.
"""

import logging

from citations.runner import run_citation_refresh
from evidence_engine.db.session import SessionLocal


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    session = SessionLocal()
    try:
        state = run_citation_refresh(session)
        if state is None:
            print("Citation tracking disabled; nothing to do.")
        else:
            print(
                f"Refreshed {state.papers_refreshed} papers "
                f"({state.papers_failed} failed, {state.anomalies_detected} anomalies)."
            )
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()
