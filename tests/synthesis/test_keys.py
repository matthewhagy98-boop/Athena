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
    a = [MemberState(ID_A, None, 91.40000000000001, "established", False)]
    b = [MemberState(ID_A, None, 91.4, "established", False)]
    assert compute_inputs_fingerprint(a) == compute_inputs_fingerprint(b)


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
