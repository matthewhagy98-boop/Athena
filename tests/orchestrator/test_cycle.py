from unittest.mock import patch

from evidence_engine.adapters.base import RawPaper
from evidence_engine.consensus.contradiction import ContradictionResult
from evidence_engine.db.models import ChangeEvent, ChangeEventType, ConsensusSnapshot, Paper, Score, Topic
from evidence_engine.orchestrator.cycle import run_topic_cycle


class _FailingAdapter:
    def fetch_new(self, topic, since):
        raise RuntimeError("source is down")


class _WorkingAdapter:
    def __init__(self, raw_papers):
        self._raw_papers = raw_papers

    def fetch_new(self, topic, since):
        return self._raw_papers


def test_run_topic_cycle_isolates_adapter_failure_and_scores_new_paper(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    prior_consensus = ConsensusSnapshot(
        topic_id=topic.id,
        consensus_text="Old consensus text",
        is_insufficient_evidence=False,
        model_version="v1",
    )
    db_session.add(prior_consensus)
    db_session.flush()

    raw_paper = RawPaper(source="pubmed", pmid="12345678", doi="10.1/xyz", title="A new trial", abstract="...")
    adapters = [_FailingAdapter(), _WorkingAdapter([raw_paper])]

    fake_consensus = ConsensusSnapshot(
        topic_id=topic.id, consensus_text="Consensus text", is_insufficient_evidence=False, model_version="v1"
    )

    with (
        patch("evidence_engine.orchestrator.cycle.score_paper") as mock_score_paper,
        patch("evidence_engine.orchestrator.cycle.synthesize_consensus", return_value=fake_consensus) as mock_synth,
        patch(
            "evidence_engine.orchestrator.cycle.detect_contradiction",
            return_value=ContradictionResult(True, "Reports opposite direction of effect."),
        ),
        patch("evidence_engine.orchestrator.cycle.recheck_retractions", return_value=[]),
    ):
        run_topic_cycle(db_session, topic, model_version="v1", adapters=adapters)

    mock_score_paper.assert_called_once()
    mock_synth.assert_called_once()

    events = db_session.query(ChangeEvent).filter_by(topic_id=topic.id).all()
    event_types = {e.event_type for e in events}
    assert ChangeEventType.NEW_PAPER in event_types
    assert ChangeEventType.CONSENSUS_UPDATED in event_types
    assert ChangeEventType.CONTRADICTION_FLAGGED in event_types
    assert "opposite direction" in fake_consensus.contradiction_notes
    assert topic.last_checked_at is not None


def test_run_topic_cycle_marks_score_pending_on_scoring_failure(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    raw_paper = RawPaper(source="pubmed", pmid="12345678", title="A new trial", abstract="...")

    fake_consensus = ConsensusSnapshot(
        topic_id=topic.id, consensus_text=None, is_insufficient_evidence=True, model_version="v1"
    )

    with (
        patch("evidence_engine.orchestrator.cycle.score_paper", side_effect=RuntimeError("LLM down")),
        patch("evidence_engine.orchestrator.cycle.synthesize_consensus", return_value=fake_consensus),
        patch("evidence_engine.orchestrator.cycle.recheck_retractions", return_value=[]),
    ):
        run_topic_cycle(db_session, topic, model_version="v1", adapters=[_WorkingAdapter([raw_paper])])

    paper = db_session.query(Paper).filter_by(pmid="12345678").one()
    score = db_session.query(Score).filter_by(paper_id=paper.id).one()
    assert score.is_pending is True

    events = db_session.query(ChangeEvent).filter_by(topic_id=topic.id).all()
    assert all(e.event_type != ChangeEventType.NEW_PAPER for e in events)


def test_run_topic_cycle_checks_contradiction_against_previous_consensus_not_new_one(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    previous_consensus = ConsensusSnapshot(
        topic_id=topic.id,
        consensus_text="OLD CONSENSUS",
        is_insufficient_evidence=False,
        model_version="v1",
    )
    db_session.add(previous_consensus)
    db_session.flush()

    new_consensus = ConsensusSnapshot(
        topic_id=topic.id,
        consensus_text="NEW CONSENSUS",
        is_insufficient_evidence=False,
        model_version="v1",
    )

    raw_paper = RawPaper(source="pubmed", pmid="12345678", title="A new trial", abstract="...")

    with (
        patch("evidence_engine.orchestrator.cycle.score_paper"),
        patch("evidence_engine.orchestrator.cycle.synthesize_consensus", return_value=new_consensus),
        patch(
            "evidence_engine.orchestrator.cycle.detect_contradiction",
            return_value=ContradictionResult(False, None),
        ) as mock_detect_contradiction,
        patch("evidence_engine.orchestrator.cycle.recheck_retractions", return_value=[]),
    ):
        run_topic_cycle(db_session, topic, model_version="v1", adapters=[_WorkingAdapter([raw_paper])])

    mock_detect_contradiction.assert_called_once()
    called_consensus = mock_detect_contradiction.call_args[0][1]
    assert called_consensus is previous_consensus
    assert called_consensus.consensus_text == "OLD CONSENSUS"
    assert called_consensus is not new_consensus
