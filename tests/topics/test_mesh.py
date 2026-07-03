import httpx
import respx

from evidence_engine.topics.mesh import resolve_to_mesh

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


@respx.mock
def test_resolve_to_mesh_returns_canonical_term():
    respx.get(ESEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["68009203"]}},
        )
    )
    respx.get(ESUMMARY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["68009203"],
                    "68009203": {"ds_meshterms": ["Myocardial Infarction"]},
                }
            },
        )
    )

    result = resolve_to_mesh("heart attack")

    assert result is not None
    assert result.mesh_id == "68009203"
    assert result.canonical_label == "Myocardial Infarction"


@respx.mock
def test_resolve_to_mesh_returns_none_when_no_match():
    respx.get(ESEARCH_URL).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": []}})
    )

    result = resolve_to_mesh("not a real medical term xyz")

    assert result is None
