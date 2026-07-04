from datetime import datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.adapters.base import RawPaper
from evidence_engine.db.models import Topic

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


class ClinicalTrialsAdapter:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _search(self, query: str) -> list[dict]:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(STUDIES_URL, params={"query.term": query, "pageSize": 100})
            resp.raise_for_status()
            return resp.json().get("studies") or []

    def _parse_study(self, study: dict) -> RawPaper:
        protocol = study.get("protocolSection") or {}
        identification = protocol.get("identificationModule") or {}
        status = protocol.get("statusModule") or {}
        design = protocol.get("designModule") or {}
        enrollment = design.get("enrollmentInfo") or {}

        return RawPaper(
            source="clinicaltrials",
            nct_id=identification.get("nctId"),
            title=identification.get("briefTitle"),
            trial_status=status.get("overallStatus"),
            registered_sample_size=enrollment.get("count"),
            raw_metadata=study,
        )

    def fetch_new(self, topic: Topic, since: datetime | None) -> list[RawPaper]:
        studies = self._search(topic.canonical_label)
        return [self._parse_study(s) for s in studies]
