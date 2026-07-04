from unittest.mock import patch

import pytest

from digest.models import DigestFrequency
from digest.profiles import (
    add_interest,
    create_user,
    get_delivery_preference,
    list_interests,
    remove_interest,
    update_delivery_preference,
)
from evidence_engine.topics.mesh import MeshResolution


def test_create_user_also_creates_profile_and_default_preference(db_session):
    user = create_user(db_session, "researcher@example.com")

    preference = get_delivery_preference(db_session, user)
    assert preference.frequency == DigestFrequency.WEEKLY
    assert preference.send_day == 0
    assert preference.last_digest_sent_at is None
    assert list_interests(db_session, user) == []


def test_add_interest_resolves_via_engine_registry_and_is_idempotent(db_session):
    user = create_user(db_session, "researcher2@example.com")

    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="68009203", canonical_label="Myocardial Infarction"),
    ):
        topic_first = add_interest(db_session, user, "heart attack")
        topic_second = add_interest(db_session, user, "heart attack")

    assert topic_first.id == topic_second.id
    interests = list_interests(db_session, user)
    assert len(interests) == 1
    assert interests[0].canonical_label == "Myocardial Infarction"


def test_add_interest_raises_when_unresolvable(db_session):
    user = create_user(db_session, "researcher3@example.com")

    with patch("evidence_engine.topics.registry.resolve_to_mesh", return_value=None):
        with pytest.raises(ValueError):
            add_interest(db_session, user, "not a real term")


def test_remove_interest_removes_topic_from_list(db_session):
    user = create_user(db_session, "researcher4@example.com")

    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="D003924", canonical_label="Diabetes Mellitus, Type 2"),
    ):
        topic = add_interest(db_session, user, "type 2 diabetes")

    remove_interest(db_session, user, topic.id)

    assert list_interests(db_session, user) == []


def test_update_delivery_preference_changes_frequency_and_send_day(db_session):
    user = create_user(db_session, "researcher5@example.com")

    updated = update_delivery_preference(db_session, user, send_day=4)

    assert updated.send_day == 4
    assert updated.frequency == DigestFrequency.WEEKLY
