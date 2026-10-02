from unittest.mock import patch

from evidence_engine.db.models import Topic
from evidence_engine.topics.mesh import MeshResolution
from evidence_engine.topics.registry import get_or_create_topic


def test_get_or_create_topic_creates_new_topic(db_session):
    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="68009203", canonical_label="Myocardial Infarction"),
    ):
        topic = get_or_create_topic(db_session, "heart attack")

    assert topic.mesh_id == "68009203"
    assert topic.canonical_label == "Myocardial Infarction"
    assert "heart attack" in topic.aliases


def test_get_or_create_topic_reuses_existing_topic_by_mesh_id(db_session):
    existing = Topic(mesh_id="68009203", canonical_label="Myocardial Infarction", aliases=["heart attack"])
    db_session.add(existing)
    db_session.flush()

    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="68009203", canonical_label="Myocardial Infarction"),
    ):
        topic = get_or_create_topic(db_session, "myocardial infarction")

    assert topic.id == existing.id
    assert "myocardial infarction" in topic.aliases


def test_get_or_create_topic_raises_when_unresolvable(db_session):
    with patch("evidence_engine.topics.registry.resolve_to_mesh", return_value=None):
        try:
            get_or_create_topic(db_session, "not a real term")
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_aliases_are_capped(db_session, monkeypatch):
    """`aliases` was the one unbounded, caller-supplied, shared-row growth point
    reachable from an unauthenticated endpoint.

    POST /interests resolves free text through get_or_create_topic, so every accepted add
    appended up to MAX_FREE_TEXT = 200 characters to a Topic row shared by everyone
    interested in that topic. The rate limit is keyed per user_id and POST /users/anonymous
    mints identities on demand, so the effective cap on appends was none at all.
    """
    from evidence_engine.topics.mesh import MeshResolution
    from evidence_engine.topics.registry import MAX_ALIASES, get_or_create_topic

    monkeypatch.setattr(
        "evidence_engine.topics.registry.resolve_to_mesh",
        lambda text: MeshResolution(mesh_id="D_CAP", canonical_label="Capped topic"),
    )

    for index in range(MAX_ALIASES + 25):
        topic = get_or_create_topic(db_session, f"spelling number {index}")

    assert len(topic.aliases) == MAX_ALIASES, (
        f"aliases grew to {len(topic.aliases)}; the cap is not holding"
    )


def test_aliases_dedupe_ignoring_case_and_whitespace(db_session, monkeypatch):
    """The old check was an exact `not in`, so "Sepsis", "sepsis" and "sepsis " each
    earned their own entry -- the same shared field growing three times faster than it
    needs to, for no added recognisability."""
    from evidence_engine.topics.mesh import MeshResolution
    from evidence_engine.topics.registry import get_or_create_topic

    monkeypatch.setattr(
        "evidence_engine.topics.registry.resolve_to_mesh",
        lambda text: MeshResolution(mesh_id="D_DEDUPE", canonical_label="Dedupe topic"),
    )

    get_or_create_topic(db_session, "Sepsis")
    for variant in ("sepsis", "SEPSIS", "  sepsis  ", "sepsis"):
        topic = get_or_create_topic(db_session, variant)

    assert topic.aliases == ["Sepsis"], f"got {topic.aliases}"
