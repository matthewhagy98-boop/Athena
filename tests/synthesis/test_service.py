from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from evidence_engine.db.models import EvidenceTier, Paper, Score, StudyType
from synthesis.models import ComparisonSynthesis, SynthesisGeneration
from synthesis.service import get_or_create_synthesis
from synthesis.validation import ValidationResult


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr("synthesis.service._synthesis_enabled", lambda: True)


def _paper(db_session, title, retracted=False):
    paper = Paper(title=title, abstract=f"Abstract for {title}.", is_retracted=retracted)
    db_session.add(paper)
    db_session.flush()
    db_session.add(
        Score(
            paper_id=paper.id,
            evidence_tier=EvidenceTier.ESTABLISHED,
            study_type=StudyType.RCT,
            final_score=80.0,
            model_version="v1",
        )
    )
    db_session.flush()
    return paper


def _ok(**overrides):
    base = dict(
        ok=True,
        narrative="They agree.",
        claims=[{"text": "Consistent.", "citations": [0]}],
        disagreements=[],
        strength_ranking=[0, 1],
    )
    base.update(overrides)
    return lambda members, call=None: (ValidationResult(**base), 100)


def test_generates_and_persists_a_ready_synthesis(db_session):
    p1, p2 = _paper(db_session, "One"), _paper(db_session, "Two")

    row = get_or_create_synthesis(db_session, "paper", [p1.id, p2.id], generate=_ok())

    assert row.status == "ready"
    assert row.narrative == "They agree."
    assert sorted(row.subject_ids) == sorted([p1.id, p2.id])
    assert row.superseded_at is None


def test_reuses_the_cached_row_without_regenerating(db_session):
    p1, p2 = _paper(db_session, "A"), _paper(db_session, "B")
    calls = []

    def counting(members, call=None):
        calls.append(1)
        return (ValidationResult(ok=True, narrative="n", claims=[{"text": "c", "citations": [0]}]), 10)

    get_or_create_synthesis(db_session, "paper", [p1.id, p2.id], generate=counting)
    get_or_create_synthesis(db_session, "paper", [p1.id, p2.id], generate=counting)

    assert len(calls) == 1


def test_member_order_does_not_produce_a_second_row(db_session):
    p1, p2 = _paper(db_session, "C"), _paper(db_session, "D")

    get_or_create_synthesis(db_session, "paper", [p1.id, p2.id], generate=_ok())
    get_or_create_synthesis(db_session, "paper", [p2.id, p1.id], generate=_ok())

    rows = db_session.execute(select(ComparisonSynthesis)).scalars().all()
    assert len(rows) == 1


def test_score_change_supersedes_and_regenerates(db_session):
    p1, p2 = _paper(db_session, "E"), _paper(db_session, "F")
    first = get_or_create_synthesis(db_session, "paper", [p1.id, p2.id], generate=_ok())

    score = db_session.execute(select(Score).where(Score.paper_id == p1.id)).scalar_one()
    score.final_score = 42.0
    db_session.flush()

    second = get_or_create_synthesis(db_session, "paper", [p1.id, p2.id], generate=_ok())

    assert second.id != first.id
    db_session.refresh(first)
    assert first.superseded_at is not None


def test_pending_score_produces_the_same_fingerprint_as_no_score_at_all(db_session):
    # Score rows are created with is_pending=True before scoring completes, carrying
    # column defaults (evidence_tier='speculative', final_score=0.0). _score_for must
    # treat that exactly like "no Score row" -- otherwise removing the pending row
    # entirely would look like a real input change and trigger a needless regenerate.
    paper = Paper(title="Pending", abstract="Abstract for Pending.", is_retracted=False)
    db_session.add(paper)
    db_session.flush()
    db_session.add(Score(paper_id=paper.id, is_pending=True, model_version="v1"))
    db_session.flush()

    calls = []

    def counting(members, call=None):
        calls.append(1)
        return (ValidationResult(ok=True, narrative="n", claims=[{"text": "c", "citations": [0]}]), 10)

    first = get_or_create_synthesis(db_session, "paper", [paper.id], generate=counting)

    # Remove the pending Score row entirely. If the pending row's defaults had leaked
    # into the fingerprint, this would look like a real input change.
    pending = db_session.execute(select(Score).where(Score.paper_id == paper.id)).scalar_one()
    db_session.delete(pending)
    db_session.flush()

    second = get_or_create_synthesis(db_session, "paper", [paper.id], generate=counting)

    assert len(calls) == 1  # no regeneration: the fingerprint did not change
    assert second.id == first.id


def test_failed_generation_sets_cooldown_and_is_not_retried_immediately(db_session):
    p1 = _paper(db_session, "G")
    calls = []

    def failing(members, call=None):
        calls.append(1)
        return (ValidationResult(ok=False, failure_reason="citation_density"), 50)

    first = get_or_create_synthesis(db_session, "paper", [p1.id], generate=failing)
    assert first.status == "failed"
    assert first.cooldown_until is not None

    get_or_create_synthesis(db_session, "paper", [p1.id], generate=failing)
    assert len(calls) == 1  # still cooling down


def test_retries_after_cooldown_expires(db_session):
    p1 = _paper(db_session, "H")
    calls = []

    def failing(members, call=None):
        calls.append(1)
        return (ValidationResult(ok=False, failure_reason="llm_unavailable"), 50)

    get_or_create_synthesis(db_session, "paper", [p1.id], generate=failing, now=datetime(2026, 8, 2, 9, 0))
    get_or_create_synthesis(db_session, "paper", [p1.id], generate=failing, now=datetime(2026, 8, 2, 11, 0))

    assert len(calls) == 2


def test_records_retracted_member_indices(db_session):
    good = _paper(db_session, "Clean")
    bad = _paper(db_session, "Retracted paper", retracted=True)

    ids = sorted([good.id, bad.id], key=str)
    row = get_or_create_synthesis(db_session, "paper", ids, generate=_ok())

    assert row.retracted_member_indices == [ids.index(bad.id)]


def test_writes_a_generation_telemetry_row(db_session):
    p1 = _paper(db_session, "Telemetry")

    get_or_create_synthesis(db_session, "paper", [p1.id], generate=_ok())

    gen = db_session.execute(select(SynthesisGeneration)).scalars().one()
    assert gen.outcome == "ready"
    assert gen.member_count == 1
    assert gen.latency_ms == 100


def test_returns_none_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr("synthesis.service._synthesis_enabled", lambda: False)
    p1 = _paper(db_session, "Disabled")

    assert get_or_create_synthesis(db_session, "paper", [p1.id], generate=_ok()) is None


def test_unknown_member_id_raises_value_error(db_session):
    import uuid

    with pytest.raises(ValueError, match="not found"):
        get_or_create_synthesis(db_session, "paper", [uuid.uuid4()], generate=_ok())


def test_member_ordering_is_canonical_regardless_of_request_order(db_session):
    # _load_papers sorts members by str(uuid), and that sort is load-bearing for
    # citation correctness -- not redundant with compute_cache_key's own internal sort.
    #
    # Because the cache key ignores order, a request listing the same papers in a
    # different order is a cache HIT. So whichever order generated the row gets frozen
    # into the narrative: claim citations are indices into subject_ids, and the Compare
    # panel resolves them through that list (see the 2026-09-12 decision in the plan).
    # Drop the sort and the second user's citations point at the wrong studies while
    # every other test in this file still passes.
    #
    # Requesting in reverse-sorted order is what makes this deterministic; asserting
    # against the request order would pass half the time on random UUIDs.
    p1, p2 = _paper(db_session, "Zeta"), _paper(db_session, "Alpha")
    ids = sorted([p1.id, p2.id], key=str)

    row = get_or_create_synthesis(db_session, "paper", list(reversed(ids)), generate=_ok())

    assert row.subject_ids == ids
