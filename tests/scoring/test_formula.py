import pytest

from evidence_engine.db.models import StudyType
from evidence_engine.scoring.formula import compute_base_score


def test_meta_analysis_with_strong_signals_scores_high():
    score = compute_base_score(
        study_type=StudyType.META_ANALYSIS,
        sample_size=1000,
        citation_count=50,
        journal_sjr=5.0,
    )
    assert score == pytest.approx(84.5, abs=0.1)


def test_opinion_editorial_with_no_signals_scores_low():
    score = compute_base_score(
        study_type=StudyType.OPINION_EDITORIAL,
        sample_size=None,
        citation_count=0,
        journal_sjr=None,
    )
    assert score == pytest.approx(5.5, abs=0.1)


def test_higher_study_tier_always_scores_higher_given_equal_signals():
    rct_score = compute_base_score(StudyType.RCT, 200, 10, 2.0)
    case_series_score = compute_base_score(StudyType.CASE_SERIES, 200, 10, 2.0)
    assert rct_score > case_series_score
