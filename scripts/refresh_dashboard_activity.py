"""Daily dashboard activity refresh.

Run as a module so package imports resolve:
    arch -x86_64 /Users/matthewhagy/Athena/.venv/bin/python -m scripts.refresh_dashboard_activity
"""

import logging
import sys

from evidence_engine.db.session import SessionLocal
from dashboard.activity import JOB_NAME, refresh_activity_snapshots
from dashboard.models import DashboardJobState
from sqlalchemy import select

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = SessionLocal()
    try:
        generation = refresh_activity_snapshots(session)
        session.commit()
        logger.info("dashboard.activity_refreshed generation=%s", generation)
        return 0
    except Exception as exc:
        session.rollback()
        # Record the failure so the dashboard can surface staleness rather than the
        # operator discovering it from an empty widget.
        try:
            state = session.execute(
                select(DashboardJobState).where(DashboardJobState.job_name == JOB_NAME)
            ).scalar_one_or_none()
            if state is None:
                # No run has ever reached the point of creating this row (e.g. the
                # failure happened before refresh_activity_snapshots wrote it). Create
                # it so the failure is still recorded rather than silently dropped.
                state = DashboardJobState(job_name=JOB_NAME)
                session.add(state)
            state.status = "failed"
            state.running_generation_id = None
            state.last_error = str(exc)[:2000]
            session.commit()
        except Exception:  # pragma: no cover - the failure path must not mask the original
            session.rollback()
        logger.exception("dashboard.activity_refresh_failed")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
