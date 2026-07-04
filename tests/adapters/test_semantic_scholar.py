from datetime import date

import httpx
import respx

from evidence_engine.adapters.semantic_scholar import SemanticScholarAdapter
from evidence_engine.db.models import Topic

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


@respx.mock
def test_fetch_new_returns_parsed_raw_papers():
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "abc123",
                        "title": "Effect of Drug X on Outcome Y",
                        "abstract": "This randomized controlled trial...",
                        "publicationDate": "2024-03-15",
                        "citationCount": 42,
                        "influentialCitationCount": 5,
                        "journal": {"name": "The Lancet"},
                        "externalIds": {"DOI": "10.1016/example.2024.001", "PubMed": "12345678"},
                        "authors": [{"name": "Jane Smith"}, {"name": "Alan Doe"}],
                    }
                ]
            },
        )
    )

    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    adapter = SemanticScholarAdapter()
    papers = adapter.fetch_new(topic, since=None)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.source == "semantic_scholar"
    assert paper.semantic_scholar_id == "abc123"
    assert paper.doi == "10.1016/example.2024.001"
    assert paper.pmid == "12345678"
    assert paper.citation_count == 42
    assert paper.pub_date == date(2024, 3, 15)
    assert paper.authors == ["Jane Smith", "Alan Doe"]


@respx.mock
def test_fetch_new_handles_null_authors():
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "def456",
                        "title": "Some Research Study",
                        "abstract": "An abstract here...",
                        "publicationDate": "2024-01-10",
                        "citationCount": 10,
                        "influentialCitationCount": 1,
                        "journal": {"name": "Nature"},
                        "externalIds": {"DOI": "10.1038/example.2024.002"},
                        "authors": None,
                    }
                ]
            },
        )
    )

    topic = Topic(canonical_label="Cancer Research", mesh_id="68002310")
    adapter = SemanticScholarAdapter()
    papers = adapter.fetch_new(topic, since=None)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.semantic_scholar_id == "def456"
    assert paper.authors == []
