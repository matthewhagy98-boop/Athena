from unittest.mock import patch

from evidence_engine.db.models import EvidenceTier, JournalSJR, Paper, Score, StudyType
from evidence_engine.scoring.assemble import assign_evidence_tier, score_paper
from evidence_engine.scoring.risk_of_bias import RiskOfBiasResult


def test_assign_evidence_tier_established_requires_top_tier_study_and_high_score():
    assert assign_evidence_tier(85.0, StudyType.META_ANALYSIS) == EvidenceTier.ESTABLISHED
    assert assign_evidence_tier(85.0, StudyType.RCT) == EvidenceTier.EMERGING
    assert assign_evidence_tier(40.0, StudyType.META_ANALYSIS) == EvidenceTier.SPECULATIVE


def test_score_paper_persists_score_with_all_components(db_session):
    journal_sjr = JournalSJR(issn="0140-6736", journal_name="The Lancet", sjr_score=5.0, year=2024)
    db_session.add(journal_sjr)
    paper = Paper(
        title="A meta-analysis",
        abstract="We pooled 20 trials...",
        journal_issn="0140-6736",
        publication_types=["Meta-Analysis"],
    )
    db_session.add(paper)
    db_session.flush()

    with (
        patch("evidence_engine.scoring.assemble.extract_sample_size", return_value=1000),
        patch(
            "evidence_engine.scoring.assemble.detect_risk_of_bias",
            return_value=RiskOfBiasResult(flags=["no_blinding"], quality_breakdown="Some limitations.", penalty=10.0),
        ),
    ):
        score = score_paper(db_session, paper, citation_count=50, model_version="v1")
    db_session.flush()

    assert score.paper_id == paper.id
    assert score.study_type == StudyType.META_ANALYSIS
    assert score.sample_size == 1000
    assert score.citation_count == 50
    assert score.journal_sjr == 5.0
    assert score.risk_of_bias_flags == ["no_blinding"]
    assert score.final_score == score.base_score - 10.0
    assert score.model_version == "v1"

    fetched = db_session.query(Score).filter_by(paper_id=paper.id).one()
    assert fetched.id == score.id
