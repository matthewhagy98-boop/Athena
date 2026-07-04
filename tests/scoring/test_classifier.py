import httpx
import respx

from evidence_engine.db.models import Paper, StudyType
from evidence_engine.scoring.classifier import classify_study_type

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def test_classify_study_type_trusts_pubmed_tag():
    paper = Paper(title="A trial", abstract="...", publication_types=["Randomized Controlled Trial"])
    assert classify_study_type(paper) == StudyType.RCT


@respx.mock
def test_classify_study_type_falls_back_to_llm_when_tag_missing():
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
                        "name": "classify_study",
                        "input": {"study_type": "cohort"},
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )
    )

    paper = Paper(title="A study", abstract="We followed 500 patients over five years...", publication_types=[])
    assert classify_study_type(paper) == StudyType.COHORT


def test_classify_study_type_returns_unknown_without_abstract():
    paper = Paper(title="A study", abstract=None, publication_types=[])
    assert classify_study_type(paper) == StudyType.UNKNOWN
