from datetime import date, datetime

from evidence_engine.db.models import (
    ChangeEvent,
    ChangeEventType,
    EvidenceTier,
    Paper,
    PaperTopic,
    Score,
    StudyType,
    Topic,
)
from webapp.search import SearchFilters, search_papers
from webapp.search_index import sync_search_index


def _seed_paper(db_session, topic, title, abstract, pub_date, tier, study_type, is_retracted=False):
    paper = Paper(title=title, abstract=abstract, pub_date=pub_date, is_retracted=is_retracted)
    db_session.add(paper)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    db_session.add(Score(paper_id=paper.id, study_type=study_type, evidence_tier=tier, final_score=50.0, model_version="v1"))
    event_type = ChangeEventType.PAPER_RETRACTED if is_retracted else ChangeEventType.NEW_PAPER
    db_session.add(ChangeEvent(topic_id=topic.id, paper_id=paper.id, event_type=event_type, detected_at=datetime(2026, 6, 1)))
    db_session.flush()
    return paper


def test_search_papers_matches_free_text_and_ranks_by_relevance(db_session):
    topic = Topic(canonical_label="Hypertension", mesh_id="D006973")
    db_session.add(topic)
    db_session.flush()

    _seed_paper(
        db_session, topic, "A trial of hypertension drug Y", "Blood pressure outcomes in hypertension.",
        date(2026, 5, 1), EvidenceTier.ESTABLISHED, StudyType.RCT,
    )
    _seed_paper(
        db_session, topic, "An unrelated paper about diabetes", "Glucose control in diabetic patients.",
        date(2026, 5, 2), EvidenceTier.EMERGING, StudyType.COHORT,
    )
    sync_search_index(db_session)

    page = search_papers(db_session, query="hypertension", filters=SearchFilters())

    assert page.total == 1
    assert page.rows[0].paper.title == "A trial of hypertension drug Y"


def test_search_papers_filters_by_topic_tier_study_type_and_date_range(db_session):
    topic_a = Topic(canonical_label="Topic A", mesh_id="D000001")
    topic_b = Topic(canonical_label="Topic B", mesh_id="D000002")
    db_session.add_all([topic_a, topic_b])
    db_session.flush()

    matching = _seed_paper(
        db_session, topic_a, "Matching paper", "abstract", date(2026, 3, 15), EvidenceTier.ESTABLISHED, StudyType.RCT
    )
    _seed_paper(
        db_session, topic_b, "Wrong topic", "abstract", date(2026, 3, 15), EvidenceTier.ESTABLISHED, StudyType.RCT
    )
    _seed_paper(
        db_session, topic_a, "Wrong tier", "abstract", date(2026, 3, 15), EvidenceTier.SPECULATIVE, StudyType.RCT
    )
    _seed_paper(
        db_session, topic_a, "Wrong study type", "abstract", date(2026, 3, 15), EvidenceTier.ESTABLISHED, StudyType.COHORT
    )
    _seed_paper(
        db_session, topic_a, "Out of date range", "abstract", date(2020, 1, 1), EvidenceTier.ESTABLISHED, StudyType.RCT
    )
    sync_search_index(db_session)

    filters = SearchFilters(
        topic_id=topic_a.id,
        tier="established",
        study_type="rct",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 12, 31),
    )
    page = search_papers(db_session, query=None, filters=filters)

    assert page.total == 1
    assert page.rows[0].paper.id == matching.id


def test_search_papers_excludes_retracted_by_default_and_includes_with_flag(db_session):
    topic = Topic(canonical_label="Retraction Topic", mesh_id="D000003")
    db_session.add(topic)
    db_session.flush()

    retracted = _seed_paper(
        db_session, topic, "A retracted paper", "abstract", date(2026, 4, 1), EvidenceTier.ESTABLISHED, StudyType.RCT,
        is_retracted=True,
    )
    sync_search_index(db_session)

    default_page = search_papers(db_session, query=None, filters=SearchFilters(topic_id=topic.id))
    assert default_page.total == 0

    with_retracted_page = search_papers(
        db_session, query=None, filters=SearchFilters(topic_id=topic.id, include_retracted=True)
    )
    assert with_retracted_page.total == 1
    assert with_retracted_page.rows[0].paper.id == retracted.id


def test_search_papers_paginates_results(db_session):
    topic = Topic(canonical_label="Pagination Topic", mesh_id="D000004")
    db_session.add(topic)
    db_session.flush()

    for i in range(5):
        _seed_paper(
            db_session, topic, f"Paper {i}", "abstract", date(2026, 1, i + 1), EvidenceTier.ESTABLISHED, StudyType.RCT
        )
    sync_search_index(db_session)

    page1 = search_papers(db_session, query=None, filters=SearchFilters(topic_id=topic.id), page=1, page_size=2)
    page2 = search_papers(db_session, query=None, filters=SearchFilters(topic_id=topic.id), page=2, page_size=2)

    assert page1.total == 5
    assert len(page1.rows) == 2
    assert len(page2.rows) == 2
    assert {r.paper.id for r in page1.rows}.isdisjoint({r.paper.id for r in page2.rows})
