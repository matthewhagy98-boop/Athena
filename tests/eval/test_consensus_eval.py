import httpx
import respx

from evidence_engine.eval.consensus_eval import judge_consensus_text, run_consensus_eval

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _mock_judge_response(passed: bool, reasoning: str):
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
                    "name": "judge_consensus",
                    "input": {"passed": passed, "reasoning": reasoning},
                }
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 50, "output_tokens": 10},
        },
    )


@respx.mock
def test_judge_consensus_text_returns_structured_result():
    respx.post(MESSAGES_URL).mock(return_value=_mock_judge_response(True, "Covers both expected themes."))

    result = judge_consensus_text(
        consensus_text="Aspirin reduces recurrent events after MI, per multiple meta-analyses.",
        expected_themes=["aspirin reduces recurrent events"],
        forbidden_claims=["aspirin is harmful in all patients"],
    )

    assert result.passed is True
    assert "expected themes" in result.reasoning


@respx.mock
def test_run_consensus_eval_aggregates_pass_rate():
    respx.post(MESSAGES_URL).mock(
        side_effect=[
            _mock_judge_response(True, "Matches expectations."),
            _mock_judge_response(False, "Missing the 'limited evidence' theme."),
        ]
    )

    result = run_consensus_eval("tests/fixtures/golden_set/consensus_golden_set.json")

    assert result.pass_rate == 0.5
    assert len(result.failures) == 1
    assert result.failures[0]["topic_label"] == "Long COVID"
