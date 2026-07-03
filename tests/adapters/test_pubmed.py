from datetime import date

import httpx
import respx

from evidence_engine.adapters.pubmed import PubMedAdapter
from evidence_engine.db.models import Topic

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


@respx.mock
def test_fetch_new_returns_parsed_raw_papers():
    respx.get(ESEARCH_URL).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["12345678"]}})
    )
    with open("tests/fixtures/pubmed_efetch_sample.xml", "rb") as f:
        xml_body = f.read()
    respx.get(EFETCH_URL).mock(return_value=httpx.Response(200, content=xml_body))

    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    adapter = PubMedAdapter()
    papers = adapter.fetch_new(topic, since=None)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.source == "pubmed"
    assert paper.pmid == "12345678"
    assert paper.doi == "10.1016/example.2024.001"
    assert paper.title == "Effect of Drug X on Outcome Y"
    assert "Smith Jane" in paper.authors or "Jane Smith" in paper.authors
    assert paper.journal_issn == "0140-6736"
    assert paper.publication_types == ["Randomized Controlled Trial"]
    assert paper.pub_date == date(2024, 3, 15)
