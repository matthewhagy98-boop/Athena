from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import EvidenceTier, JournalSJR, Paper, Score, StudyType
from evidence_engine.scoring.classifier import classify_study_type
from evidence_engine.scoring.formula import compute_base_score
from evidence_engine.scoring.risk_of_bias import detect_risk_of_bias
from evidence_engine.scoring.sample_size import extract_sample_size

TOP_TIER_TYPES = {StudyType.META_ANALYSIS, StudyType.SYSTEMATIC_REVIEW}


def assign_evidence_tier(final_score: float, study_type: StudyType) -> EvidenceTier:
    if study_type in TOP_TIER_TYPES and final_score >= 70.0:
        return EvidenceTier.ESTABLISHED
    if final_score >= 50.0:
        return EvidenceTier.EMERGING
    return EvidenceTier.SPECULATIVE


def _latest_sjr(session: Session, journal_issn: str | None) -> float | None:
    if not journal_issn:
        return None
    row = (
        session.execute(
            select(JournalSJR).where(JournalSJR.issn == journal_issn).order_by(JournalSJR.year.desc())
        )
        .scalars()
        .first()
    )
    return row.sjr_score if row else None


def score_paper(session: Session, paper: Paper, citation_count: int, model_version: str) -> Score:
    study_type = classify_study_type(paper)
    sample_size = extract_sample_size(paper)
    journal_sjr = _latest_sjr(session, paper.journal_issn)
    base_score = compute_base_score(study_type, sample_size, citation_count, journal_sjr)
    risk_result = detect_risk_of_bias(paper)
    final_score = max(0.0, base_score - risk_result.penalty)
    tier = assign_evidence_tier(final_score, study_type)

    existing = session.execute(select(Score).where(Score.paper_id == paper.id)).scalar_one_or_none()
    score = existing or Score(paper_id=paper.id)
    score.study_type = study_type
    score.sample_size = sample_size
    score.citation_count = citation_count
    score.journal_sjr = journal_sjr
    score.base_score = base_score
    score.risk_of_bias_flags = risk_result.flags
    score.final_score = final_score
    score.evidence_tier = tier
    score.quality_breakdown = risk_result.quality_breakdown
    score.model_version = model_version
    score.is_pending = False

    if not existing:
        session.add(score)
    session.flush()
    return score
