import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.db.models import Paper, PaperTopic, Topic

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _search_retracted(pmids: list[str]) -> set[str]:
    pmid_query = " OR ".join(pmids)
    term = f"({pmid_query}) AND retracted publication[Publication Type]"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(ESEARCH_URL, params={"db": "pubmed", "term": term, "retmode": "json", "retmax": "500"})
        resp.raise_for_status()
        return set(resp.json()["esearchresult"]["idlist"])


def recheck_retractions(session: Session, topic: Topic) -> list[Paper]:
    papers = (
        session.execute(
            select(Paper)
            .join(PaperTopic, PaperTopic.paper_id == Paper.id)
            .where(PaperTopic.topic_id == topic.id, Paper.pmid.isnot(None), Paper.is_retracted.is_(False))
        )
        .scalars()
        .all()
    )
    if not papers:
        return []

    pmid_to_paper = {p.pmid: p for p in papers}
    retracted_pmids = _search_retracted(list(pmid_to_paper.keys()))

    newly_retracted = []
    for pmid in retracted_pmids:
        paper = pmid_to_paper.get(pmid)
        if paper:
            paper.is_retracted = True
            newly_retracted.append(paper)
    return newly_retracted
