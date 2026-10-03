import uuid
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from digest.profiles import create_user
from evidence_engine.db.models import ChangeEvent, ChangeEventType, EvidenceTier, Paper, PaperTopic, Score, StudyType, Topic
from sqlalchemy import delete, select

from webapp.api import app, get_db
from webapp.search_index import sync_search_index


@pytest.fixture(autouse=True)
def _dashboard_enabled(monkeypatch):
    """Every dashboard/interests test in this file predates Task 10's gate and was
    written against the feature always being on. Enabling it by default here, the same
    way tests/synthesis/test_service.py's autouse fixture patches _synthesis_enabled,
    keeps them all exercising real behavior; the handful of tests below that care about
    the disabled case patch this back to False themselves.
    """
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: True)


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

    # Both ends of both ranges. The original pinned days at 0/31/30 but only the UPPER
    # end of limit, so an off-by-one on its lower bound passed -- confirmed by mutation.
    # The activity endpoint's test pins all four; this one now matches.
    assert client.get("/dashboard/changes?days=0").status_code == 422
    assert client.get("/dashboard/changes?days=1").status_code == 200
    assert client.get("/dashboard/changes?days=30").status_code == 200
    assert client.get("/dashboard/changes?days=31").status_code == 422

    assert client.get("/dashboard/changes?limit=0").status_code == 422
    assert client.get("/dashboard/changes?limit=1").status_code == 200
    assert client.get("/dashboard/changes?limit=50").status_code == 200
    assert client.get("/dashboard/changes?limit=51").status_code == 422


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


def test_dashboard_personal_404s_for_an_unknown_user(db_session, monkeypatch):
    # Force the gate ON. With DASHBOARD_ENABLED off this route now returns 404
    # too, so without this the test would pass on the GATE's 404 and assert
    # nothing about the unknown-user path it is named for.
    monkeypatch.setattr("webapp.api.dashboard_flags.dashboard_enabled", lambda: True)
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


def test_post_interests_404s_for_an_unknown_user(db_session, monkeypatch):
    # Force the gate ON. With DASHBOARD_ENABLED off this route now returns 404
    # too, so without this the test would pass on the GATE's 404 and assert
    # nothing about the unknown-user path it is named for.
    monkeypatch.setattr("webapp.api.dashboard_flags.dashboard_enabled", lambda: True)
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

    # All five routes, not three. The two /interests routes were missing from this loop,
    # which is the one place they most needed covering: when frontend/dist does not exist
    # the mount is never registered, nothing can be shadowed, and every functional test
    # passes regardless of declaration order -- so in that environment this check is the
    # only guard, and it was silently skipping them.
    source = inspect.getsource(api_module)
    mount_at = source.index('app.mount("/"')
    for route in [
        "/dashboard/activity",
        "/dashboard/changes",
        "/dashboard/personal",
        '"/interests"',
        "/interests/{topic_id}",
        # Task 10: /features is a new route added after this test was written, and it
        # belongs in the same guard as everything else declared before the mount.
        '"/features"',
    ]:
        assert source.index(route) < mount_at, f"{route} is declared after the static mount"


def test_dashboard_personal_returns_a_blurb_for_a_user_with_interests(db_session):
    """The endpoint computes the blurb, and only the null case was asserted.

    It is computed server-side rather than in the client so the copy rules live in one
    tested place. Dropping that line left every endpoint test passing -- the dashboard
    would simply have shown no blurb, silently.
    """
    from datetime import timedelta

    from digest.models import InterestProfile, ProfileTopic
    from digest.profiles import create_anonymous_user
    from evidence_engine.db.models import ChangeEvent, ChangeEventType, Topic

    user = create_anonymous_user(db_session)
    topic = Topic(canonical_label="Atrial fibrillation")
    db_session.add(topic)
    db_session.flush()
    profile = InterestProfile(user_id=user.id)
    db_session.add(profile)
    db_session.flush()
    db_session.add(ProfileTopic(profile_id=profile.id, topic_id=topic.id))
    for _ in range(3):
        db_session.add(
            ChangeEvent(
                topic_id=topic.id,
                event_type=ChangeEventType.NEW_PAPER,
                detected_at=datetime.utcnow() - timedelta(days=1),
            )
        )
    db_session.flush()

    body = _client(db_session).get(f"/dashboard/personal?user_id={user.id}").json()

    assert body["has_profile"] is True
    assert body["blurb"], "the endpoint returned no blurb for a user with interests"
    assert "3 new papers" in body["blurb"]
    assert "this week" in body["blurb"]


def test_dashboard_personal_rejects_an_out_of_range_days(db_session):
    # This endpoint's bound check had zero coverage: every other /dashboard/personal test
    # omits `days` entirely, so deleting the check or shifting either bound passed the
    # whole suite. Its two sibling endpoints already pin all four of their boundaries.
    from digest.profiles import create_anonymous_user

    user = create_anonymous_user(db_session)
    client = _client(db_session)

    assert client.get(f"/dashboard/personal?user_id={user.id}&days=0").status_code == 422
    assert client.get(f"/dashboard/personal?user_id={user.id}&days=1").status_code == 200
    assert client.get(f"/dashboard/personal?user_id={user.id}&days=30").status_code == 200
    assert client.get(f"/dashboard/personal?user_id={user.id}&days=31").status_code == 422


def test_post_interests_rejects_a_malformed_user_id(db_session):
    """The UUID guard had no test, and its absence would not have been obvious.

    Deleting the try/except entirely still passed every existing test, because
    SQLAlchemy's session.get(User, ...) accepts a well-formed UUID *string*
    transparently -- so the guard only shows its value for input that is not a UUID at
    all, which nothing supplied. All three shapes belong here: a missing key, a
    non-string, and a string that is not a UUID.
    """
    client = _client(db_session)

    assert client.post("/interests", json={"free_text": "sepsis"}).status_code == 422
    assert client.post(
        "/interests", json={"user_id": 12345, "free_text": "sepsis"}
    ).status_code == 422
    assert client.post(
        "/interests", json={"user_id": "not-a-uuid", "free_text": "sepsis"}
    ).status_code == 422


# --- Task 10: DASHBOARD_ENABLED gating -------------------------------------------


def test_dashboard_activity_returns_404_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    assert client.get("/dashboard/activity").status_code == 404


def test_dashboard_activity_gate_precedes_parameter_validation(db_session, monkeypatch):
    # limit=0 is out of range and would 422 on its own. With the flag off it must still
    # be 503, not 422 -- the brief calls out "two different answers to 'is this
    # available'" as exactly the failure mode of checking the flag second.
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    assert client.get("/dashboard/activity?limit=0").status_code == 404


# Inputs FastAPI itself rejects, before any handler body runs. These are the ONLY inputs
# that can tell a route-level gate from an in-body one, and every case below leaks
# parameter names, locations and types to a caller who cannot use them.
#
# The four `gate_precedes_*` tests above cannot do this job, because every value they
# send is one FastAPI accepts: the range checks on `limit` and `days` live in the handler
# bodies, not in `Query(ge=..., le=...)`, so `limit=0` parses fine as an int and an
# in-body gate would answer 404 too. Reverting the five route-level dependencies to
# in-body calls left the whole suite green at 57 passed -- the branch's headline fix,
# which took two review passes to find, was completely unguarded.
_VALIDATION_REJECTED_BEFORE_ANY_HANDLER_RUNS = [
    ("GET", "/dashboard/activity?limit=notanint", "query int parse"),
    ("GET", "/dashboard/changes?days=abc", "query int parse"),
    ("GET", "/dashboard/personal", "required query param missing"),
    ("GET", "/dashboard/personal?user_id=not-a-uuid", "query uuid parse"),
    ("DELETE", "/interests/NOTAUUID?user_id=alsobad", "path uuid parse"),
]


@pytest.mark.parametrize(
    "method,url,rejected_by", _VALIDATION_REJECTED_BEFORE_ANY_HANDLER_RUNS
)
def test_gate_precedes_fastapis_own_validation(db_session, monkeypatch, method, url, rejected_by):
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    response = client.request(method, url)

    assert response.status_code == 404, (
        f"{rejected_by} leaked {response.status_code}: {response.text[:200]}"
    )
    # Not just the status: a 404 carrying a validation body would still disclose the
    # contract. Must be byte-identical to Starlette's own not-found.
    assert response.json() == {"detail": "Not Found"}


def test_dashboard_changes_returns_404_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    assert client.get("/dashboard/changes").status_code == 404


def test_dashboard_changes_gate_precedes_parameter_validation(db_session, monkeypatch):
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    assert client.get("/dashboard/changes?days=0").status_code == 404
    assert client.get("/dashboard/changes?limit=0").status_code == 404


def test_dashboard_personal_returns_404_when_disabled(db_session, monkeypatch):
    from digest.profiles import create_anonymous_user

    user = create_anonymous_user(db_session)
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    assert client.get(f"/dashboard/personal?user_id={user.id}").status_code == 404


def test_dashboard_personal_gate_precedes_parameter_and_user_validation(db_session, monkeypatch):
    # Both an out-of-range `days` and an unknown user_id would otherwise 422/404. With
    # the flag off, neither of those checks should even run.
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    assert client.get(f"/dashboard/personal?user_id={uuid.uuid4()}&days=999").status_code == 404


def test_post_interests_returns_404_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    response = client.post(
        "/interests", json={"user_id": str(uuid.uuid4()), "free_text": "sepsis"}
    )

    assert response.status_code == 404


def test_post_interests_gate_precedes_input_validation(db_session, monkeypatch):
    # Empty free_text and a malformed user_id would otherwise 422. With the flag off, a
    # disabled endpoint must not leak its input contract to a caller who cannot use it.
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    assert client.post(
        "/interests", json={"user_id": str(uuid.uuid4()), "free_text": "  "}
    ).status_code == 404
    assert client.post(
        "/interests", json={"user_id": "not-a-uuid", "free_text": "sepsis"}
    ).status_code == 404


def test_delete_interests_returns_404_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    response = client.delete(f"/interests/{uuid.uuid4()}?user_id={uuid.uuid4()}")

    assert response.status_code == 404


def test_features_endpoint_reports_both_states(db_session, monkeypatch):
    client = _client(db_session)

    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: True)
    assert client.get("/features").json() == {"dashboard_enabled": True}

    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    assert client.get("/features").json() == {"dashboard_enabled": False}


def test_features_endpoint_is_not_gated(db_session, monkeypatch):
    # A client must be able to ask whether the feature is on even while it is off --
    # gating this endpoint on itself would make it useless for exactly the case it
    # exists to serve.
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    assert client.get("/features").status_code == 200


def test_a_failed_add_still_charges_quota_through_the_real_get_db(db_session, monkeypatch):
    """The gap every other quota test had: nothing exercised `get_db`'s rollback.

    `_client()` above overrides `get_db` with a generator that neither commits nor rolls
    back, and `tests/dashboard/test_interests.py` calls `add_user_interest` directly on a
    session it never rolls back either. So no test in the suite ran the real dependency's
    `except Exception: session.rollback()` -- and with the charge on the request session,
    that rollback discarded it.

    The effect was that the counter recorded *successful* adds only. The 422 path, which
    has already paid for the outbound PubMed term resolution, was free and unlimited on
    an unauthenticated endpoint -- so the rate limit did not work on the one path it
    exists to cap. Verified before the fix: five failing adds left zero rows.

    This test therefore deliberately uses the real `get_db` and its own committed user,
    because the bug lives entirely in the commit/rollback behaviour that the override
    hides.
    """
    from digest.models import User
    from digest.profiles import create_anonymous_user
    from evidence_engine.db.session import SessionLocal

    from dashboard.models import DashboardRateWindow

    # The real dependency, not _client's override. monkeypatch restores whatever was
    # there, so a later test in this file still gets its override back.
    monkeypatch.delitem(app.dependency_overrides, get_db, raising=False)

    setup = SessionLocal()
    user = create_anonymous_user(setup)
    setup.commit()
    user_id = str(user.id)
    setup.close()

    def unresolvable(session, free_text):
        raise ValueError("could not resolve term")

    monkeypatch.setattr("digest.profiles.get_or_create_topic", unresolvable)

    try:
        client = TestClient(app)
        codes = [
            client.post("/interests", json={"user_id": user_id, "free_text": f"zz{i}"}).status_code
            for i in range(3)
        ]
        assert codes == [422, 422, 422]

        check = SessionLocal()
        charged = check.execute(
            select(DashboardRateWindow.request_count).where(
                DashboardRateWindow.subject == f"user:{user_id}"
            )
        ).scalar_one_or_none()
        check.close()

        assert charged == 3, (
            f"three failed adds charged {charged} instead of 3 -- each one reached the "
            "provider, so each one must cost its slot"
        )
    finally:
        cleanup = SessionLocal()
        cleanup.execute(
            delete(DashboardRateWindow).where(DashboardRateWindow.subject == f"user:{user_id}")
        )
        cleanup.execute(delete(User).where(User.id == uuid.UUID(user_id)))
        cleanup.commit()
        cleanup.close()


def test_a_malformed_body_does_not_leak_a_parse_error_when_disabled(db_session, monkeypatch):
    """The last hole in the gate, and the one a route-level dependency cannot close.

    FastAPI reads and JSON-decodes a declared body before it solves dependencies, so
    `POST /interests` with a malformed body answered 422 with the full json_invalid
    detail while every other probe returned 404. Since an unrouted path answers 405 from
    the StaticFiles mount, that 422 positively confirmed the route exists -- for the one
    route the spec wants indistinguishable from a deployment that never added it.
    """
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    response = client.post(
        "/interests", content=b"{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_the_openapi_schema_hides_the_gated_routes_when_disabled(db_session, monkeypatch):
    """`/openapi.json` listed all five routes with every parameter name, location, type
    and default while the flag was off -- strictly more disclosure than the 422s the gate
    was written to suppress, and nothing covered it."""
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: False)
    client = _client(db_session)

    paths = client.get("/openapi.json").json()["paths"]

    assert [p for p in paths if p.startswith("/dashboard/") or p.startswith("/interests")] == []
    # /features is never gated: the client has to be able to ask.
    assert "/features" in paths
    # And an ungated route is untouched, so this is a filter and not an empty schema.
    assert "/topics" in paths


def test_the_openapi_schema_lists_the_gated_routes_when_enabled(db_session, monkeypatch):
    """The other half: a filter that hid them unconditionally would also pass the test
    above, and would break the API docs for everyone once the feature ships."""
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: True)
    client = _client(db_session)

    paths = client.get("/openapi.json").json()["paths"]

    assert sorted(p for p in paths if p.startswith("/dashboard/") or p.startswith("/interests")) == [
        "/dashboard/activity",
        "/dashboard/changes",
        "/dashboard/personal",
        "/interests",
        "/interests/{topic_id}",
    ]


def test_normal_validation_is_unaffected_when_enabled(db_session, monkeypatch):
    """The gate moved in front of request parsing; with the flag ON, parsing and
    validation must behave exactly as before. A middleware that swallowed requests in
    both states would pass every disabled-case test in this file."""
    monkeypatch.setattr("dashboard.flags.dashboard_enabled", lambda: True)
    client = _client(db_session)

    assert client.post(
        "/interests", content=b"{not json", headers={"Content-Type": "application/json"}
    ).status_code == 422
    assert client.get("/dashboard/activity?limit=notanint").status_code == 422
    assert client.get("/dashboard/activity?limit=0").status_code == 422
