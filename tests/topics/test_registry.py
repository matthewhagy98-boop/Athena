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
