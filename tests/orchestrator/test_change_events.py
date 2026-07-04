from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Topic
from evidence_engine.orchestrator.change_events import record_change_event


def test_record_change_event_with_paper(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    paper = Paper(title="A study")
    db_session.add_all([topic, paper])
    db_session.flush()

    event = record_change_event(db_session, topic, ChangeEventType.NEW_PAPER, paper=paper)
    db_session.flush()

    fetched = db_session.query(ChangeEvent).filter_by(id=event.id).one()
    assert fetched.topic_id == topic.id
    assert fetched.paper_id == paper.id
    assert fetched.event_type == ChangeEventType.NEW_PAPER


def test_record_change_event_without_paper(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    event = record_change_event(db_session, topic, ChangeEventType.CONSENSUS_UPDATED)
    db_session.flush()

    assert event.paper_id is None
    assert event.event_type == ChangeEventType.CONSENSUS_UPDATED
