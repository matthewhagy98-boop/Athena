import httpx
import respx

from evidence_engine.adapters.clinicaltrials import ClinicalTrialsAdapter
from evidence_engine.db.models import Topic

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


@respx.mock
def test_fetch_new_returns_parsed_raw_papers():
    respx.get(STUDIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "studies": [
                    {
                        "protocolSection": {
                            "identificationModule": {
                                "nctId": "NCT01234567",
                                "briefTitle": "Trial of Drug X for Outcome Y",
                            },
                            "statusModule": {"overallStatus": "COMPLETED"},
                            "designModule": {"enrollmentInfo": {"count": 300}},
                        }
                    }
                ]
            },
        )
    )

    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    adapter = ClinicalTrialsAdapter()
    papers = adapter.fetch_new(topic, since=None)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.source == "clinicaltrials"
    assert paper.nct_id == "NCT01234567"
    assert paper.title == "Trial of Drug X for Outcome Y"
    assert paper.trial_status == "COMPLETED"
    assert paper.registered_sample_size == 300
