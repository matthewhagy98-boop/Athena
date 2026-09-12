import uuid
from datetime import datetime

from synthesis.keys import (
    SYNTHESIS_PROMPT_VERSION,
    MemberState,
    compute_cache_key,
    compute_inputs_fingerprint,
)

ID_A = uuid.UUID("3f2a0000-0000-0000-0000-000000000001")
ID_B = uuid.UUID("7e1b0000-0000-0000-0000-000000000002")


def test_cache_key_is_order_independent():
    a = compute_cache_key("paper", [ID_A, ID_B], SYNTHESIS_PROMPT_VERSION, "m1")
    b = compute_cache_key("paper", [ID_B, ID_A], SYNTHESIS_PROMPT_VERSION, "m1")
    assert a == b


def test_cache_key_changes_with_prompt_version():
    a = compute_cache_key("paper", [ID_A], "v1", "m1")
    b = compute_cache_key("paper", [ID_A], "v2", "m1")
    assert a != b


def test_cache_key_changes_with_model():
    a = compute_cache_key("paper", [ID_A], "v1", "m1")
    b = compute_cache_key("paper", [ID_A], "v1", "m2")
    assert a != b


def test_cache_key_distinguishes_papers_from_topics():
    assert compute_cache_key("paper", [ID_A], "v1", "m1") != compute_cache_key("topic", [ID_A], "v1", "m1")


def test_cache_key_is_64_hex_chars():
    key = compute_cache_key("paper", [ID_A], "v1", "m1")
    assert len(key) == 64 and key == key.lower()


def test_fingerprint_changes_when_member_score_changes():
    base = [MemberState(ID_A, datetime(2026, 7, 30, 4, 0), 91.4, "established", False)]
    changed = [MemberState(ID_A, datetime(2026, 7, 30, 4, 0), 93.1, "established", False)]
    assert compute_inputs_fingerprint(base) != compute_inputs_fingerprint(changed)


def test_fingerprint_stable_across_float_repr():
    # Rounded to 1 decimal before hashing, so float noise cannot invalidate a cache entry.
    #
    # The noisy value must be produced by arithmetic, not written as a literal. The
    # literal this test originally used -- 91.40000000000001 -- parses to the *same
    # float64* as 91.4, so the two sides were identical before hashing and the test
    # passed whether or not the rounding existed. `91.3 + 0.1` is a genuinely distinct
    # double: it renders as "91.39999999999999", so without round(..., 1) the two
    # fingerprints differ and this fails.
    noisy = 91.3 + 0.1
    assert noisy != 91.4, "the noise value must differ as a float, or this proves nothing"

    a = [MemberState(ID_A, None, noisy, "established", False)]
    b = [MemberState(ID_A, None, 91.4, "established", False)]
    assert compute_inputs_fingerprint(a) == compute_inputs_fingerprint(b)


def test_fingerprint_still_changes_on_a_real_one_decimal_difference():
    # The complement of the test above, and the reason it is safe. Rounding is a
    # deliberate loss of precision, so something must pin how much is lost -- otherwise
    # rounding to 0 decimals would satisfy every other fingerprint test here.
    #
    # The pair must differ at 1 decimal AND collapse at 0. 91.4 vs 91.5 does not work:
    # round(91.4, 0) is 91.0 and round(91.5, 0) is 92.0, so those still differ and the
    # mutation survives. 91.4 vs 91.3 both round to 91.0, so this catches it.
    a = [MemberState(ID_A, None, 91.4, "established", False)]
    b = [MemberState(ID_A, None, 91.3, "established", False)]
    assert compute_inputs_fingerprint(a) != compute_inputs_fingerprint(b)


# Each field of MemberState is varied on its own below. Without per-field coverage a
# refactor could drop a field from the hash format string and no test would notice --
# which for scored_at would silently break the staleness guarantee the whole cache
# rests on. test_unscored_member_contributes_none_placeholders varies three fields at
# once, so it cannot stand in for these.


def test_fingerprint_changes_when_only_scored_at_changes():
    a = [MemberState(ID_A, datetime(2026, 7, 30, 4, 0), 91.4, "established", False)]
    b = [MemberState(ID_A, datetime(2026, 8, 1, 4, 0), 91.4, "established", False)]
    assert compute_inputs_fingerprint(a) != compute_inputs_fingerprint(b)


def test_fingerprint_changes_when_only_evidence_tier_changes():
    a = [MemberState(ID_A, None, 91.4, "established", False)]
    b = [MemberState(ID_A, None, 91.4, "emerging", False)]
    assert compute_inputs_fingerprint(a) != compute_inputs_fingerprint(b)


def test_fingerprint_changes_when_only_member_id_changes():
    # Order independence alone proves member_id is *neutral* under reordering, not that
    # it is hashed at all. This pins that it is.
    a = [MemberState(ID_A, None, 91.4, "established", False)]
    b = [MemberState(ID_B, None, 91.4, "established", False)]
    assert compute_inputs_fingerprint(a) != compute_inputs_fingerprint(b)


def test_fingerprint_changes_when_a_member_is_added():
    # Adding a paper to a comparison is a different comparison, and must not reuse the
    # narrative written for the smaller set.
    one = [MemberState(ID_A, None, 91.4, "established", False)]
    two = one + [MemberState(ID_B, None, 12.0, "speculative", False)]
    assert compute_inputs_fingerprint(one) != compute_inputs_fingerprint(two)


def test_fingerprint_changes_when_member_becomes_retracted():
    a = [MemberState(ID_A, None, 50.0, "emerging", False)]
    b = [MemberState(ID_A, None, 50.0, "emerging", True)]
    assert compute_inputs_fingerprint(a) != compute_inputs_fingerprint(b)


def test_unscored_member_contributes_none_placeholders():
    # A member gaining its first score must change the fingerprint.
    unscored = [MemberState(ID_A, None, None, None, False)]
    scored = [MemberState(ID_A, datetime(2026, 8, 1), 10.0, "speculative", False)]
    assert compute_inputs_fingerprint(unscored) != compute_inputs_fingerprint(scored)


def test_fingerprint_is_order_independent():
    m1 = MemberState(ID_A, None, 1.0, "emerging", False)
    m2 = MemberState(ID_B, None, 2.0, "emerging", False)
    assert compute_inputs_fingerprint([m1, m2]) == compute_inputs_fingerprint([m2, m1])
