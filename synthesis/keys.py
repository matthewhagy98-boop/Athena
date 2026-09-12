import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

# Bump whenever the prompt text or the tool schema changes. It is part of the cache
# key, so a bump retires every cached narrative rather than mixing prompt generations.
SYNTHESIS_PROMPT_VERSION = "v1"


@dataclass(frozen=True)
class MemberState:
    member_id: uuid.UUID
    scored_at: datetime | None
    final_score: float | None
    evidence_tier: str | None
    is_retracted: bool


def compute_cache_key(
    subject_type: str, subject_ids: list[uuid.UUID], prompt_version: str, model_id: str
) -> str:
    sorted_ids = ",".join(sorted(str(i) for i in subject_ids))
    payload = f"{subject_type}|{sorted_ids}|{prompt_version}|{model_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_inputs_fingerprint(members: list[MemberState]) -> str:
    lines = []
    for member in sorted(members, key=lambda m: str(m.member_id)):
        scored_at = member.scored_at.isoformat() if member.scored_at else "none"
        # Rounded to 1 decimal, matching the precision compute_base_score returns
        # (evidence_engine/scoring/formula.py:49), so float noise cannot invalidate.
        score = "none" if member.final_score is None else f"{round(member.final_score, 1)}"
        # Explicit None check rather than `or "none"`, matching scored_at and
        # final_score above: a falsy-but-present tier must not hash as "no tier".
        tier = "none" if member.evidence_tier is None else member.evidence_tier
        lines.append(f"{member.member_id}|{scored_at}|{score}|{tier}|{member.is_retracted}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
