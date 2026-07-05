import uuid
from datetime import date, datetime

from fastapi.testclient import TestClient

from digest.profiles import create_user
from evidence_engine.db.models import ChangeEvent, ChangeEventType, EvidenceTier, Paper, PaperTopic, Score, StudyType, Topic
from webapp.api import app, get_db
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


def test_search_endpoint_returns_matching_papers(db_session):
    topic = Topic(canonical_label="Search Topic", mesh_id="D000001")
    db_session.add(topic)
    db_session.flush()
    paper = _seed_paper(db_session, topic, "A study of drug Z")
    sync_search_index(db_session)

    client = _client(db_session)
    response = client.get("/search", params={"q": "drug Z"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["rows"][0]["paper"]["title"] == "A study of drug Z"


def test_search_endpoint_rejects_invalid_tier_with_422(db_session):
    client = _client(db_session)
    response = client.get("/search", params={"tier": "not_a_real_tier"})
    assert response.status_code == 422


def test_compare_papers_endpoint_returns_partial_results(db_session):
    paper = Paper(title="Existing paper")
    db_session.add(paper)
    db_session.flush()
    missing_id = uuid.uuid4()

    client = _client(db_session)
    response = client.get("/compare/papers", params={"paper_ids": [str(paper.id), str(missing_id)]})

    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 1
    assert body["unresolved_ids"] == [str(missing_id)]


def test_compare_topics_endpoint_returns_partial_results(db_session):
    topic = Topic(canonical_label="Compare Topic", mesh_id="D000002")
    db_session.add(topic)
    db_session.flush()
    missing_id = uuid.uuid4()

    client = _client(db_session)
    response = client.get("/compare/topics", params={"topic_ids": [str(topic.id), str(missing_id)]})

    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 1
    assert body["unresolved_ids"] == [str(missing_id)]


def test_compare_papers_endpoint_handles_empty_input(db_session):
    client = _client(db_session)
    response = client.get("/compare/papers")

    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == []
    assert body["unresolved_ids"] == []


def test_compare_topics_endpoint_handles_empty_input(db_session):
    client = _client(db_session)
    response = client.get("/compare/topics")

    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == []
    assert body["unresolved_ids"] == []


def test_saved_search_crud_and_run_lifecycle(db_session):
    user = create_user(db_session, "api_user@example.com")
    topic = Topic(canonical_label="Saved Search Topic", mesh_id="D000003")
    db_session.add(topic)
    db_session.flush()
    _seed_paper(db_session, topic, "A saved-search matching paper")
    sync_search_index(db_session)

    client = _client(db_session)

    create_response = client.post(
        "/saved-searches", json={"user_id": str(user.id), "name": "My Topic", "query_params": {"topic_id": str(topic.id)}}
    )
    assert create_response.status_code == 200
    saved_id = create_response.json()["id"]

    list_response = client.get("/saved-searches", params={"user_id": str(user.id)})
    assert len(list_response.json()) == 1

    run_response = client.post(f"/saved-searches/{saved_id}/run", params={"user_id": str(user.id)})
    assert run_response.status_code == 200
    assert run_response.json()["total"] == 1

    delete_response = client.delete(f"/saved-searches/{saved_id}", params={"user_id": str(user.id)})
    assert delete_response.status_code == 204

    list_after_delete = client.get("/saved-searches", params={"user_id": str(user.id)})
    assert list_after_delete.json() == []


def test_saved_search_run_returns_404_for_unknown_user(db_session):
    client = _client(db_session)
    response = client.post(f"/saved-searches/{uuid.uuid4()}/run", params={"user_id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_tier_distribution_endpoint(db_session):
    topic = Topic(canonical_label="Viz Topic", mesh_id="D000004")
    db_session.add(topic)
    db_session.flush()
    _seed_paper(db_session, topic, "Viz paper", tier=EvidenceTier.ESTABLISHED)

    client = _client(db_session)
    response = client.get(f"/topics/{topic.id}/tier-distribution")

    assert response.status_code == 200
    assert response.json()["established"] == 1


def test_timeline_endpoint(db_session):
    topic = Topic(canonical_label="Timeline Topic", mesh_id="D000005")
    db_session.add(topic)
    db_session.flush()
    db_session.add(ChangeEvent(topic_id=topic.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 5, 1)))
    db_session.flush()

    client = _client(db_session)
    response = client.get(
        f"/topics/{topic.id}/timeline",
        params={"window_start": "2026-04-01T00:00:00", "window_end": "2026-06-01T00:00:00"},
    )

    assert response.status_code == 200
    assert response.json()[0]["count"] == 1
