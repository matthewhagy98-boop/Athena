from evidence_engine.adapters.base import RawPaper
from evidence_engine.adapters.merge import merge_raw_papers, upsert_paper
from evidence_engine.db.models import Paper, Topic


def test_merge_raw_papers_combines_matching_doi():
    pubmed_paper = RawPaper(
        source="pubmed",
        pmid="12345678",
        doi="10.1016/example.2024.001",
        title="Effect of Drug X",
        abstract="Background...",
        publication_types=["Randomized Controlled Trial"],
    )
    s2_paper = RawPaper(
        source="semantic_scholar",
        doi="10.1016/example.2024.001",
        semantic_scholar_id="abc123",
        citation_count=42,
    )

    merged = merge_raw_papers([pubmed_paper, s2_paper])

    assert len(merged) == 1
    combined = merged[0]
    assert combined.pmid == "12345678"
    assert combined.semantic_scholar_id == "abc123"
    assert combined.citation_count == 42
    assert combined.publication_types == ["Randomized Controlled Trial"]


def test_merge_raw_papers_keeps_distinct_papers_separate():
    paper_a = RawPaper(source="pubmed", doi="10.1/aaa", title="Paper A")
    paper_b = RawPaper(source="pubmed", doi="10.1/bbb", title="Paper B")

    merged = merge_raw_papers([paper_a, paper_b])

    assert len(merged) == 2


def test_upsert_paper_creates_new_paper_and_links_topic(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    raw_paper = RawPaper(source="pubmed", pmid="12345678", doi="10.1/xyz", title="Effect of Drug X")
    paper = upsert_paper(db_session, topic, raw_paper)
    db_session.flush()

    assert paper.pmid == "12345678"
    fetched = db_session.query(Paper).filter_by(pmid="12345678").one()
    assert fetched.id == paper.id


def test_upsert_paper_updates_existing_paper_on_second_call(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    first = upsert_paper(db_session, topic, RawPaper(source="pubmed", pmid="12345678", title="Draft Title"))
    db_session.flush()

    second = upsert_paper(
        db_session, topic, RawPaper(source="semantic_scholar", pmid="12345678", citation_count=10)
    )
    db_session.flush()

    assert second.id == first.id
    assert db_session.query(Paper).count() == 1
