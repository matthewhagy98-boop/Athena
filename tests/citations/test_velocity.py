from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from citations.models import CitationSnapshot, CitationVelocityCache
from citations.velocity import compute_velocity, recompute_all
from evidence_engine.db.models import Paper, PaperTopic, Topic

BASE = datetime(2026, 6, 28)


def _snap(day, count, anomalous=False):
    moment = BASE + timedelta(days=day)
    return CitationSnapshot(
        observed_at=moment,
        observed_on=moment.date(),
        citation_count=count,
        is_anomalous=anomalous,
    )


def test_velocity_worked_example_returns_24():
    # Spec 14.1 worked example: 104 -> 132 over 35 days = 28/35*30 = 24.00
    snapshots = [
        _snap(0, 104),
        _snap(7, 109),
        _snap(14, 112),
        _snap(21, 121),
        _snap(28, 126),
        _snap(35, 132),
    ]

    result = compute_velocity(snapshots)

    assert result.status == "ready"
    assert result.velocity_per_30d == Decimal("24.00")
    assert result.observation_count == 6
    assert result.window_start_observed_at == BASE
    assert result.window_end_observed_at == BASE + timedelta(days=35)


def test_velocity_requires_fourteen_day_span():
    result = compute_velocity([_snap(0, 100), _snap(10, 140)])

    assert result.status == "insufficient_history"
    assert result.velocity_per_30d is None
    assert result.observation_count == 2


def test_single_observation_is_insufficient():
    result = compute_velocity([_snap(0, 100)])

    assert result.status == "insufficient_history"
    assert result.velocity_per_30d is None
    assert result.first_observed_at == BASE


def test_no_observations_is_insufficient():
    result = compute_velocity([])

    assert result.status == "insufficient_history"
    assert result.observation_count == 0
    assert result.first_observed_at is None


def test_exactly_fourteen_days_qualifies():
    # The threshold is inclusive: >= 14 days, not > 14.
    result = compute_velocity([_snap(0, 100), _snap(14, 114)])

    assert result.status == "ready"
    assert result.velocity_per_30d == Decimal("30.00")  # 14/14*30


def test_anomalous_transition_excluded_from_pair_selection():
    # A provider merge drops the count at day 20; the only valid pair is post-merge.
    snapshots = [_snap(0, 240), _snap(20, 190, anomalous=True), _snap(40, 210)]

    result = compute_velocity(snapshots)

    assert result.status == "ready"
    assert result.window_start_observed_at == BASE + timedelta(days=20)
    assert result.velocity_per_30d == Decimal("30.00")  # (210-190)/20*30
    assert result.anomaly_count == 1


def test_lookback_is_capped_at_ninety_days():
    snapshots = [_snap(0, 0), _snap(100, 200), _snap(120, 260)]

    result = compute_velocity(snapshots)

    # Most recent end is day 120; the widest start within 90 days is day 100, not day 0.
    assert result.window_start_observed_at == BASE + timedelta(days=100)
    assert result.velocity_per_30d == Decimal("90.00")  # (260-200)/20*30


def test_merge_and_recovery_does_not_produce_phantom_velocity():
    # A merge (240 -> 190) reverted by a later recovery (190 -> 240) is zero real
    # growth. If the recovery snapshot were left unflagged, the (190 -> 240) pair
    # would read as (50/20*30) = 75.00/30d out of thin air. With both the drop and
    # the recovery flagged anomalous (citations/refresh.py's phantom-recovery
    # detection), every candidate pair spans an anomaly and none qualifies.
    snapshots = [_snap(0, 240), _snap(20, 190, anomalous=True), _snap(40, 240, anomalous=True)]

    result = compute_velocity(snapshots)

    assert result.status == "insufficient_history"
    assert result.velocity_per_30d is None


def test_unsorted_input_is_handled():
    # Snapshots arrive in arbitrary order from the DB; the function must sort them.
    result = compute_velocity([_snap(35, 132), _snap(0, 104), _snap(14, 112)])

    assert result.status == "ready"
    assert result.velocity_per_30d == Decimal("24.00")


def _make_paper_with_series(db_session, topic, title, start, end, pub_date=date(2026, 1, 1)):
    paper = Paper(title=title, pub_date=pub_date)
    db_session.add(paper)
    db_session.flush()
    if topic is not None:
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    for day, count in ((0, start), (30, end)):
        moment = datetime(2026, 6, 1) + timedelta(days=day)
        db_session.add(
            CitationSnapshot(
                paper_id=paper.id,
                observed_at=moment,
                observed_on=moment.date(),
                citation_count=count,
            )
        )
    db_session.flush()
    return paper


def test_recompute_assigns_percentile_from_cohort(db_session):
    topic = Topic(canonical_label="Velocity topic", mesh_id="D_VEL_1")
    db_session.add(topic)
    db_session.flush()

    for i in range(30):
        _make_paper_with_series(db_session, topic, f"Slow paper {i}", 0, 1)
    fast = _make_paper_with_series(db_session, topic, "Fast paper", 0, 100)

    recompute_all(db_session)

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == fast.id)
    ).scalar_one()
    assert cache.status == "ready"
    assert cache.cohort_size == 31
    # clamp(round(100*30/31)) = clamp(97) = 97
    assert cache.percentile == 97


def test_percentile_is_clamped_to_99_not_100(db_session):
    # Even the fastest paper in a cohort must not read as 100th percentile.
    topic = Topic(canonical_label="Clamp topic", mesh_id="D_VEL_3")
    db_session.add(topic)
    db_session.flush()
    for i in range(200):
        _make_paper_with_series(db_session, topic, f"Zero paper {i}", 0, 0)
    fastest = _make_paper_with_series(db_session, topic, "Fastest", 0, 5000)

    recompute_all(db_session)

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == fastest.id)
    ).scalar_one()
    assert cache.percentile == 99


def test_percentile_omitted_for_small_cohort(db_session):
    topic = Topic(canonical_label="Tiny cohort", mesh_id="D_VEL_2")
    db_session.add(topic)
    db_session.flush()
    paper = _make_paper_with_series(db_session, topic, "Lonely paper", 10, 40)

    recompute_all(db_session)

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == paper.id)
    ).scalar_one()
    assert cache.status == "ready"
    assert cache.percentile is None
    assert cache.cohort_size == 1


def test_paper_without_pub_date_gets_velocity_but_no_percentile(db_session):
    paper = _make_paper_with_series(db_session, None, "Undated paper", 5, 35, pub_date=None)

    recompute_all(db_session)

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == paper.id)
    ).scalar_one()
    assert cache.status == "ready"
    assert cache.velocity_per_30d == Decimal("30.00")
    assert cache.percentile is None
    assert cache.cohort_key is None


def test_recompute_is_idempotent(db_session):
    topic = Topic(canonical_label="Idempotent topic", mesh_id="D_VEL_4")
    db_session.add(topic)
    db_session.flush()
    paper = _make_paper_with_series(db_session, topic, "Repeat paper", 10, 40)

    recompute_all(db_session)
    recompute_all(db_session)

    caches = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == paper.id)
    ).scalars().all()
    assert len(caches) == 1
    assert caches[0].velocity_per_30d == Decimal("30.00")


def test_cohort_key_is_stable_for_multi_topic_paper(db_session):
    # A paper linked to several topics must land in the same cohort on every run --
    # otherwise its percentile could jump between recomputes with no data change.
    topics = [Topic(canonical_label=f"Multi topic {i}", mesh_id=f"D_MULTI_{i}") for i in range(3)]
    db_session.add_all(topics)
    db_session.flush()

    paper = _make_paper_with_series(db_session, None, "Multi-topic paper", 0, 10, pub_date=date(2026, 1, 1))
    for topic in topics:
        db_session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    db_session.flush()

    recompute_all(db_session)
    first_key = (
        db_session.execute(
            select(CitationVelocityCache).where(CitationVelocityCache.paper_id == paper.id)
        )
        .scalar_one()
        .cohort_key
    )

    recompute_all(db_session)
    second_key = (
        db_session.execute(
            select(CitationVelocityCache).where(CitationVelocityCache.paper_id == paper.id)
        )
        .scalar_one()
        .cohort_key
    )

    assert first_key == second_key
    # The deterministic pick is always the lowest topic_id, regardless of insert order.
    assert first_key == f"{min(t.id for t in topics)}:2024"


def test_percentile_omitted_at_cohort_size_nine(db_session):
    # MIN_COHORT_SIZE is 10. A cohort of exactly 9 ready papers must get no
    # percentiles at all; adding a 10th ready paper must switch every member on.
    topic = Topic(canonical_label="Nine cohort", mesh_id="D_VEL_NINE")
    db_session.add(topic)
    db_session.flush()
    papers = [
        _make_paper_with_series(db_session, topic, f"Nine {i}", 0, i + 1)
        for i in range(9)
    ]

    recompute_all(db_session)

    caches = [
        db_session.execute(
            select(CitationVelocityCache).where(CitationVelocityCache.paper_id == p.id)
        ).scalar_one()
        for p in papers
    ]
    assert all(c.status == "ready" for c in caches)
    assert all(c.cohort_size == 9 for c in caches)
    assert all(c.percentile is None for c in caches)

    tenth = _make_paper_with_series(db_session, topic, "Tenth", 0, 100)
    papers.append(tenth)

    recompute_all(db_session)

    caches = [
        db_session.execute(
            select(CitationVelocityCache).where(CitationVelocityCache.paper_id == p.id)
        ).scalar_one()
        for p in papers
    ]
    assert all(c.cohort_size == 10 for c in caches)
    assert all(c.percentile is not None for c in caches)


def test_percentile_worked_example_returns_88(db_session):
    # Spec 14.2 worked example: a cohort of 34 ready papers where exactly 30 have a
    # velocity strictly below the target's. round(100*30/34) = round(88.235...) = 88.
    topic = Topic(canonical_label="Worked example cohort", mesh_id="D_VEL_88")
    db_session.add(topic)
    db_session.flush()

    for i in range(1, 31):
        _make_paper_with_series(db_session, topic, f"Below {i}", 0, i)
    target = _make_paper_with_series(db_session, topic, "Target", 0, 100)
    for i in range(3):
        _make_paper_with_series(db_session, topic, f"Above {i}", 0, 101 + i)

    recompute_all(db_session)

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == target.id)
    ).scalar_one()
    assert cache.cohort_size == 34
    assert cache.percentile == 88


def test_percentile_clamped_to_1_for_bottom_paper(db_session):
    # The strictly slowest paper in a cohort of 10 must read 1, never 0.
    topic = Topic(canonical_label="Bottom clamp cohort", mesh_id="D_VEL_BOTTOM")
    db_session.add(topic)
    db_session.flush()
    papers = [
        _make_paper_with_series(db_session, topic, f"Ranked {i}", 0, i + 1)
        for i in range(10)
    ]
    slowest = papers[0]  # velocity 1, strictly below every other paper's velocity.

    recompute_all(db_session)

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == slowest.id)
    ).scalar_one()
    assert cache.percentile == 1


def test_cohort_bands_are_fixed_not_sliding(db_session):
    # BAND_WIDTH_YEARS=4, anchored on years divisible by 4: 2024-2027 is one band,
    # 2020-2023 is the previous one. This pins both the width and the anchoring.
    topic = Topic(canonical_label="Band topic", mesh_id="D_VEL_BAND")
    db_session.add(topic)
    db_session.flush()
    papers = {
        year: _make_paper_with_series(
            db_session, topic, f"Paper {year}", 0, 10, pub_date=date(year, 6, 1)
        )
        for year in (2023, 2024, 2025, 2026, 2027)
    }

    recompute_all(db_session)

    keys = {
        year: db_session.execute(
            select(CitationVelocityCache).where(CitationVelocityCache.paper_id == papers[year].id)
        )
        .scalar_one()
        .cohort_key
        for year in papers
    }
    assert keys[2024] == keys[2025] == keys[2026] == keys[2027] == f"{topic.id}:2024"
    assert keys[2023] == f"{topic.id}:2020"
    assert keys[2023] != keys[2024]


def test_shrinking_cohort_does_not_leave_a_stale_percentile(db_session):
    # A paper that drops out of a large cohort must lose its percentile, not keep
    # a value computed when the cohort was big enough.
    topic = Topic(canonical_label="Shrink topic", mesh_id="D_VEL_5")
    db_session.add(topic)
    db_session.flush()
    papers = [_make_paper_with_series(db_session, topic, f"P{i}", 0, i + 1) for i in range(12)]
    recompute_all(db_session)

    target = papers[0]
    assert (
        db_session.execute(
            select(CitationVelocityCache).where(CitationVelocityCache.paper_id == target.id)
        ).scalar_one().percentile
        is not None
    )

    # Remove enough snapshots that the cohort falls under the minimum of 10.
    for paper in papers[1:]:
        for snap in db_session.execute(
            select(CitationSnapshot).where(CitationSnapshot.paper_id == paper.id)
        ).scalars().all():
            db_session.delete(snap)
    db_session.flush()

    recompute_all(db_session)

    cache = db_session.execute(
        select(CitationVelocityCache).where(CitationVelocityCache.paper_id == target.id)
    ).scalar_one()
    assert cache.percentile is None
