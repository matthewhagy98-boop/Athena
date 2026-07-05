import uuid
from datetime import date, datetime

from fastapi.testclient import TestClient

from enterprise_api.api import app, get_db
from enterprise_api.provisioning import create_api_key, create_organization
from evidence_engine.db.models import ChangeEvent, ChangeEventType, EvidenceTier, Paper, PaperTopic, Score, StudyType, Topic
from webapp.search_index import sync_search_index


def _client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _seed_paper(db_session, topic, title, tier=EvidenceTier.ESTABLISHED, study_type=StudyType.RCT, pub_date=date(2026, 5, 1)):
    paper = Paper(title=title, pub_date=pub_date)
    db_session.add(paper)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    db_session.add(Score(paper_id=paper.id, evidence_tier=tier, study_type=study_type, final_score=70.0, model_version="v1"))
    db_session.add(ChangeEvent(topic_id=topic.id, paper_id=paper.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 5, 1)))
    db_session.flush()
    return paper


def test_search_endpoint_requires_authorization_header(db_session):
    client = _client(db_session)
    response = client.get("/v1/search")
    assert response.status_code == 401


def test_search_endpoint_rejects_unknown_api_key(db_session):
    client = _client(db_session)
    response = client.get("/v1/search", headers={"Authorization": "Bearer not-a-real-key"})
    assert response.status_code == 401


def test_search_endpoint_rejects_suspended_organization(db_session):
    organization = create_organization(db_session, "Suspended Org")
    _, plaintext_key = create_api_key(db_session, organization)
    organization.status = "suspended"
    db_session.flush()

    client = _client(db_session)
    response = client.get("/v1/search", headers={"Authorization": f"Bearer {plaintext_key}"})
    assert response.status_code == 403


def test_search_endpoint_returns_matching_papers_for_valid_key(db_session):
    organization = create_organization(db_session, "Acme Corp")
    _, plaintext_key = create_api_key(db_session, organization)
    topic = Topic(canonical_label="Search Topic", mesh_id="D000001")
    db_session.add(topic)
    db_session.flush()
    _seed_paper(db_session, topic, "A study of drug Z")
    sync_search_index(db_session)

    client = _client(db_session)
    response = client.get("/v1/search", params={"q": "drug Z"}, headers={"Authorization": f"Bearer {plaintext_key}"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["rows"][0]["paper"]["title"] == "A study of drug Z"


def test_search_endpoint_enforces_rate_limit(db_session):
    organization = create_organization(db_session, "Rate Limited Org", rate_limit_per_hour=1)
    _, plaintext_key = create_api_key(db_session, organization)

    client = _client(db_session)
    headers = {"Authorization": f"Bearer {plaintext_key}"}

    first_response = client.get("/v1/search", headers=headers)
    second_response = client.get("/v1/search", headers=headers)

    assert first_response.status_code == 200
    assert second_response.status_code == 429


def test_compare_papers_endpoint_returns_partial_results_for_valid_key(db_session):
    organization = create_organization(db_session, "Beta Inc")
    _, plaintext_key = create_api_key(db_session, organization)
    paper = Paper(title="Existing paper")
    db_session.add(paper)
    db_session.flush()
    missing_id = uuid.uuid4()

    client = _client(db_session)
    response = client.get(
        "/v1/compare/papers",
        params={"paper_ids": [str(paper.id), str(missing_id)]},
        headers={"Authorization": f"Bearer {plaintext_key}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 1
    assert body["unresolved_ids"] == [str(missing_id)]


def test_compare_topics_endpoint_for_valid_key(db_session):
    organization = create_organization(db_session, "Gamma LLC")
    _, plaintext_key = create_api_key(db_session, organization)
    topic = Topic(canonical_label="Compare Topic", mesh_id="D000002")
    db_session.add(topic)
    db_session.flush()

    client = _client(db_session)
    response = client.get(
        "/v1/compare/topics",
        params={"topic_ids": [str(topic.id)]},
        headers={"Authorization": f"Bearer {plaintext_key}"},
    )

    assert response.status_code == 200
    assert response.json()["rows"][0]["topic"]["canonical_label"] == "Compare Topic"


def test_tier_distribution_endpoint_for_valid_key(db_session):
    organization = create_organization(db_session, "Delta Co")
    _, plaintext_key = create_api_key(db_session, organization)
    topic = Topic(canonical_label="Viz Topic", mesh_id="D000003")
    db_session.add(topic)
    db_session.flush()
    _seed_paper(db_session, topic, "Viz paper", tier=EvidenceTier.ESTABLISHED)

    client = _client(db_session)
    response = client.get(
        f"/v1/topics/{topic.id}/tier-distribution", headers={"Authorization": f"Bearer {plaintext_key}"}
    )

    assert response.status_code == 200
    assert response.json()["established"] == 1


def test_timeline_endpoint_for_valid_key(db_session):
    organization = create_organization(db_session, "Epsilon Ltd")
    _, plaintext_key = create_api_key(db_session, organization)
    topic = Topic(canonical_label="Timeline Topic", mesh_id="D000004")
    db_session.add(topic)
    db_session.flush()
    db_session.add(ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 5, 1)))
    db_session.flush()

    client = _client(db_session)
    response = client.get(
        f"/v1/topics/{topic.id}/timeline",
        params={"window_start": "2026-04-01T00:00:00", "window_end": "2026-06-01T00:00:00"},
        headers={"Authorization": f"Bearer {plaintext_key}"},
    )

    assert response.status_code == 200
    assert response.json()[0]["count"] == 1


def test_tier_distribution_endpoint_returns_404_for_unknown_topic(db_session):
    organization = create_organization(db_session, "Zeta Corp")
    _, plaintext_key = create_api_key(db_session, organization)

    client = _client(db_session)
    response = client.get(
        f"/v1/topics/{uuid.uuid4()}/tier-distribution", headers={"Authorization": f"Bearer {plaintext_key}"}
    )

    assert response.status_code == 404
