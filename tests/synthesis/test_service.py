from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from evidence_engine.db.models import EvidenceTier, Paper, Score, StudyType
from synthesis.models import ComparisonSynthesis, SynthesisGeneration
from synthesis.service import COOLDOWN_MINUTES, get_or_create_synthesis
from evidence_engine.config import get_settings
from synthesis.keys import SYNTHESIS_PROMPT_VERSION, compute_cache_key
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


def test_a_failed_result_persists_no_narrative_or_claims(db_session):
    # The binding constraint is that nothing is persisted with a narrative unless the
    # result validated. The guards in get_or_create_synthesis were untested, because
    # ValidationResult's dataclass defaults happen to equal the values they fall back to
    # -- so every failure fixture matched the guard's output and removing the guards
    # passed the whole file. This fixture returns a NOT-ok result that still carries a
    # narrative and claims, which is the only shape that distinguishes them.
    p1 = _paper(db_session, "Leaky")

    def failed_but_populated(members, call=None):
        return (
            ValidationResult(
                ok=False,
                failure_reason="citation_density",
                narrative="Ungrounded prose that must never be stored.",
                claims=[{"text": "Uncited.", "citations": []}],
                disagreements=[{"indices": [0, 1], "description": "d"}],
                strength_ranking=[0],
            ),
            10,
        )

    row = get_or_create_synthesis(db_session, "paper", [p1.id], generate=failed_but_populated)

    assert row.status == "failed"
    assert row.narrative is None
    assert row.claims == []
    assert row.disagreements == []
    assert row.strength_ranking == []


def test_a_ready_row_carries_no_failure_reason_or_cooldown(db_session):
    # The complement: the same guards must not leave failure metadata on a good row, or
    # a later request would treat a ready synthesis as cooling down.
    p1 = _paper(db_session, "Clean")

    row = get_or_create_synthesis(db_session, "paper", [p1.id], generate=_ok())

    assert row.status == "ready"
    assert row.failure_reason is None
    assert row.cooldown_until is None


def test_the_supplied_now_is_what_gets_written(db_session):
    # `now` is injectable so the cooldown tests can control time, but nothing asserted it
    # actually reaches the persisted columns -- substituting datetime.utcnow() for it
    # passed every test.
    p1 = _paper(db_session, "Clock")
    fixed = datetime(2026, 8, 2, 9, 0)

    row = get_or_create_synthesis(db_session, "paper", [p1.id], generate=_ok(), now=fixed)

    assert row.generated_at == fixed


def test_cooldown_is_still_honoured_at_the_exact_expiry_instant(db_session):
    # The check is `cooldown_until > now`, so at exactly cooldown_until it must expire
    # and regenerate. Every other cooldown test uses a two-hour gap against a sixty
    # minute cooldown, so > vs >= was never pinned.
    p1 = _paper(db_session, "Boundary")
    start = datetime(2026, 8, 2, 9, 0)
    calls = []

    def failing(members, call=None):
        calls.append(1)
        return (ValidationResult(ok=False, failure_reason="llm_unavailable"), 50)

    get_or_create_synthesis(db_session, "paper", [p1.id], generate=failing, now=start)
    expiry = start + timedelta(minutes=COOLDOWN_MINUTES)

    get_or_create_synthesis(db_session, "paper", [p1.id], generate=failing, now=expiry)

    assert len(calls) == 2


def test_a_non_paper_subject_type_is_rejected_clearly(db_session):
    p1 = _paper(db_session, "Topicish")

    with pytest.raises(ValueError, match="Unsupported subject_type"):
        get_or_create_synthesis(db_session, "topic", [p1.id], generate=_ok())


def test_losing_the_insert_race_returns_the_winners_row(db_session):
    # Two requests for the same uncached member set both miss the cache lookup, both
    # call the model, and both try to insert under the same cache_key. The partial
    # unique index lets one win; the loser must return the winner's narrative rather
    # than raising IntegrityError up to the endpoint as a 500.
    #
    # generate() runs between the lookup and the insert, so inserting the competitor
    # from inside the fake reproduces the race exactly, without threads.
    p1 = _paper(db_session, "Contended")

    def generate_then_lose_the_race(members, call=None):
        key = compute_cache_key(
            "paper", [p1.id], SYNTHESIS_PROMPT_VERSION, get_settings().anthropic_model
        )
        db_session.add(
            ComparisonSynthesis(
                cache_key=key,
                subject_type="paper",
                subject_ids=[p1.id],
                inputs_fingerprint="winner",
                status="ready",
                narrative="The winner's narrative.",
                claims=[{"text": "Winner.", "citations": [0]}],
                model_id=get_settings().anthropic_model,
                prompt_version=SYNTHESIS_PROMPT_VERSION,
            )
        )
        db_session.flush()
        return (
            ValidationResult(
                ok=True, narrative="The loser's narrative.", claims=[{"text": "Loser.", "citations": [0]}]
            ),
            10,
        )

    row = get_or_create_synthesis(db_session, "paper", [p1.id], generate=generate_then_lose_the_race)

    assert row.narrative == "The winner's narrative."

    # Exactly one active row survives -- the loser's insert was rolled back, not merged.
    active = (
        db_session.execute(
            select(ComparisonSynthesis).where(ComparisonSynthesis.superseded_at.is_(None))
        )
        .scalars()
        .all()
    )
    assert len(active) == 1

    # The model call happened and cost real money, so it is still counted, pointed at
    # the row that actually survived.
    gen = db_session.execute(select(SynthesisGeneration)).scalars().one()
    assert gen.synthesis_id == row.id
