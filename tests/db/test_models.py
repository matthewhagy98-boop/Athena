import uuid

from evidence_engine.db.models import EvidenceTier, Paper, StudyType, Topic


def test_topic_and_paper_round_trip(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="D009203")
    db_session.add(topic)
    db_session.flush()

    paper = Paper(
        pmid="12345678",
        title="A study of something",
        abstract="Background... Methods... Results...",
        authors=["Smith J", "Doe A"],
        journal="The Lancet",
        publication_types=["Randomized Controlled Trial"],
    )
    db_session.add(paper)
    db_session.flush()

    fetched_topic = db_session.get(Topic, topic.id)
    fetched_paper = db_session.get(Paper, paper.id)

    assert fetched_topic.canonical_label == "Myocardial Infarction"
    assert fetched_paper.pmid == "12345678"
    assert fetched_paper.publication_types == ["Randomized Controlled Trial"]
