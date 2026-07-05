import uuid
from datetime import datetime

from evidence_engine.db.models import ConsensusSnapshot, Paper, Score, Topic
from webapp.compare import compare_papers, compare_topics


def test_compare_papers_returns_rows_for_all_resolvable_ids(db_session):
    paper_a = Paper(title="Paper A")
    paper_b = Paper(title="Paper B")
    db_session.add_all([paper_a, paper_b])
    db_session.flush()
    db_session.add(Score(paper_id=paper_a.id, final_score=90.0, model_version="v1"))
    db_session.flush()

    result = compare_papers(db_session, [paper_a.id, paper_b.id])

    assert {row.paper.id for row in result.rows} == {paper_a.id, paper_b.id}
    assert result.unresolved_ids == []
    row_a = next(r for r in result.rows if r.paper.id == paper_a.id)
    assert row_a.score.final_score == 90.0
    row_b = next(r for r in result.rows if r.paper.id == paper_b.id)
    assert row_b.score is None


def test_compare_papers_returns_partial_results_with_unresolved_ids(db_session):
    paper = Paper(title="Real paper")
    db_session.add(paper)
    db_session.flush()
    missing_id = uuid.uuid4()

    result = compare_papers(db_session, [paper.id, missing_id])

    assert len(result.rows) == 1
    assert result.rows[0].paper.id == paper.id
    assert result.unresolved_ids == [missing_id]


def test_compare_papers_handles_empty_input(db_session):
    result = compare_papers(db_session, [])

    assert result.rows == []
    assert result.unresolved_ids == []


def test_compare_topics_returns_latest_consensus_per_topic(db_session):
    topic_a = Topic(canonical_label="Topic A", mesh_id="D000001")
    topic_b = Topic(canonical_label="Topic B", mesh_id="D000002")
    db_session.add_all([topic_a, topic_b])
    db_session.flush()
    db_session.add(
        ConsensusSnapshot(
            topic_id=topic_a.id, consensus_text="Old", model_version="v1", generated_at=datetime(2026, 6, 1)
        )
    )
    db_session.add(
        ConsensusSnapshot(
            topic_id=topic_a.id, consensus_text="New", model_version="v1", generated_at=datetime(2026, 6, 5)
        )
    )
    db_session.flush()

    result = compare_topics(db_session, [topic_a.id, topic_b.id])

    row_a = next(r for r in result.rows if r.topic.id == topic_a.id)
    row_b = next(r for r in result.rows if r.topic.id == topic_b.id)
    assert row_a.consensus.consensus_text == "New"
    assert row_b.consensus is None
    assert result.unresolved_ids == []


def test_compare_topics_returns_partial_results_with_unresolved_ids(db_session):
    topic = Topic(canonical_label="Real Topic", mesh_id="D000003")
    db_session.add(topic)
    db_session.flush()
    missing_id = uuid.uuid4()

    result = compare_topics(db_session, [topic.id, missing_id])

    assert len(result.rows) == 1
    assert result.rows[0].topic.id == topic.id
    assert result.unresolved_ids == [missing_id]
