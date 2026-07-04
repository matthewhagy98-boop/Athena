import httpx
import respx

from evidence_engine.adapters.retractions import recheck_retractions
from evidence_engine.db.models import Paper, PaperTopic, Topic

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


@respx.mock
def test_recheck_retractions_flags_matching_pmid(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    retracted_paper = Paper(pmid="11111111", title="Retracted paper")
    healthy_paper = Paper(pmid="22222222", title="Healthy paper")
    db_session.add_all([retracted_paper, healthy_paper])
    db_session.flush()
    db_session.add_all(
        [
            PaperTopic(paper_id=retracted_paper.id, topic_id=topic.id),
            PaperTopic(paper_id=healthy_paper.id, topic_id=topic.id),
        ]
    )
    db_session.flush()

    respx.get(ESEARCH_URL).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["11111111"]}})
    )

    newly_retracted = recheck_retractions(db_session, topic)

    assert len(newly_retracted) == 1
    assert newly_retracted[0].pmid == "11111111"
    assert retracted_paper.is_retracted is True
    assert healthy_paper.is_retracted is False


def test_recheck_retractions_returns_empty_when_no_papers_have_pmid(db_session):
    topic = Topic(canonical_label="Rare Condition", mesh_id="D000000")
    db_session.add(topic)
    db_session.flush()

    assert recheck_retractions(db_session, topic) == []
