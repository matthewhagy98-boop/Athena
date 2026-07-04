from datetime import datetime
from unittest.mock import patch

from digest.aggregate import aggregate_changes_for_user
from digest.profiles import add_interest, create_user
from evidence_engine.db.models import ChangeEvent, ChangeEventType, ConsensusSnapshot, Paper, PaperTopic, Score
from evidence_engine.topics.mesh import MeshResolution


def _add_topic(db_session, user, mesh_id, label, free_text):
    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id=mesh_id, canonical_label=label),
    ):
        return add_interest(db_session, user, free_text)


def test_aggregate_excludes_topics_with_no_changes_in_window(db_session):
    user = create_user(db_session, "researcher@example.com")
    quiet_topic = _add_topic(db_session, user, "D000001", "Quiet Topic", "quiet topic")
    active_topic = _add_topic(db_session, user, "D000002", "Active Topic", "active topic")

    paper = Paper(title="A new finding")
    db_session.add(paper)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper.id, topic_id=active_topic.id))
    db_session.add(
        ChangeEvent(
            topic_id=active_topic.id,
            paper_id=paper.id,
            event_type=ChangeEventType.NEW_PAPER,
            detected_at=datetime(2026, 7, 2),
        )
    )
    db_session.flush()

    results = aggregate_changes_for_user(
        db_session, user, window_start=datetime(2026, 7, 1), window_end=datetime(2026, 7, 8)
    )

    assert len(results) == 1
    assert results[0].topic.id == active_topic.id
    assert quiet_topic.id not in [r.topic.id for r in results]


def test_aggregate_window_start_exclusive_window_end_inclusive(db_session):
    user = create_user(db_session, "researcher2@example.com")
    topic = _add_topic(db_session, user, "D000003", "Boundary Topic", "boundary topic")

    db_session.add_all(
        [
            ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.CONSENSUS_UPDATED, detected_at=datetime(2026, 7, 1, 0, 0, 0)),
            ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.CONSENSUS_UPDATED, detected_at=datetime(2026, 7, 8, 0, 0, 0)),
        ]
    )
    db_session.flush()

    results = aggregate_changes_for_user(
        db_session, user, window_start=datetime(2026, 7, 1, 0, 0, 0), window_end=datetime(2026, 7, 8, 0, 0, 0)
    )

    assert len(results) == 1
    assert len(results[0].changes) == 1
    assert results[0].changes[0].detected_at == datetime(2026, 7, 8, 0, 0, 0)


def test_aggregate_hydrates_paper_score_and_consensus(db_session):
    user = create_user(db_session, "researcher3@example.com")
    topic = _add_topic(db_session, user, "D000004", "Hydrate Topic", "hydrate topic")

    paper = Paper(title="Pooled analysis of outcome X")
    db_session.add(paper)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    db_session.add(Score(paper_id=paper.id, final_score=88.0, model_version="v1"))
    snapshot = ConsensusSnapshot(
        topic_id=topic.id,
        consensus_text="Treatment reduces risk.",
        supporting_paper_ids=[paper.id],
        model_version="v1",
        generated_at=datetime(2026, 7, 3),
    )
    db_session.add(snapshot)
    db_session.add(
        ChangeEvent(
            topic_id=topic.id,
            paper_id=paper.id,
            event_type=ChangeEventType.NEW_PAPER,
            detected_at=datetime(2026, 7, 3),
        )
    )
    db_session.add(
        ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.CONSENSUS_UPDATED, detected_at=datetime(2026, 7, 3))
    )
    db_session.flush()

    results = aggregate_changes_for_user(
        db_session, user, window_start=datetime(2026, 7, 1), window_end=datetime(2026, 7, 8)
    )

    assert len(results) == 1
    changes_by_type = {c.event_type: c for c in results[0].changes}
    new_paper_change = changes_by_type[ChangeEventType.NEW_PAPER]
    assert new_paper_change.paper.title == "Pooled analysis of outcome X"
    assert new_paper_change.score.final_score == 88.0
    consensus_change = changes_by_type[ChangeEventType.CONSENSUS_UPDATED]
    assert consensus_change.consensus.consensus_text == "Treatment reduces risk."
