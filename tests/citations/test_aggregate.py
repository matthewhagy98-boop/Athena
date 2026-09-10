from datetime import date, datetime, timedelta
from decimal import Decimal

from citations.aggregate import MIN_COVERAGE_RATIO, median, saved_search_velocity
from citations.models import CitationVelocityCache
from digest.profiles import create_user
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
from webapp.models import SavedSearch
from webapp.search_index import sync_search_index


def test_median_of_odd_and_even_counts():
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_median_of_empty_is_none():
    assert median([]) is None


def _topic_with_papers(db_session, label, count, velocity, weeks_ago=1):
    topic = Topic(canonical_label=label, mesh_id=f"D_AGG_{label[:6]}")
    db_session.add(topic)
    db_session.flush()
    window_end = datetime(2026, 8, 1) - timedelta(weeks=weeks_ago)
    for i in range(count):
        paper = Paper(title=f"{label} paper {i}", abstract="Aggregate fixture.")
        db_session.add(paper)
        db_session.flush()
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
        db_session.add(
            ChangeEvent(topic_id=topic.id, paper_id=paper.id, event_type=ChangeEventType.NEW_PAPER)
        )
        db_session.add(
            Score(
                paper_id=paper.id,
                evidence_tier=EvidenceTier.ESTABLISHED,
                study_type=StudyType.RCT,
                final_score=70.0,
                model_version="v1",
            )
        )
        db_session.add(
            CitationVelocityCache(
                paper_id=paper.id,
                status="ready",
                velocity_per_30d=Decimal(str(velocity)),
                window_end_observed_at=window_end,
            )
        )
    db_session.flush()
    sync_search_index(db_session)
    return topic


def _saved_search(db_session, topic):
    user = create_user(db_session, f"agg-{topic.mesh_id}@example.com")
    saved = SavedSearch(
        user_id=user.id, name="Aggregate search", query_params={"topic_id": str(topic.id)}
    )
    db_session.add(saved)
    db_session.flush()
    return saved


def test_ready_when_coverage_is_sufficient(db_session):
    topic = _topic_with_papers(db_session, "Covered topic", count=12, velocity=4.0)
    saved = _saved_search(db_session, topic)

    result = saved_search_velocity(db_session, saved, weeks=12)

    assert result["status"] == "ready"
    assert result["papers_total"] == 12
    assert result["papers_with_history"] == 12
    assert result["series"], "expected at least one weekly point"
    assert all(p["median_velocity_per_30d"] == 4.0 for p in result["series"])


def test_insufficient_coverage_returns_no_series(db_session):
    # 1 of 12 papers has history: below the MIN_COVERAGE_RATIO floor, so a median
    # would describe one paper while appearing to describe the whole search.
    topic = Topic(canonical_label="Sparse topic", mesh_id="D_AGG_SPARSE")
    db_session.add(topic)
    db_session.flush()
    for i in range(12):
        paper = Paper(title=f"Sparse paper {i}")
        db_session.add(paper)
        db_session.flush()
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
        db_session.add(
            ChangeEvent(topic_id=topic.id, paper_id=paper.id, event_type=ChangeEventType.NEW_PAPER)
        )
        db_session.add(
            Score(
                paper_id=paper.id,
                evidence_tier=EvidenceTier.ESTABLISHED,
                study_type=StudyType.RCT,
                final_score=70.0,
                model_version="v1",
            )
        )
        if i == 0:
            db_session.add(
                CitationVelocityCache(
                    paper_id=paper.id,
                    status="ready",
                    velocity_per_30d=Decimal("9.00"),
                    window_end_observed_at=datetime(2026, 7, 25),
                )
            )
    db_session.flush()
    sync_search_index(db_session)
    saved = _saved_search(db_session, topic)

    result = saved_search_velocity(db_session, saved, weeks=12)

    assert result["status"] == "insufficient_coverage"
    assert result["series"] == []
    assert result["papers_total"] == 12
    assert result["papers_with_history"] == 1


def test_uses_median_not_mean(db_session):
    # One landmark paper must not drag the line.
    topic = Topic(canonical_label="Skewed topic", mesh_id="D_AGG_SKEW")
    db_session.add(topic)
    db_session.flush()
    velocities = [1.0] * 10 + [1000.0]
    for i, v in enumerate(velocities):
        paper = Paper(title=f"Skewed paper {i}")
        db_session.add(paper)
        db_session.flush()
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
        db_session.add(
            ChangeEvent(topic_id=topic.id, paper_id=paper.id, event_type=ChangeEventType.NEW_PAPER)
        )
        db_session.add(
            Score(
                paper_id=paper.id,
                evidence_tier=EvidenceTier.ESTABLISHED,
                study_type=StudyType.RCT,
                final_score=70.0,
                model_version="v1",
            )
        )
        db_session.add(
            CitationVelocityCache(
                paper_id=paper.id,
                status="ready",
                velocity_per_30d=Decimal(str(v)),
                window_end_observed_at=datetime(2026, 7, 25),
            )
        )
    db_session.flush()
    sync_search_index(db_session)
    saved = _saved_search(db_session, topic)

    result = saved_search_velocity(db_session, saved, weeks=12)

    # Mean would be ~91.8; median is 1.0.
    assert all(p["median_velocity_per_30d"] == 1.0 for p in result["series"])


def test_does_not_update_last_run_at(db_session):
    topic = _topic_with_papers(db_session, "Untouched topic", count=12, velocity=2.0)
    saved = _saved_search(db_session, topic)
    assert saved.last_run_at is None

    saved_search_velocity(db_session, saved, weeks=12)

    # This is a pure read; the saved search's own run history must be unaffected.
    assert saved.last_run_at is None


def test_string_dates_in_query_params_still_return_ready(db_session):
    # A saved search's query_params is free-form JSONB: dates and topic_id arrive
    # as strings, not the typed uuid.UUID/date SearchFilters declares. Passing them
    # through raw would compare a str against a typed column and either raise or
    # silently match nothing -- the latter is indistinguishable from a legitimate
    # cold-start "insufficient_coverage" and would hide the bug for weeks. Papers
    # need a pub_date inside the string date range so a broken (str-vs-date, or
    # NULL-excluding) comparison shows up as a coverage failure, not a tautology.
    topic = Topic(canonical_label="Coerced topic", mesh_id="D_AGG_COERCE")
    db_session.add(topic)
    db_session.flush()
    window_end = datetime(2026, 8, 1) - timedelta(weeks=1)
    for i in range(12):
        paper = Paper(
            title=f"Coerced paper {i}",
            abstract="Aggregate fixture.",
            pub_date=date(2026, 2, 15),
        )
        db_session.add(paper)
        db_session.flush()
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
        db_session.add(
            ChangeEvent(topic_id=topic.id, paper_id=paper.id, event_type=ChangeEventType.NEW_PAPER)
        )
        db_session.add(
            Score(
                paper_id=paper.id,
                evidence_tier=EvidenceTier.ESTABLISHED,
                study_type=StudyType.RCT,
                final_score=70.0,
                model_version="v1",
            )
        )
        db_session.add(
            CitationVelocityCache(
                paper_id=paper.id,
                status="ready",
                velocity_per_30d=Decimal("4.00"),
                window_end_observed_at=window_end,
            )
        )
    db_session.flush()
    sync_search_index(db_session)

    user = create_user(db_session, f"agg-coerce-{topic.mesh_id}@example.com")
    saved = SavedSearch(
        user_id=user.id,
        name="Coercion search",
        query_params={
            "topic_id": str(topic.id),
            "date_from": "2020-01-01",
            "date_to": "2026-12-31",
        },
    )
    db_session.add(saved)
    db_session.flush()

    result = saved_search_velocity(db_session, saved, weeks=12)

    assert result["status"] == "ready"
    assert result["papers_total"] == 12
    assert result["papers_with_history"] == 12
