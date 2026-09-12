import uuid
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from synthesis.models import ComparisonSynthesis, SynthesisGeneration


def _synthesis(**overrides):
    defaults = dict(
        cache_key="a" * 64,
        subject_type="paper",
        subject_ids=[uuid.uuid4()],
        inputs_fingerprint="b" * 64,
        model_id="claude-test",
        prompt_version="v1",
    )
    defaults.update(overrides)
    return ComparisonSynthesis(**defaults)


def test_synthesis_round_trip(db_session):
    row = _synthesis(narrative="Two studies agree.", claims=[{"text": "A", "citations": [0]}])
    db_session.add(row)
    db_session.flush()

    stored = db_session.get(ComparisonSynthesis, row.id)
    assert stored.status == "ready"
    assert stored.claims[0]["citations"] == [0]
    assert stored.disagreements == []
    assert stored.superseded_at is None


def test_active_cache_key_is_unique(db_session):
    db_session.add(_synthesis(cache_key="c" * 64))
    db_session.flush()
    db_session.add(_synthesis(cache_key="c" * 64))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_superseded_rows_do_not_block_a_new_active_row(db_session):
    # The unique index is partial on superseded_at IS NULL, so regeneration is possible.
    db_session.add(_synthesis(cache_key="d" * 64, superseded_at=datetime(2026, 8, 1)))
    db_session.flush()
    db_session.add(_synthesis(cache_key="d" * 64))
    db_session.flush()  # must not raise


def test_failed_synthesis_stores_reason_and_no_narrative(db_session):
    row = _synthesis(status="failed", failure_reason="citation_density", narrative=None)
    db_session.add(row)
    db_session.flush()

    assert row.narrative is None
    assert row.failure_reason == "citation_density"


def test_generation_row_round_trip(db_session):
    gen = SynthesisGeneration(member_count=3, outcome="ready", latency_ms=1200)
    db_session.add(gen)
    db_session.flush()

    assert gen.attempt_count == 1
    assert gen.truncated_member_count == 0
    assert gen.user_id is None
