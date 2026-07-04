from dataclasses import dataclass

from evidence_engine.db.models import ConsensusSnapshot, Paper
from evidence_engine.llm.client import call_forced_tool

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

    prompt = (
        f"Current consensus: {consensus.consensus_text}\n\n"
        f"New paper title: {paper.title}\nNew paper abstract: {paper.abstract}"
    )
    result = call_forced_tool(prompt, CONTRADICTION_TOOL, max_tokens=300)

    if result:
        return ContradictionResult(
            contradicts=result.get("contradicts", False),
            note=result.get("note"),
        )
    return ContradictionResult(contradicts=False, note=None)
