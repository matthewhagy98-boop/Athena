from datetime import date, datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.adapters.base import RawPaper
from evidence_engine.config import get_settings
from evidence_engine.db.models import Topic

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,publicationDate,citationCount,influentialCitationCount,journal,externalIds,authors"


class SemanticScholarAdapter:
    def _headers(self) -> dict:
        settings = get_settings()
        return {"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
    def _search(self, query: str) -> list[dict]:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                SEARCH_URL,
                params={"query": query, "fields": FIELDS, "limit": 100},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("data", [])

    def _parse_record(self, record: dict) -> RawPaper:
        external_ids = record.get("externalIds") or {}
        pub_date = None
        if record.get("publicationDate"):
            pub_date = datetime.strptime(record["publicationDate"], "%Y-%m-%d").date()

        return RawPaper(
            source="semantic_scholar",
            semantic_scholar_id=record.get("paperId"),
            doi=external_ids.get("DOI"),
            pmid=external_ids.get("PubMed"),
            title=record.get("title"),
            abstract=record.get("abstract"),
            authors=[a["name"] for a in record.get("authors", []) if a.get("name")],
            journal=(record.get("journal") or {}).get("name"),
            pub_date=pub_date,
            citation_count=record.get("citationCount"),
            raw_metadata={"influentialCitationCount": record.get("influentialCitationCount")},
        )

    def fetch_new(self, topic: Topic, since: datetime | None) -> list[RawPaper]:
        records = self._search(topic.canonical_label)
        papers = [self._parse_record(r) for r in records]
        if since is not None:
            papers = [p for p in papers if p.pub_date is None or p.pub_date >= since.date()]
        return papers
