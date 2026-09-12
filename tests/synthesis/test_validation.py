from synthesis.validation import validate_response


def _raw(**overrides):
    base = {
        "narrative": "Both studies point the same way.",
        "claims": [
            {"text": "Effect is consistent.", "citations": [0, 1]},
            {"text": "Sample sizes differ.", "citations": [1]},
        ],
        "disagreements": [],
        "strength_ranking": [1, 0],
    }
    base.update(overrides)
    return base


def test_valid_response_passes():
    result = validate_response(_raw(), member_count=2)

    assert result.ok is True
    assert result.failure_reason is None
    assert len(result.claims) == 2


def test_none_response_is_llm_unavailable():
    result = validate_response(None, member_count=2)

    assert result.ok is False
    assert result.failure_reason == "llm_unavailable"
    assert result.narrative is None


def test_empty_claims_is_no_valid_claims():
    result = validate_response(_raw(claims=[]), member_count=2)

    assert result.ok is False
    assert result.failure_reason == "no_valid_claims"


def test_missing_narrative_is_no_valid_claims():
    result = validate_response(_raw(narrative=""), member_count=2)

    assert result.ok is False
    assert result.failure_reason == "no_valid_claims"


def test_out_of_range_citations_are_dropped():
    raw = _raw(claims=[{"text": "Grounded.", "citations": [0, 7, -1]}])

    result = validate_response(raw, member_count=2)

    assert result.ok is True
    assert result.claims[0]["citations"] == [0]


def test_density_below_threshold_is_rejected():
    # 1 of 3 claims cited = 0.33, below the 0.6 floor.
    raw = _raw(
        claims=[
            {"text": "Cited.", "citations": [0]},
            {"text": "Uncited.", "citations": []},
            {"text": "Also uncited.", "citations": [9]},  # 9 is out of range, so it drops to []
        ]
    )

    result = validate_response(raw, member_count=2)

    assert result.ok is False
    assert result.failure_reason == "citation_density"


def test_density_exactly_at_threshold_passes():
    # 3 of 5 = 0.6, which is allowed (>=, not >).
    raw = _raw(
        claims=[
            {"text": "a", "citations": [0]},
            {"text": "b", "citations": [1]},
            {"text": "c", "citations": [0]},
            {"text": "d", "citations": []},
            {"text": "e", "citations": []},
        ]
    )

    result = validate_response(raw, member_count=2)

    assert result.ok is True


def test_malformed_claim_entries_are_discarded():
    raw = _raw(claims=[{"text": "Good.", "citations": [0]}, "not a dict", {"citations": [1]}])

    result = validate_response(raw, member_count=2)

    # Only the well-formed claim survives; density is 1/1.
    assert result.ok is True
    assert len(result.claims) == 1


def test_strength_ranking_is_filtered_to_valid_indices():
    result = validate_response(_raw(strength_ranking=[1, 0, 5]), member_count=2)

    assert result.strength_ranking == [1, 0]


def test_disagreement_with_bad_indices_is_dropped():
    raw = _raw(disagreements=[{"indices": [0, 1], "description": "ok"}, {"indices": [0, 9], "description": "bad"}])

    result = validate_response(raw, member_count=2)

    assert len(result.disagreements) == 1
    assert result.disagreements[0]["description"] == "ok"
