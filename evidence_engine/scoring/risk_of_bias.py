from dataclasses import dataclass

from evidence_engine.db.models import Paper
from evidence_engine.llm.client import call_forced_tool

FLAG_PENALTIES = {
    "no_control_group": 15.0,
    "no_blinding": 10.0,
    "funding_conflict_of_interest": 10.0,
    "underpowered_sample": 15.0,
    "outcome_switching": 20.0,
    "other": 5.0,
}
MAX_PENALTY = 50.0

ASSESS_TOOL = {
    "name": "assess_risk_of_bias",
    "description": "Identify concrete risk-of-bias issues in a biomedical paper from its abstract, and write a short quality critique.",
    "input_schema": {
        "type": "object",
        "properties": {
            "flags": {
                "type": "array",
                "items": {"type": "string", "enum": list(FLAG_PENALTIES.keys())},
            },
            "quality_breakdown": {"type": "string"},
        },
        "required": ["flags", "quality_breakdown"],
    },
}


@dataclass
class RiskOfBiasResult:
    flags: list[str]
    quality_breakdown: str
    penalty: float


def detect_risk_of_bias(paper: Paper) -> RiskOfBiasResult:
    if not paper.abstract:
        return RiskOfBiasResult(flags=[], quality_breakdown="", penalty=0.0)

    prompt = f"Title: {paper.title}\n\nAbstract: {paper.abstract}"
    result = call_forced_tool(prompt, ASSESS_TOOL, max_tokens=500)

    if result:
        flags = result.get("flags", [])
        penalty = min(MAX_PENALTY, sum(FLAG_PENALTIES.get(f, 0.0) for f in flags))
        return RiskOfBiasResult(
            flags=flags,
            quality_breakdown=result.get("quality_breakdown", ""),
            penalty=penalty,
        )
    return RiskOfBiasResult(flags=[], quality_breakdown="", penalty=0.0)
