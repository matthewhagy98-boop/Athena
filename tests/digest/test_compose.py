from datetime import datetime

import httpx
import respx

from digest.aggregate import TopicChange, TopicDigestData
from digest.compose import ComposeError, compose_digest
from evidence_engine.db.models import ChangeEventType, Paper, Score, StudyType, Topic

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _tool_use_response(narrative: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "compose_topic_narrative", "input": {"narrative": narrative}}
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 50, "output_tokens": 20},
        },
    )


@respx.mock
def test_compose_digest_produces_one_section_per_topic():
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    paper = Paper(title="Pooled analysis of outcome X")
    score = Score(paper_id=None, study_type=StudyType.META_ANALYSIS, final_score=90.0, model_version="v1")
    change = TopicChange(event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 7, 3), paper=paper, score=score)
    topic_digest = TopicDigestData(topic=topic, changes=[change])

    respx.post(MESSAGES_URL).mock(return_value=_tool_use_response("A new meta-analysis strengthens the evidence."))

    composed = compose_digest([topic_digest])

    assert len(composed.sections) == 1
    assert composed.sections[0].topic_label == "Myocardial Infarction"
    assert "meta-analysis" in composed.sections[0].narrative
    assert composed.sections[0].change_count == 1


@respx.mock
def test_compose_digest_handles_contradiction_and_retraction_change_types():
    topic = Topic(canonical_label="Some Topic", mesh_id="D000009")
    paper_a = Paper(title="Contradicting Paper")
    paper_b = Paper(title="Retracted Paper")
    changes = [
        TopicChange(event_type=ChangeEventType.CONTRADICTION_FLAGGED, detected_at=datetime(2026, 7, 3), paper=paper_a),
        TopicChange(event_type=ChangeEventType.PAPER_RETRACTED, detected_at=datetime(2026, 7, 3), paper=paper_b),
    ]
    topic_digest = TopicDigestData(topic=topic, changes=changes)

    route = respx.post(MESSAGES_URL).mock(return_value=_tool_use_response("Mixed developments this week."))

    composed = compose_digest([topic_digest])

    assert composed.sections[0].change_count == 2
    sent_prompt = route.calls.last.request.content.decode()
    assert "Contradicting Paper" in sent_prompt
    assert "contradicts current consensus" in sent_prompt
    assert "Retracted Paper" in sent_prompt
    assert "retracted" in sent_prompt.lower()


@respx.mock
def test_compose_digest_raises_after_persistent_llm_failure():
    topic = Topic(canonical_label="Rare Condition", mesh_id="D000000")
    change = TopicChange(event_type=ChangeEventType.CONSENSUS_UPDATED, detected_at=datetime(2026, 7, 3))
    topic_digest = TopicDigestData(topic=topic, changes=[change])

    respx.post(MESSAGES_URL).mock(return_value=httpx.Response(500, json={"error": "server error"}))

    try:
        compose_digest([topic_digest])
        assert False, "expected ComposeError"
    except ComposeError:
        pass
