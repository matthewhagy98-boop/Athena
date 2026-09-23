import uuid
from datetime import date, datetime

from fastapi.testclient import TestClient

from digest.profiles import create_user
from evidence_engine.db.models import ChangeEvent, ChangeEventType, EvidenceTier, Paper, PaperTopic, Score, StudyType, Topic
from sqlalchemy import select

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


def test_search_endpoint_treats_pending_score_as_unscored(db_session):
    topic = Topic(canonical_label="Pending Topic", mesh_id="D000106")
    db_session.add(topic)
    db_session.flush()
    paper = Paper(title="A paper awaiting scoring", pub_date=date(2026, 5, 1))
    db_session.add(paper)
    db_session.flush()
    db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    db_session.add(Score(paper_id=paper.id, is_pending=True, model_version="v1"))
    db_session.add(
        ChangeEvent(topic_id=topic.id, paper_id=paper.id, event_type=ChangeEventType.NEW_PAPER, detected_at=datetime(2026, 5, 1))
    )
    db_session.flush()
    sync_search_index(db_session)

    client = _client(db_session)
    response = client.get("/search", params={"q": "awaiting scoring"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["rows"][0]["score"] is None


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


def test_create_anonymous_user_endpoint(db_session):
    client = _client(db_session)
    response = client.post("/users/anonymous")
    assert response.status_code == 201
    user_id = uuid.UUID(response.json()["user_id"])

    from digest.models import User
    user = db_session.get(User, user_id)
    assert user is not None
    assert user.email.endswith("@no-reply.local")


def test_list_topics_endpoint_returns_sorted_topics(db_session):
    db_session.add(Topic(canonical_label="Zebra Topic", mesh_id="D000101"))
    db_session.add(Topic(canonical_label="Alpha Topic", mesh_id="D000102"))
    db_session.flush()

    client = _client(db_session)
    response = client.get("/topics")

    assert response.status_code == 200
    labels = [t["canonical_label"] for t in response.json()]
    assert labels == sorted(labels)
    assert {"id", "canonical_label"} <= set(response.json()[0].keys())


def test_search_rows_include_topics_abstract_and_study_type(db_session):
    topic = Topic(canonical_label="Enriched Topic", mesh_id="D000103")
    db_session.add(topic)
    db_session.flush()
    paper = _seed_paper(db_session, topic, "Enrichment study of drug Q")
    paper.abstract = "A detailed abstract about drug Q."
    db_session.flush()
    sync_search_index(db_session)

    client = _client(db_session)
    row = client.get("/search", params={"q": "drug Q"}).json()["rows"][0]

    assert row["paper"]["abstract"] == "A detailed abstract about drug Q."
    assert row["score"]["study_type"] == "rct"
    assert row["topics"] == [{"id": str(topic.id), "canonical_label": "Enriched Topic"}]


def test_compare_papers_rows_include_topics(db_session):
    topic = Topic(canonical_label="Compare Topic", mesh_id="D000104")
    db_session.add(topic)
    db_session.flush()
    paper = _seed_paper(db_session, topic, "Comparable paper")

    client = _client(db_session)
    response = client.get("/compare/papers", params={"paper_ids": [str(paper.id)]})

    assert response.json()["rows"][0]["topics"][0]["canonical_label"] == "Compare Topic"


def test_list_saved_searches_includes_last_run_at(db_session):
    user = create_user(db_session, "listrun@example.com")
    client = _client(db_session)
    client.post("/saved-searches", json={"user_id": str(user.id), "name": "Mine", "query_params": {"q": "x"}})

    rows = client.get("/saved-searches", params={"user_id": str(user.id)}).json()

    assert rows[0]["last_run_at"] is None


def test_paper_velocity_endpoint_returns_a_block_per_requested_id(db_session):
    from decimal import Decimal

    from citations.models import CitationVelocityCache

    paper = Paper(title="Velocity endpoint paper")
    db_session.add(paper)
    db_session.flush()
    db_session.add(
        CitationVelocityCache(
            paper_id=paper.id, status="ready", velocity_per_30d=Decimal("14.00"), percentile=88
        )
    )
    db_session.flush()
    missing = uuid.uuid4()

    client = _client(db_session)
    response = client.get("/papers/velocity", params={"paper_ids": [str(paper.id), str(missing)]})

    assert response.status_code == 200
    velocities = response.json()["velocities"]
    assert velocities[str(paper.id)]["velocity_per_30d"] == 14.0
    assert velocities[str(paper.id)]["percentile"] == 88
    # Every requested id appears, even one that resolves to nothing.
    assert velocities[str(missing)]["status"] == "insufficient_history"


def test_paper_velocity_endpoint_rejects_empty_and_oversized_requests(db_session):
    client = _client(db_session)

    assert client.get("/papers/velocity", params={"paper_ids": []}).status_code == 422
    too_many = {"paper_ids": [str(uuid.uuid4()) for _ in range(101)]}
    assert client.get("/papers/velocity", params=too_many).status_code == 422


def test_citation_history_endpoint_returns_observations(db_session):
    from datetime import date as _date

    from citations.models import CitationSnapshot

    paper = Paper(title="History endpoint paper")
    db_session.add(paper)
    db_session.flush()
    db_session.add(
        CitationSnapshot(
            paper_id=paper.id,
            observed_at=datetime(2026, 7, 1, 4, 0),
            observed_on=_date(2026, 7, 1),
            citation_count=104,
        )
    )
    db_session.flush()

    client = _client(db_session)
    response = client.get(f"/papers/{paper.id}/citation-history")

    assert response.status_code == 200
    body = response.json()
    assert body["observations"][0]["citation_count"] == 104
    assert body["source"] == "semantic_scholar"


def test_citation_history_endpoint_404s_for_unknown_paper(db_session):
    client = _client(db_session)

    response = client.get(f"/papers/{uuid.uuid4()}/citation-history")

    assert response.status_code == 404


def test_citation_history_endpoint_rejects_out_of_range_days(db_session):
    paper = Paper(title="Range paper")
    db_session.add(paper)
    db_session.flush()
    client = _client(db_session)

    assert client.get(f"/papers/{paper.id}/citation-history", params={"days": 5}).status_code == 422
    assert (
        client.get(f"/papers/{paper.id}/citation-history", params={"days": 5000}).status_code == 422
    )


def test_saved_search_velocity_endpoint_404s_for_unknown_saved_search(db_session):
    user = create_user(db_session, "ssvel@example.com")
    client = _client(db_session)

    response = client.get(
        f"/saved-searches/{uuid.uuid4()}/velocity", params={"user_id": str(user.id)}
    )

    assert response.status_code == 404


def test_synthesis_endpoint_returns_narrative(db_session, monkeypatch):
    from synthesis.models import ComparisonSynthesis

    paper = Paper(title="Synthesis paper")
    db_session.add(paper)
    db_session.flush()

    def fake_get_or_create(session, subject_type, subject_ids, user_id=None, **kwargs):
        return ComparisonSynthesis(
            cache_key="k" * 64,
            subject_type=subject_type,
            subject_ids=subject_ids,
            inputs_fingerprint="f" * 64,
            status="ready",
            narrative="A grounded summary.",
            claims=[{"text": "Claim.", "citations": [0]}],
            disagreements=[],
            strength_ranking=[0],
            retracted_member_indices=[],
            model_id="m",
            prompt_version="v1",
        )

    monkeypatch.setattr("webapp.api.get_or_create_synthesis", fake_get_or_create)
    client = _client(db_session)

    response = client.post("/synthesis/papers", json={"paper_ids": [str(paper.id)]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["narrative"] == "A grounded summary."
    assert body["claims"][0]["citations"] == [0]


def test_synthesis_endpoint_returns_503_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr("webapp.api.get_or_create_synthesis", lambda *a, **k: None)
    client = _client(db_session)

    response = client.post("/synthesis/papers", json={"paper_ids": [str(uuid.uuid4())]})

    assert response.status_code == 503


def test_synthesis_endpoint_returns_404_for_unknown_paper(db_session, monkeypatch):
    def raising(*args, **kwargs):
        raise ValueError("Paper deadbeef not found")

    monkeypatch.setattr("webapp.api.get_or_create_synthesis", raising)
    client = _client(db_session)

    response = client.post("/synthesis/papers", json={"paper_ids": [str(uuid.uuid4())]})

    assert response.status_code == 404


def test_synthesis_endpoint_rejects_empty_and_oversized_selections(db_session):
    client = _client(db_session)

    assert client.post("/synthesis/papers", json={"paper_ids": []}).status_code == 422
    too_many = {"paper_ids": [str(uuid.uuid4()) for _ in range(11)]}
    assert client.post("/synthesis/papers", json=too_many).status_code == 422


def test_the_synthesis_member_cap_boundary_is_exact(db_session, monkeypatch):
    # The brief's selection test only checks 0 and 11, both of which reject, so a mutant
    # moving the cutoff to 5 or 20 would pass it. MAX_SYNTHESIS_MEMBERS bounds the prompt
    # size, the model cost per request, and the per-member session.get loop inside the
    # service -- it is the reason that loop is acceptable -- so the exact boundary is the
    # behaviour worth pinning, not "some large number is refused".
    from synthesis.models import ComparisonSynthesis
    from webapp.api import MAX_SYNTHESIS_MEMBERS

    reached = []

    def fake_get_or_create(session, subject_type, subject_ids, user_id=None, **kwargs):
        reached.append(len(subject_ids))
        return ComparisonSynthesis(
            cache_key="k" * 64,
            subject_type=subject_type,
            subject_ids=subject_ids,
            inputs_fingerprint="f" * 64,
            status="ready",
            narrative="A grounded summary.",
            claims=[{"text": "Claim.", "citations": [0]}],
            disagreements=[],
            strength_ranking=[0],
            retracted_member_indices=[],
            model_id="m",
            prompt_version="v1",
        )

    monkeypatch.setattr("webapp.api.get_or_create_synthesis", fake_get_or_create)
    client = _client(db_session)

    def post(n):
        return client.post(
            "/synthesis/papers", json={"paper_ids": [str(uuid.uuid4()) for _ in range(n)]}
        )

    assert post(MAX_SYNTHESIS_MEMBERS).status_code == 200
    assert post(MAX_SYNTHESIS_MEMBERS + 1).status_code == 422

    # The oversized request must be refused by validation, never by the service -- the
    # cap exists to stop the work from starting, not to discard its result.
    assert reached == [MAX_SYNTHESIS_MEMBERS]


def test_synthesis_endpoint_rejects_a_malformed_user_id_as_422_not_404(db_session, monkeypatch):
    # The user_id parse used to sit inside the try that maps ValueError to 404, so a bad
    # user_id was reported as "paper not found" -- the wrong status, and a message about
    # the wrong field entirely.
    called = []

    def fake_get_or_create(session, subject_type, subject_ids, user_id=None, **kwargs):
        called.append(user_id)
        return None

    monkeypatch.setattr("webapp.api.get_or_create_synthesis", fake_get_or_create)
    client = _client(db_session)

    response = client.post(
        "/synthesis/papers",
        json={"paper_ids": [str(uuid.uuid4())], "user_id": "not-a-uuid"},
    )

    assert response.status_code == 422
    assert "user_id" in response.json()["detail"]
    assert called == []  # rejected before the service is reached


def test_synthesis_endpoint_serializes_a_real_row_id(db_session, monkeypatch):
    # Every other synthesis endpoint test builds a ComparisonSynthesis that is never
    # flushed, so row.id is None and _synthesis_out renders the string "None". That made
    # the id field invisible to the whole suite. This one flushes a real row.
    from synthesis.models import ComparisonSynthesis

    stored = ComparisonSynthesis(
        cache_key="r" * 64,
        subject_type="paper",
        subject_ids=[],
        inputs_fingerprint="f" * 64,
        status="ready",
        narrative="A grounded summary.",
        claims=[],
        disagreements=[],
        strength_ranking=[],
        retracted_member_indices=[],
        model_id="m",
        prompt_version="v1",
    )
    db_session.add(stored)
    db_session.flush()

    monkeypatch.setattr(
        "webapp.api.get_or_create_synthesis",
        lambda *a, **k: stored,
    )
    client = _client(db_session)

    response = client.post("/synthesis/papers", json={"paper_ids": [str(uuid.uuid4())]})

    assert response.status_code == 200
    assert response.json()["id"] == str(stored.id)
    assert response.json()["id"] != "None"


def test_synthesis_endpoint_survives_a_stale_user_id(db_session, monkeypatch):
    # The only /synthesis/papers test that goes through the REAL service. Every other one
    # monkeypatches it, which is exactly why this shipped: an unknown user_id reaches
    # SynthesisGeneration's FK and raises IntegrityError -- after the model call, and not
    # a ValueError, so the endpoint's handler misses it and the rollback destroys the
    # generated row. One paid call per click, nothing cached, a 500, forever.
    #
    # Anonymous ids persist in localStorage indefinitely, and this repo's own conftest
    # deletes anon users on every test run, so a developer hits this by running the suite
    # and then opening the app.
    from synthesis.models import ComparisonSynthesis, SynthesisGeneration
    from synthesis.validation import ValidationResult

    monkeypatch.setattr("synthesis.service._synthesis_enabled", lambda: True)

    paper = Paper(title="Stale user paper", abstract="Abstract.")
    db_session.add(paper)
    db_session.flush()

    monkeypatch.setattr(
        "synthesis.service.default_generate",
        lambda members, call=None: (
            ValidationResult(ok=True, narrative="Grounded.", claims=[{"text": "c", "citations": [0]}]),
            10,
        ),
    )
    client = _client(db_session)

    response = client.post(
        "/synthesis/papers",
        json={"paper_ids": [str(paper.id)], "user_id": str(uuid.uuid4())},
    )

    assert response.status_code == 200
    assert response.json()["narrative"] == "Grounded."

    # The work was kept: the synthesis persisted, and the telemetry row records the
    # generation with its attribution dropped rather than the request failing.
    assert db_session.execute(select(ComparisonSynthesis)).scalars().one() is not None
    gen = db_session.execute(select(SynthesisGeneration)).scalars().one()
    assert gen.user_id is None
    assert gen.outcome == "ready"


def test_synthesis_response_carries_provenance(db_session, monkeypatch):
    # The panel must be able to say which model wrote the narrative and when. Without
    # these two fields the provenance line the spec requires is not merely missing from
    # the UI -- it is impossible to build from the API contract.
    from datetime import datetime

    from synthesis.models import ComparisonSynthesis

    monkeypatch.setattr(
        "webapp.api.get_or_create_synthesis",
        lambda *a, **k: ComparisonSynthesis(
            cache_key="p" * 64,
            subject_type="paper",
            subject_ids=[],
            inputs_fingerprint="f" * 64,
            status="ready",
            narrative="A grounded summary.",
            claims=[],
            disagreements=[],
            strength_ranking=[],
            retracted_member_indices=[],
            model_id="claude-sonnet-4-6",
            prompt_version="v1",
            generated_at=datetime(2026, 9, 15, 12, 0, 0),
        ),
    )
    client = _client(db_session)

    body = client.post("/synthesis/papers", json={"paper_ids": [str(uuid.uuid4())]}).json()

    assert body["model_id"] == "claude-sonnet-4-6"
    assert body["generated_at"] == "2026-09-15T12:00:00Z"


def test_dashboard_activity_is_empty_before_the_job_has_run(db_session):
    client = _client(db_session)

    body = client.get("/dashboard/activity").json()

    assert body == {"computed_at": None, "window_start": None, "window_end": None, "topics": []}


def test_dashboard_activity_rejects_an_out_of_range_limit(db_session):
    client = _client(db_session)

    assert client.get("/dashboard/activity?limit=0").status_code == 422
    assert client.get("/dashboard/activity?limit=26").status_code == 422
    assert client.get("/dashboard/activity?limit=25").status_code == 200
    assert client.get("/dashboard/activity?limit=1").status_code == 200


def test_dashboard_changes_rejects_out_of_range_parameters(db_session):
    client = _client(db_session)

    assert client.get("/dashboard/changes?days=0").status_code == 422
    assert client.get("/dashboard/changes?days=31").status_code == 422
    assert client.get("/dashboard/changes?limit=51").status_code == 422
    assert client.get("/dashboard/changes?days=30&limit=50").status_code == 200


def test_dashboard_personal_returns_200_and_no_profile_for_a_fresh_user(db_session):
    # The cold-start case, and the one that must never 500: every anonymous user starts
    # without an InterestProfile.
    from digest.profiles import create_anonymous_user

    user = create_anonymous_user(db_session)
    client = _client(db_session)

    response = client.get(f"/dashboard/personal?user_id={user.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["has_profile"] is False
    assert body["topics"] == []
    assert body["blurb"] is None


def test_dashboard_personal_404s_for_an_unknown_user(db_session):
    client = _client(db_session)

    assert client.get(f"/dashboard/personal?user_id={uuid.uuid4()}").status_code == 404


def test_dashboard_personal_422s_for_a_malformed_user_id(db_session):
    client = _client(db_session)

    assert client.get("/dashboard/personal?user_id=not-a-uuid").status_code == 422


def test_post_interests_creates_and_is_idempotent(db_session, monkeypatch):
    from digest.profiles import create_anonymous_user
    from evidence_engine.db.models import Topic

    def fake_get_or_create_topic(session, free_text):
        from sqlalchemy import select as _select

        existing = session.execute(
            _select(Topic).where(Topic.canonical_label == free_text)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        topic = Topic(canonical_label=free_text)
        session.add(topic)
        session.flush()
        return topic

    monkeypatch.setattr("digest.profiles.get_or_create_topic", fake_get_or_create_topic)
    user = create_anonymous_user(db_session)
    client = _client(db_session)

    first = client.post("/interests", json={"user_id": str(user.id), "free_text": "sepsis"})
    assert first.status_code == 201
    assert first.json()["created"] is True

    second = client.post("/interests", json={"user_id": str(user.id), "free_text": "sepsis"})
    assert second.status_code == 200
    assert second.json()["created"] is False


def test_post_interests_422s_on_empty_text(db_session):
    from digest.profiles import create_anonymous_user

    user = create_anonymous_user(db_session)
    client = _client(db_session)

    response = client.post("/interests", json={"user_id": str(user.id), "free_text": "  "})

    assert response.status_code == 422


def test_post_interests_404s_for_an_unknown_user(db_session):
    client = _client(db_session)

    response = client.post(
        "/interests", json={"user_id": str(uuid.uuid4()), "free_text": "sepsis"}
    )

    assert response.status_code == 404


def test_post_interests_429s_when_rate_limited(db_session, monkeypatch):
    # 429, not 422: the request is well-formed and will succeed later. Sending 422 would
    # tell the client its input was wrong and invite it to retry immediately.
    from dashboard.interests import RateLimitExceeded

    def raising(*args, **kwargs):
        raise RateLimitExceeded("too many")

    monkeypatch.setattr("webapp.api.add_user_interest", raising)
    client = _client(db_session)

    response = client.post(
        "/interests", json={"user_id": str(uuid.uuid4()), "free_text": "sepsis"}
    )

    assert response.status_code == 429


def test_delete_interests_returns_204_then_404(db_session, monkeypatch):
    from digest.profiles import create_anonymous_user
    from evidence_engine.db.models import Topic

    def fake_get_or_create_topic(session, free_text):
        topic = Topic(canonical_label=free_text)
        session.add(topic)
        session.flush()
        return topic

    monkeypatch.setattr("digest.profiles.get_or_create_topic", fake_get_or_create_topic)
    user = create_anonymous_user(db_session)
    client = _client(db_session)
    topic_id = client.post(
        "/interests", json={"user_id": str(user.id), "free_text": "removable"}
    ).json()["topic"]["id"]

    assert client.delete(f"/interests/{topic_id}?user_id={user.id}").status_code == 204
    # Not idempotent on repeat, matching DELETE /saved-searches/{id}.
    assert client.delete(f"/interests/{topic_id}?user_id={user.id}").status_code == 404


def test_dashboard_routes_do_not_shadow_the_static_mount(db_session):
    # The StaticFiles mount catches every unmatched path, so a route declared after it is
    # unreachable. This asserts the file's structure, which no functional test would catch.
    import inspect

    import webapp.api as api_module

    source = inspect.getsource(api_module)
    mount_at = source.index('app.mount("/"')
    for route in ["/dashboard/activity", "/dashboard/changes", "/dashboard/personal"]:
        assert source.index(route) < mount_at, f"{route} is declared after the static mount"
