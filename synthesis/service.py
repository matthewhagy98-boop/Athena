import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.config import get_settings
from evidence_engine.db.models import Paper, Score
from synthesis.generate import generate_synthesis as default_generate
from synthesis.keys import (
    SYNTHESIS_PROMPT_VERSION,
    MemberState,
    compute_cache_key,
    compute_inputs_fingerprint,
)
from synthesis.models import ComparisonSynthesis, SynthesisGeneration
from synthesis.prompt import MemberInput

COOLDOWN_MINUTES = 60


def _synthesis_enabled() -> bool:
    return get_settings().synthesis_enabled


def _load_papers(session: Session, subject_ids: list[uuid.UUID]) -> list[Paper]:
    ordered_ids = sorted(subject_ids, key=str)
    papers = []
    for member_id in ordered_ids:
        paper = session.get(Paper, member_id)
        if paper is None:
            raise ValueError(f"Paper {member_id} not found")
        papers.append(paper)
    return papers


def _score_for(session: Session, paper_id: uuid.UUID) -> Score | None:
    """A pending score is not a score.

    Score rows are created with is_pending=True before scoring completes, carrying
    column defaults (evidence_tier='speculative', final_score=0.0). Treating those
    as real would tell the model a paper is speculative evidence when it is simply
    unscored -- the same misrepresentation webapp/search_index.py guards against.
    """
    score = session.execute(select(Score).where(Score.paper_id == paper_id)).scalar_one_or_none()
    return None if score is not None and score.is_pending else score


def get_or_create_synthesis(
    session: Session,
    subject_type: str,
    subject_ids: list[uuid.UUID],
    user_id: uuid.UUID | None = None,
    generate=None,
    now: datetime | None = None,
) -> ComparisonSynthesis | None:
    """Return a cached synthesis, or generate one. None when the feature is disabled."""
    if not _synthesis_enabled():
        return None

    now = now or datetime.utcnow()
    generate = generate or default_generate

    papers = _load_papers(session, subject_ids)
    ordered_ids = [p.id for p in papers]

    states, inputs, retracted = [], [], []
    for index, paper in enumerate(papers):
        score = _score_for(session, paper.id)
        states.append(
            MemberState(
                member_id=paper.id,
                scored_at=score.scored_at if score else None,
                final_score=score.final_score if score else None,
                evidence_tier=score.evidence_tier.value if score and score.evidence_tier else None,
                is_retracted=bool(paper.is_retracted),
            )
        )
        inputs.append(
            MemberInput(
                title=paper.title,
                tier=score.evidence_tier.value if score and score.evidence_tier else None,
                study_type=score.study_type.value if score and score.study_type else None,
                abstract=paper.abstract,
                is_retracted=bool(paper.is_retracted),
            )
        )
        if paper.is_retracted:
            retracted.append(index)

    model_id = get_settings().anthropic_model
    cache_key = compute_cache_key(subject_type, ordered_ids, SYNTHESIS_PROMPT_VERSION, model_id)
    fingerprint = compute_inputs_fingerprint(states)

    existing = session.execute(
        select(ComparisonSynthesis).where(
            ComparisonSynthesis.cache_key == cache_key,
            ComparisonSynthesis.superseded_at.is_(None),
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.inputs_fingerprint == fingerprint:
            if existing.status == "ready":
                return existing
            # Failed: honour the cooldown so a broken input set cannot be retried in a loop.
            if existing.cooldown_until and existing.cooldown_until > now:
                return existing
        existing.superseded_at = now
        session.flush()

    result, latency_ms = generate(inputs)

    row = ComparisonSynthesis(
        cache_key=cache_key,
        subject_type=subject_type,
        subject_ids=ordered_ids,
        inputs_fingerprint=fingerprint,
        status="ready" if result.ok else "failed",
        narrative=result.narrative if result.ok else None,
        claims=result.claims if result.ok else [],
        disagreements=result.disagreements if result.ok else [],
        strength_ranking=result.strength_ranking if result.ok else [],
        retracted_member_indices=retracted,
        failure_reason=None if result.ok else result.failure_reason,
        cooldown_until=None if result.ok else now + timedelta(minutes=COOLDOWN_MINUTES),
        model_id=model_id,
        prompt_version=SYNTHESIS_PROMPT_VERSION,
        generated_at=now,
    )
    session.add(row)
    session.flush()

    session.add(
        SynthesisGeneration(
            synthesis_id=row.id,
            user_id=user_id,
            member_count=len(inputs),
            outcome=row.status,
            latency_ms=latency_ms,
        )
    )
    session.flush()
    return row
