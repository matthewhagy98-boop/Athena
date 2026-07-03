from dataclasses import dataclass

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.config import get_settings

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


@dataclass
class MeshResolution:
    mesh_id: str
    canonical_label: str


def _api_params() -> dict:
    settings = get_settings()
    params = {}
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    return params


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def resolve_to_mesh(term: str) -> MeshResolution | None:
    with httpx.Client(timeout=10.0) as client:
        search_resp = client.get(
            ESEARCH_URL,
            params={"db": "mesh", "term": term, "retmode": "json", **_api_params()},
        )
        search_resp.raise_for_status()
        id_list = search_resp.json()["esearchresult"]["idlist"]
        if not id_list:
            return None

        mesh_uid = id_list[0]
        summary_resp = client.get(
            ESUMMARY_URL,
            params={"db": "mesh", "id": mesh_uid, "retmode": "json", **_api_params()},
        )
        summary_resp.raise_for_status()
        entry = summary_resp.json()["result"][mesh_uid]
        terms = entry.get("ds_meshterms", [])
        if not terms:
            return None

        return MeshResolution(mesh_id=mesh_uid, canonical_label=terms[0])
