from dataclasses import dataclass

MAX_ABSTRACT_CHARS = 1200


@dataclass(frozen=True)
class MemberInput:
    title: str
    tier: str | None
    study_type: str | None
    abstract: str | None
    is_retracted: bool


SYNTHESIS_TOOL = {
    "name": "record_synthesis",
    "description": "Record a grounded synthesis of the supplied studies.",
    "input_schema": {
        "type": "object",
        "properties": {
            "narrative": {
                "type": "string",
                "description": "2-4 sentences comparing the studies. No claim without a citation.",
            },
            "claims": {
                "type": "array",
                "description": "Each factual claim, with the indices of the studies supporting it.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "citations": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["text", "citations"],
                },
            },
            "disagreements": {
                "type": "array",
                "description": "Pairs of studies that conflict, and how.",
                "items": {
                    "type": "object",
                    "properties": {
                        "indices": {"type": "array", "items": {"type": "integer"}},
                        "description": {"type": "string"},
                    },
                    "required": ["indices", "description"],
                },
            },
            "strength_ranking": {
                "type": "array",
                "description": "Study indices ordered strongest evidence first.",
                "items": {"type": "integer"},
            },
        },
        "required": ["narrative", "claims", "disagreements", "strength_ranking"],
    },
}


def build_prompt(members: list[MemberInput]) -> str:
    blocks = []
    for index, member in enumerate(members):
        abstract = (member.abstract or "").strip()[:MAX_ABSTRACT_CHARS] or "(no abstract available)"
        retracted = " [RETRACTED]" if member.is_retracted else ""
        blocks.append(
            f"[{index}] {member.title}{retracted}\n"
            f"    evidence tier: {member.tier or 'not yet scored'}\n"
            f"    study type: {member.study_type or 'unknown'}\n"
            f"    abstract: {abstract}"
        )
    body = "\n\n".join(blocks)

    # The instructions below are the hallucination guardrails. The validator enforces
    # them independently -- this text only improves the odds of a compliant response.
    return (
        "You are comparing research studies for a researcher who will act on your summary.\n\n"
        "Rules you must follow:\n"
        "- Use ONLY the studies listed below. Never introduce a study, statistic, or "
        "finding that does not appear in them.\n"
        "- Every claim must cite the indices of the studies supporting it. A claim you "
        "cannot cite must be omitted entirely.\n"
        "- Do not state or imply causation unless a study listed below does.\n"
        "- Treat a study marked [RETRACTED] as unreliable and say so if you reference it.\n"
        "- Rank by evidence strength using study design and tier, not by how interesting "
        "the finding is.\n"
        "- If the studies do not support a meaningful comparison, say so plainly rather "
        "than manufacturing agreement.\n\n"
        f"Studies:\n\n{body}\n\n"
        "Record your synthesis with the record_synthesis tool."
    )
