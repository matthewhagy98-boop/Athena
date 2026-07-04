import json
from dataclasses import dataclass

from evidence_engine.config import get_settings
from evidence_engine.llm.client import get_anthropic_client

JUDGE_TOOL = {
    "name": "judge_consensus",
    "description": "Judge whether a consensus paragraph reflects the expected themes and avoids forbidden claims.",
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["passed", "reasoning"],
    },
}


@dataclass
class JudgeResult:
    passed: bool
    reasoning: str


@dataclass
class ConsensusEvalResult:
    pass_rate: float
    failures: list[dict]


def judge_consensus_text(consensus_text: str, expected_themes: list[str], forbidden_claims: list[str]) -> JudgeResult:
    themes_block = "\n".join(f"- {t}" for t in expected_themes)
    forbidden_block = "\n".join(f"- {c}" for c in forbidden_claims)
    prompt = (
        f"Consensus paragraph:\n{consensus_text}\n\n"
        f"Expected themes it should include:\n{themes_block}\n\n"
        f"Claims it must NOT make:\n{forbidden_block}\n\n"
        "Judge whether the paragraph includes all expected themes and none of the forbidden claims."
    )

    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=300,
        tools=[JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "judge_consensus"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return JudgeResult(passed=block.input.get("passed", False), reasoning=block.input.get("reasoning", ""))
    return JudgeResult(passed=False, reasoning="No judgment returned")


def run_consensus_eval(golden_set_path: str) -> ConsensusEvalResult:
    with open(golden_set_path, encoding="utf-8") as f:
        cases = json.load(f)

    failures = []
    passed_count = 0
    for case in cases:
        result = judge_consensus_text(case["consensus_text"], case["expected_themes"], case["forbidden_claims"])
        if result.passed:
            passed_count += 1
        else:
            failures.append({"topic_label": case["topic_label"], "reasoning": result.reasoning})

    pass_rate = passed_count / len(cases) if cases else 0.0
    return ConsensusEvalResult(pass_rate=pass_rate, failures=failures)
