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


def test_score_paper_reuses_existing_score_on_second_call(db_session):
    paper = Paper(
        title="A cohort study",
        abstract="We followed 500 patients...",
        journal_issn=None,
        publication_types=["Randomized Controlled Trial"],
    )
    db_session.add(paper)
    db_session.flush()

    with (
        patch("evidence_engine.scoring.assemble.extract_sample_size", return_value=500),
        patch(
            "evidence_engine.scoring.assemble.detect_risk_of_bias",
            return_value=RiskOfBiasResult(flags=[], quality_breakdown="First pass.", penalty=5.0),
        ),
    ):
        first_score = score_paper(db_session, paper, citation_count=10, model_version="v1")
    db_session.flush()
    first_id = first_score.id

    with (
        patch("evidence_engine.scoring.assemble.extract_sample_size", return_value=2000),
        patch(
            "evidence_engine.scoring.assemble.detect_risk_of_bias",
            return_value=RiskOfBiasResult(flags=["no_blinding"], quality_breakdown="Second pass.", penalty=10.0),
        ),
    ):
        second_score = score_paper(db_session, paper, citation_count=100, model_version="v2")
    db_session.flush()

    assert second_score.id == first_id
    assert second_score.sample_size == 2000
    assert second_score.citation_count == 100
    assert second_score.risk_of_bias_flags == ["no_blinding"]
    assert second_score.quality_breakdown == "Second pass."
    assert second_score.model_version == "v2"

    all_scores = db_session.query(Score).filter_by(paper_id=paper.id).all()
    assert len(all_scores) == 1


def test_score_paper_clears_is_pending_flag_on_success(db_session):
    paper = Paper(
        title="A cohort study",
        abstract="We followed 500 patients...",
        journal_issn=None,
        publication_types=["Randomized Controlled Trial"],
    )
    db_session.add(paper)
    db_session.flush()

    pending_score = Score(paper_id=paper.id, is_pending=True, model_version="v0")
    db_session.add(pending_score)
    db_session.flush()

    with (
        patch("evidence_engine.scoring.assemble.extract_sample_size", return_value=500),
        patch(
            "evidence_engine.scoring.assemble.detect_risk_of_bias",
            return_value=RiskOfBiasResult(flags=[], quality_breakdown="Fine.", penalty=0.0),
        ),
    ):
        score = score_paper(db_session, paper, citation_count=10, model_version="v1")

    assert score.is_pending is False


def test_latest_sjr_picks_highest_year(db_session):
    older = JournalSJR(issn="1234-5678", journal_name="Old Journal Snapshot", sjr_score=2.0, year=2020)
    newer = JournalSJR(issn="1234-5678", journal_name="Old Journal Snapshot", sjr_score=8.0, year=2024)
    db_session.add_all([older, newer])
    paper = Paper(
        title="An RCT",
        abstract="We randomized 300 patients...",
        journal_issn="1234-5678",
        publication_types=["Randomized Controlled Trial"],
    )
    db_session.add(paper)
    db_session.flush()

    with (
        patch("evidence_engine.scoring.assemble.extract_sample_size", return_value=300),
        patch(
            "evidence_engine.scoring.assemble.detect_risk_of_bias",
            return_value=RiskOfBiasResult(flags=[], quality_breakdown="No issues.", penalty=0.0),
        ),
    ):
        score = score_paper(db_session, paper, citation_count=5, model_version="v1")

    assert score.journal_sjr == 8.0


def test_score_paper_floors_final_score_at_zero(db_session):
    paper = Paper(
        title="A case series",
        abstract="We describe 3 cases...",
        journal_issn=None,
        publication_types=["Case Reports"],
    )
    db_session.add(paper)
    db_session.flush()

    with (
        patch("evidence_engine.scoring.assemble.extract_sample_size", return_value=3),
        patch(
            "evidence_engine.scoring.assemble.detect_risk_of_bias",
            return_value=RiskOfBiasResult(
                flags=["outcome_switching"], quality_breakdown="Severe issues.", penalty=150.0
            ),
        ),
    ):
        score = score_paper(db_session, paper, citation_count=0, model_version="v1")

    assert score.final_score == 0.0
