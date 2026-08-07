import logging
from datetime import datetime

from sqlalchemy.orm import Session

from citations.models import CitationRefreshState
from citations.provider import SemanticScholarCitationClient
from citations.refresh import refresh_citations
from citations.velocity import recompute_all
from evidence_engine.config import get_settings

logger = logging.getLogger(__name__)


def _tracking_enabled() -> bool:
    return get_settings().citation_tracking_enabled


def run_citation_refresh(
    session: Session, client=None, now: datetime | None = None
) -> CitationRefreshState | None:
    """Collect today's snapshots, then recompute derived velocity.

    Returns None without contacting the provider when the feature is disabled.
    """
    if not _tracking_enabled():
        logger.info("CITATION_TRACKING_ENABLED is false; skipping citation refresh")
        return None

    client = client or SemanticScholarCitationClient()
    state = refresh_citations(session, client, now=now)
    recompute_all(session, now=now)
    logger.info(
        "Citation refresh complete: %s refreshed, %s failed, %s anomalies",
        state.papers_refreshed,
        state.papers_failed,
        state.anomalies_detected,
    )
    return state
