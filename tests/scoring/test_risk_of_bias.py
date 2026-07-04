import httpx
import respx

from evidence_engine.db.models import Paper
from evidence_engine.scoring.risk_of_bias import detect_risk_of_bias

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


@respx.mock
def test_detect_risk_of_bias_applies_penalty_for_flags():
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
                        "name": "assess_risk_of_bias",
                        "input": {
                            "flags": ["no_blinding", "underpowered_sample"],
                            "quality_breakdown": "Small, unblinded trial; results directionally consistent with prior work.",
                        },
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )
    )

    paper = Paper(title="A trial", abstract="We conducted an open-label trial of 20 patients...")
    result = detect_risk_of_bias(paper)

    assert result.flags == ["no_blinding", "underpowered_sample"]
    assert "unblinded" in result.quality_breakdown
    assert result.penalty == 25.0


def test_detect_risk_of_bias_returns_no_flags_without_abstract():
    paper = Paper(title="A trial", abstract=None)
    result = detect_risk_of_bias(paper)
    assert result.flags == []
    assert result.penalty == 0.0
