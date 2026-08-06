import httpx
import pytest
import respx

from citations.provider import BATCH_URL, CitationProviderError, SemanticScholarCitationClient


@respx.mock
def test_fetch_batch_returns_observations_keyed_by_id():
    respx.post(BATCH_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"paperId": "aaa", "citationCount": 132, "influentialCitationCount": 9},
                {"paperId": "bbb", "citationCount": 4, "influentialCitationCount": None},
            ],
        )
    )

    result = SemanticScholarCitationClient().fetch_batch(["aaa", "bbb"])

    assert result["aaa"].citation_count == 132
    assert result["aaa"].influential_citation_count == 9
    assert result["bbb"].influential_citation_count is None


@respx.mock
def test_fetch_batch_omits_ids_the_provider_returned_null_for():
    # The batch endpoint returns a null entry for ids it cannot resolve.
    respx.post(BATCH_URL).mock(
        return_value=httpx.Response(200, json=[{"paperId": "aaa", "citationCount": 5}, None])
    )

    result = SemanticScholarCitationClient().fetch_batch(["aaa", "missing"])

    assert "aaa" in result
    assert "missing" not in result


@respx.mock
def test_fetch_batch_raises_provider_error_on_rate_limit():
    respx.post(BATCH_URL).mock(return_value=httpx.Response(429, text="slow down"))

    with pytest.raises(CitationProviderError) as exc:
        SemanticScholarCitationClient().fetch_batch(["aaa"])

    assert exc.value.status_code == 429


def test_fetch_batch_rejects_oversized_batch():
    with pytest.raises(ValueError, match="500"):
        SemanticScholarCitationClient().fetch_batch(["x"] * 501)


def test_fetch_batch_with_no_ids_makes_no_request():
    # No respx mock registered: any HTTP call would raise.
    assert SemanticScholarCitationClient().fetch_batch([]) == {}
