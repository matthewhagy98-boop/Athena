import httpx
import respx

from evidence_engine.consensus.synthesizer import get_top_tier_scores, synthesize_consensus
from evidence_engine.db.models import ConsensusSnapshot, Paper, PaperTopic, Score, StudyType, Topic

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _link(session, topic, title, abstract, study_type, final_score=90.0):
    paper = Paper(title=title, abstract=abstract)
    session.add(paper)
    session.flush()
    session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    score = Score(paper_id=paper.id, study_type=study_type, final_score=final_score, model_version="v1")
    session.add(score)
    session.flush()
    return paper, score


def test_get_top_tier_scores_filters_to_meta_analyses_and_systematic_reviews(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    _link(db_session, topic, "Meta-analysis A", "abstract", StudyType.META_ANALYSIS)
    _link(db_session, topic, "Case series B", "abstract", StudyType.CASE_SERIES)

    top_tier = get_top_tier_scores(db_session, topic)

    assert len(top_tier) == 1
    assert top_tier[0].study_type == StudyType.META_ANALYSIS


@respx.mock
def test_synthesize_consensus_grounds_text_in_top_tier_papers(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    _link(db_session, topic, "Meta-analysis A", "Pooled 10 trials, n=5000...", StudyType.META_ANALYSIS)
    paper_b, _ = _link(db_session, topic, "Systematic review B", "Reviewed 8 RCTs...", StudyType.SYSTEMATIC_REVIEW)

    respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "synthesize_consensus",
                        "input": {
                            "consensus_text": "Across pooled trials, treatment reduces risk.",
                            "supporting_indices": [1],
                        },
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )
    )

    snapshot = synthesize_consensus(db_session, topic, model_version="v1")

    assert snapshot.is_insufficient_evidence is False
    assert "reduces risk" in snapshot.consensus_text
    assert snapshot.supporting_paper_ids == [paper_b.id]


def test_synthesize_consensus_flags_insufficient_evidence_below_threshold(db_session):
    topic = Topic(canonical_label="Rare Condition", mesh_id="D000000")
    db_session.add(topic)
    db_session.flush()

    _link(db_session, topic, "Meta-analysis A", "abstract", StudyType.META_ANALYSIS)

    snapshot = synthesize_consensus(db_session, topic, model_version="v1")

    assert snapshot.is_insufficient_evidence is True
    assert snapshot.consensus_text is None
