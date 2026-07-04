import httpx
import respx

from evidence_engine.consensus.contradiction import detect_contradiction
from evidence_engine.db.models import ConsensusSnapshot, Paper

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


@respx.mock
def test_detect_contradiction_flags_conflicting_paper():
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
                        "name": "assess_contradiction",
                        "input": {"contradicts": True, "note": "Reports increased risk, contrary to consensus."},
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )
    )

    consensus = ConsensusSnapshot(
        consensus_text="Treatment X reduces risk of outcome Y.",
        is_insufficient_evidence=False,
        model_version="v1",
    )
    paper = Paper(title="A study", abstract="We found treatment X increases risk of outcome Y...")

    result = detect_contradiction(paper, consensus)

    assert result.contradicts is True
    assert "increased risk" in result.note


def test_detect_contradiction_skips_when_consensus_is_insufficient_evidence():
    consensus = ConsensusSnapshot(consensus_text=None, is_insufficient_evidence=True, model_version="v1")
    paper = Paper(title="A study", abstract="Some findings...")

    result = detect_contradiction(paper, consensus)

    assert result.contradicts is False
    assert result.note is None


def test_detect_contradiction_skips_when_no_consensus_text():
    consensus = ConsensusSnapshot(consensus_text=None, is_insufficient_evidence=False, model_version="v1")
    paper = Paper(title="A study", abstract="Some findings...")

    result = detect_contradiction(paper, consensus)

    assert result.contradicts is False
    assert result.note is None


def test_detect_contradiction_skips_when_paper_has_no_abstract():
    consensus = ConsensusSnapshot(
        consensus_text="Treatment X reduces risk of outcome Y.",
        is_insufficient_evidence=False,
        model_version="v1",
    )
    paper = Paper(title="A study", abstract=None)

    result = detect_contradiction(paper, consensus)

    assert result.contradicts is False
    assert result.note is None
