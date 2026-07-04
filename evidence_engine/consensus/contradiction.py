from dataclasses import dataclass

from evidence_engine.config import get_settings
from evidence_engine.db.models import ConsensusSnapshot, Paper
from evidence_engine.llm.client import get_anthropic_client

CONTRADICTION_TOOL = {
    "name": "assess_contradiction",
    "description": "Determine whether a paper's claims contradict the current scientific consensus for a topic.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contradicts": {"type": "boolean"},
            "note": {"type": ["string", "null"]},
        },
        "required": ["contradicts", "note"],
    },
}


@dataclass
class ContradictionResult:
    contradicts: bool
    note: str | None


def detect_contradiction(paper: Paper, consensus: ConsensusSnapshot) -> ContradictionResult:
    if consensus.is_insufficient_evidence or not consensus.consensus_text or not paper.abstract:
        return ContradictionResult(contradicts=False, note=None)

    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=300,
        tools=[CONTRADICTION_TOOL],
        tool_choice={"type": "tool", "name": "assess_contradiction"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Current consensus: {consensus.consensus_text}\n\n"
                    f"New paper title: {paper.title}\nNew paper abstract: {paper.abstract}"
                ),
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use":
            return ContradictionResult(
                contradicts=block.input.get("contradicts", False),
                note=block.input.get("note"),
            )
    return ContradictionResult(contradicts=False, note=None)
