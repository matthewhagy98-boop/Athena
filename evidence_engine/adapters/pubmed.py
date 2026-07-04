from datetime import date, datetime

import httpx
from defusedxml import ElementTree
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.adapters.base import RawPaper
from evidence_engine.config import get_settings
from evidence_engine.db.models import Topic

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


class PubMedAdapter:
    def _api_params(self) -> dict:
        settings = get_settings()
        return {"api_key": settings.ncbi_api_key} if settings.ncbi_api_key else {}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _search_ids(self, topic: Topic, since: datetime | None) -> list[str]:
        params = {
            "db": "pubmed",
            "term": f"{topic.canonical_label}[MeSH Terms]",
            "retmode": "json",
            "retmax": "500",
            **self._api_params(),
        }
        if since is not None:
            params["datetype"] = "pdat"
            params["mindate"] = since.strftime("%Y/%m/%d")
            params["maxdate"] = datetime.utcnow().strftime("%Y/%m/%d")

        with httpx.Client(timeout=15.0) as client:
            resp = client.get(ESEARCH_URL, params=params)
            resp.raise_for_status()
            return resp.json()["esearchresult"]["idlist"]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _fetch_records(self, pmids: list[str]) -> str:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                EFETCH_URL,
                params={
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "rettype": "abstract",
                    "retmode": "xml",
                    **self._api_params(),
                },
            )
            resp.raise_for_status()
            return resp.text

    def _parse_pub_date(self, article) -> date | None:
        pub_date_el = article.find(".//PubmedData/History/PubMedPubDate[@PubStatus='pubmed']")
        if pub_date_el is None:
            return None
        year = pub_date_el.findtext("Year")
        month = pub_date_el.findtext("Month")
        day = pub_date_el.findtext("Day")
        if not year:
            return None
        month_num = _MONTHS.get(month, None) if month and not month.isdigit() else (int(month) if month else 1)
        return date(int(year), month_num or 1, int(day) if day else 1)

    def _parse_article(self, article) -> RawPaper:
        pmid = article.findtext(".//MedlineCitation/PMID")
        title = article.findtext(".//ArticleTitle")
        abstract = article.findtext(".//Abstract/AbstractText")
        authors = []
        for author in article.findall(".//AuthorList/Author"):
            last = author.findtext("LastName") or ""
            first = author.findtext("ForeName") or ""
            name = f"{last} {first}".strip()
            if name:
                authors.append(name)
        journal = article.findtext(".//Journal/Title")
        issn = article.findtext(".//Journal/ISSN")
        doi = None
        for eloc in article.findall(".//ELocationID"):
            if eloc.get("EIdType") == "doi":
                doi = eloc.text
        pub_types = [
            pt.text for pt in article.findall(".//PublicationTypeList/PublicationType") if pt.text
        ]

        return RawPaper(
            source="pubmed",
            pmid=pmid,
            doi=doi,
            title=title,
            abstract=abstract,
            authors=authors,
            journal=journal,
            journal_issn=issn,
            pub_date=self._parse_pub_date(article),
            publication_types=pub_types,
            raw_metadata={},
        )

    def fetch_new(self, topic: Topic, since: datetime | None) -> list[RawPaper]:
        pmids = self._search_ids(topic, since)
        if not pmids:
            return []
        xml_text = self._fetch_records(pmids)
        root = ElementTree.fromstring(xml_text)
        return [self._parse_article(article) for article in root.findall(".//PubmedArticle")]
