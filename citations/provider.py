from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from evidence_engine.config import get_settings

BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
BATCH_FIELDS = "citationCount,influentialCitationCount"
MAX_BATCH = 500


@dataclass(frozen=True)
class CitationObservation:
    semantic_scholar_id: str
    citation_count: int
    influential_citation_count: int | None


class CitationProviderError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _is_retryable(exc: BaseException) -> bool:
    # Retry transport hiccups and 5xx; never retry a 429. The job's own pacing
    # handles rate limits, and hammering a 429 with retries makes it worse.
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, CitationProviderError) and exc.status_code is not None and exc.status_code >= 500


class SemanticScholarCitationClient:
    def _headers(self) -> dict:
        settings = get_settings()
        return {"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else {}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def fetch_batch(self, ids: list[str]) -> dict[str, CitationObservation]:
        if len(ids) > MAX_BATCH:
            raise ValueError(f"batch of {len(ids)} exceeds the provider maximum of {MAX_BATCH}")
        if not ids:
            return {}

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                BATCH_URL,
                params={"fields": BATCH_FIELDS},
                json={"ids": ids},
                headers=self._headers(),
            )
        if resp.status_code != 200:
            raise CitationProviderError(
                f"citation batch request failed: {resp.status_code}", status_code=resp.status_code
            )

        out: dict[str, CitationObservation] = {}
        for record in resp.json():
            # The endpoint returns a null entry, positionally, for unresolvable ids.
            if not record:
                continue
            paper_id = record.get("paperId")
            count = record.get("citationCount")
            if paper_id is None or count is None:
                continue
            out[paper_id] = CitationObservation(
                semantic_scholar_id=paper_id,
                citation_count=count,
                influential_citation_count=record.get("influentialCitationCount"),
            )
        return out
