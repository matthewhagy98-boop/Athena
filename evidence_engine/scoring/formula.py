import math

from evidence_engine.db.models import StudyType

STUDY_TYPE_TIER_SCORES: dict[StudyType, float] = {
    StudyType.META_ANALYSIS: 100.0,
    StudyType.SYSTEMATIC_REVIEW: 95.0,
    StudyType.RCT: 80.0,
    StudyType.COHORT: 60.0,
    StudyType.CASE_CONTROL: 50.0,
    StudyType.CASE_SERIES: 30.0,
    StudyType.OPINION_EDITORIAL: 10.0,
    StudyType.UNKNOWN: 20.0,
}

WEIGHTS = {"study_type": 0.55, "sample_size": 0.15, "citations": 0.15, "journal": 0.15}


def _sample_size_score(sample_size: int | None) -> float:
    if not sample_size or sample_size <= 0:
        return 0.0
    return min(100.0, math.log10(sample_size + 1) * 40)


def _citation_score(citation_count: int) -> float:
    if citation_count <= 0:
        return 0.0
    return min(100.0, math.log10(citation_count + 1) * 33)


def _journal_score(journal_sjr: float | None) -> float:
    if not journal_sjr or journal_sjr <= 0:
        return 0.0
    return min(100.0, journal_sjr * 8)


def compute_base_score(
    study_type: StudyType,
    sample_size: int | None,
    citation_count: int,
    journal_sjr: float | None,
) -> float:
    total = (
        WEIGHTS["study_type"] * STUDY_TYPE_TIER_SCORES.get(study_type, 20.0)
        + WEIGHTS["sample_size"] * _sample_size_score(sample_size)
        + WEIGHTS["citations"] * _citation_score(citation_count)
        + WEIGHTS["journal"] * _journal_score(journal_sjr)
    )
    return round(total, 1)
