"""Seed a demo topic with papers for local dev and the e2e smoke test."""

import argparse
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from dashboard.activity import refresh_activity_snapshots
from dashboard.trend import MIN_EVENTS
from dashboard.windows import BASELINE_WINDOWS, window_for
from evidence_engine.db.models import (
    ChangeEvent,
    ChangeEventType,
    EvidenceTier,
    Paper,
    PaperTopic,
    Score,
    StudyType,
    Topic,
)
from evidence_engine.db.session import SessionLocal
from webapp.search_index import sync_search_index

DEMO_TOPIC = "Demo: AI and Cognitive Mapping"

PAPERS = [
    ("Longitudinal analysis of neural plasticity under AI assistance", EvidenceTier.ESTABLISHED, StudyType.META_ANALYSIS, 88.0),
    ("Cognitive offloading and digital tool interaction: a systematic review", EvidenceTier.ESTABLISHED, StudyType.SYSTEMATIC_REVIEW, 76.0),
    ("Cross-cultural variance in generative AI adaptation", EvidenceTier.EMERGING, StudyType.RCT, 44.0),
    ("Attention residue in multi-agent workflows: a hypothesis", EvidenceTier.SPECULATIVE, StudyType.OPINION_EDITORIAL, 12.0),
]

# The demo topic's steady baseline-week volume and its current-window spike. The spike
# clears MIN_EVENTS with headroom and sits above the baseline, so the topic reads as
# genuinely trending rather than merely eligible.
_BASELINE_WEEKLY_EVENTS = 4
_CURRENT_WINDOW_EVENTS = 9
assert _CURRENT_WINDOW_EVENTS >= MIN_EVENTS

_DASHBOARD_EVENT_TYPES = (
    ChangeEventType.NEW_PAPER,
    ChangeEventType.CONSENSUS_UPDATED,
    ChangeEventType.CONTRADICTION_FLAGGED,
)


def _seed_dashboard_history(session: Session, topic: Topic, papers: list[Paper]) -> None:
    """Give the demo topic 9 weeks of `ChangeEvent` history for the Trending widget.

    Without this, a freshly seeded database has no events inside the daily job's
    rolling windows at all: the papers above carry fixed calendar dates (2026-01-15
    etc.) that only drift further into the past as time goes on, and fall outside
    every window `refresh_activity_snapshots` looks at long before this script is
    likely to run. The ranking would then be entirely empty rather than demonstrating
    both the cold-start ("newly tracked") and steady-state (scored, real trend_score)
    cases -- which reads as broken, not as correct behaviour.

    Idempotent and re-runnable: prior runs' windowed events for this topic are cleared
    and rebuilt relative to "now" every time, so the demo stays correct regardless of
    how long it has been since the database was first seeded.
    """
    now = datetime.utcnow()

    # Clear this function's own output from any previous run (including the anchor
    # event below) before rebuilding it, so repeated runs don't accumulate events.
    horizon = now - timedelta(days=(BASELINE_WINDOWS + 2) * 7)
    session.execute(
        delete(ChangeEvent).where(ChangeEvent.topic_id == topic.id, ChangeEvent.detected_at > horizon)
    )

    # Anchor: one event at-or-before the earliest baseline window's start. This is what
    # dashboard/activity.py's `weeks_tracked` predicate (`first <= window.start`) checks
    # to credit a topic with a complete baseline week, so without it the topic would
    # stay "newly tracked" forever regardless of how much windowed history it has.
    earliest_start = window_for(now, BASELINE_WINDOWS).start
    session.add(
        ChangeEvent(
            topic_id=topic.id,
            paper_id=papers[0].id,
            event_type=ChangeEventType.NEW_PAPER,
            detected_at=earliest_start - timedelta(days=1),
        )
    )

    # Eight complete, steady baseline weeks (indices 1..8), spread across the demo papers
    # and event types rather than piled onto one of each.
    for index in range(1, BASELINE_WINDOWS + 1):
        window = window_for(now, index)
        for n in range(_BASELINE_WEEKLY_EVENTS):
            session.add(
                ChangeEvent(
                    topic_id=topic.id,
                    paper_id=papers[n % len(papers)].id,
                    event_type=_DASHBOARD_EVENT_TYPES[n % len(_DASHBOARD_EVENT_TYPES)],
                    detected_at=window.start + timedelta(days=3, hours=n),
                )
            )

    # The current window (index 0): a spike above the baseline, so the topic reads as
    # trending up rather than merely present.
    current = window_for(now, 0)
    for n in range(_CURRENT_WINDOW_EVENTS):
        session.add(
            ChangeEvent(
                topic_id=topic.id,
                paper_id=papers[n % len(papers)].id,
                event_type=_DASHBOARD_EVENT_TYPES[n % len(_DASHBOARD_EVENT_TYPES)],
                detected_at=current.start + timedelta(days=3, hours=n),
            )
        )
    session.flush()


def main(argv: list[str] | None = None) -> None:
    """Converge the database on the demo state.

    Re-running is safe and is sometimes necessary: the test suite's
    `reset_leaked_state` fixture truncates `paper_search_index`, so a seeded topic can
    outlive its search-index rows. Existence of the topic therefore can't stand in for
    "fully seeded" -- the search index is rebuilt on every run, and so is the
    dashboard's windowed `ChangeEvent` history (see `_seed_dashboard_history`), since
    that history is relative to "now" and goes stale on its own.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dashboard-job",
        action="store_true",
        help=(
            "Also run refresh_activity_snapshots after seeding, so the dashboard has a "
            "published generation without a second command."
        ),
    )
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        topic = session.execute(select(Topic).where(Topic.canonical_label == DEMO_TOPIC)).scalar_one_or_none()
        if topic is None:
            topic = Topic(canonical_label=DEMO_TOPIC, mesh_id="D_DEMO_01")
            session.add(topic)
            session.flush()

            papers = []
            for i, (title, tier, study_type, score) in enumerate(PAPERS):
                paper = Paper(
                    title=title,
                    abstract=f"Demo abstract for: {title}.",
                    pub_date=date(2026, 1 + i, 15),
                )
                session.add(paper)
                session.flush()
                session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
                session.add(
                    Score(paper_id=paper.id, evidence_tier=tier, study_type=study_type, final_score=score, model_version="demo")
                )
                session.add(
                    ChangeEvent(
                        topic_id=topic.id,
                        paper_id=paper.id,
                        event_type=ChangeEventType.NEW_PAPER,
                        detected_at=datetime(2026, 1 + i, 16),
                    )
                )
                papers.append(paper)
            session.flush()
            print(f"Seeded demo topic {topic.id} with {len(PAPERS)} papers.")
        else:
            papers = [
                session.execute(select(Paper).where(Paper.title == title)).scalars().first()
                for title, *_ in PAPERS
            ]
            print(f"Demo topic {topic.id} already present; search index and dashboard history rebuilt.")

        _seed_dashboard_history(session, topic, papers)
        sync_search_index(session)
        session.commit()

        if args.run_dashboard_job:
            generation = refresh_activity_snapshots(session)
            session.commit()
            print(f"Dashboard activity refreshed (generation {generation}).")
    finally:
        session.close()


if __name__ == "__main__":
    main()
