import httpx
import respx

from evidence_engine.db.models import Paper
from evidence_engine.scoring.sample_size import extract_sample_size

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _mock_response(reported: bool, size: int | None):
    return httpx.Response(
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
                    "name": "extract_sample_size",
                    "input": {"sample_size_reported": reported, "sample_size": size},
                }
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 50, "output_tokens": 10},
        },
    )


@respx.mock
def test_extract_sample_size_returns_reported_value():
    respx.post(MESSAGES_URL).mock(return_value=_mock_response(True, 245))
    paper = Paper(title="A trial", abstract="We enrolled 245 patients...")
    assert extract_sample_size(paper) == 245


@respx.mock
def test_extract_sample_size_returns_none_when_not_reported():
    respx.post(MESSAGES_URL).mock(return_value=_mock_response(False, None))
    paper = Paper(title="An opinion piece", abstract="In this commentary we argue...")
    assert extract_sample_size(paper) is None


def test_extract_sample_size_returns_none_without_abstract():
    paper = Paper(title="A trial", abstract=None)
    assert extract_sample_size(paper) is None
