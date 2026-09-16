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


def test_duplicate_strength_ranking_indices_are_collapsed():
    # validate_response de-duplicates the ranking, but nothing exercised it: deleting the
    # dedup was the one mutation the original test list did not catch. A ranking is an
    # ordering of members, so a repeated index is malformed and must not appear twice.
    result = validate_response(_raw(strength_ranking=[1, 0, 1, 0]), member_count=2)

    assert result.strength_ranking == [1, 0]


def test_boolean_citations_do_not_count_as_grounding():
    # bool is a subclass of int, so a JSON `true` would slip through an isinstance(v, int)
    # check as index 1. The claim would then count as cited, and the whole point of the
    # density floor is that an ungrounded claim must not.
    raw = _raw(claims=[{"text": "Ungrounded.", "citations": [True]}])

    result = validate_response(raw, member_count=2)

    assert result.ok is False
    assert result.failure_reason == "citation_density"


def test_claims_present_but_all_malformed_is_no_valid_claims():
    # The third and last route to no_valid_claims, and the only one that was untested.
    # It is not redundant with the empty-list case: this list is non-empty, so the
    # earlier guard passes and execution reaches the post-filter check. Delete that
    # check and this input divides by zero at `cited / len(claims)` -- an unhandled
    # exception surfacing in the request path instead of a controlled rejection.
    raw = _raw(claims=[{"citations": [0]}, "not a dict", {"text": "   "}])

    result = validate_response(raw, member_count=2)

    assert result.ok is False
    assert result.failure_reason == "no_valid_claims"
    assert result.narrative is None


def test_non_string_narrative_is_rejected():
    # The blank-narrative test exercises only the `.strip()` half of the guard, and
    # narrative=None does not reach the isinstance half either -- `not None` is already
    # True. The value has to be truthy AND not a string: without isinstance, 123 passes
    # the truthiness check and then raises AttributeError on .strip().
    assert validate_response(_raw(narrative=None), member_count=2).failure_reason == "no_valid_claims"

    result = validate_response(_raw(narrative=123), member_count=2)

    assert result.ok is False
    assert result.failure_reason == "no_valid_claims"


def test_missing_or_non_list_claims_is_rejected():
    # Same shape. claims=[] and claims="nope" are both caught downstream regardless --
    # a string iterates into characters, none of which are dicts, so the all-malformed
    # guard rejects it either way. Only a truthy non-iterable distinguishes the
    # isinstance check: without it, `for entry in 5` raises TypeError.
    assert validate_response({"narrative": "n"}, member_count=2).failure_reason == "no_valid_claims"
    assert (
        validate_response({"narrative": "n", "claims": "nope"}, member_count=2).failure_reason
        == "no_valid_claims"
    )

    result = validate_response({"narrative": "n", "claims": 5}, member_count=2)

    assert result.ok is False
    assert result.failure_reason == "no_valid_claims"


def test_disagreement_with_a_blank_description_is_dropped():
    # Index validity was tested; the description half of the same guard was not.
    raw = _raw(
        disagreements=[
            {"indices": [0, 1], "description": "   "},
            {"indices": [0, 1], "description": None},
            {"indices": [0, 1], "description": "kept"},
        ]
    )

    result = validate_response(raw, member_count=2)

    assert [d["description"] for d in result.disagreements] == ["kept"]


def test_a_passing_response_carries_every_survivor_field_through():
    # Coverage was split one field per test, so nothing pinned that a single successful
    # validation returns all of them together. Task 5 persists this whole object.
    raw = _raw(
        narrative="  Both agree.  ",
        claims=[{"text": "  Consistent.  ", "citations": [0, 1]}],
        disagreements=[{"indices": [0, 1], "description": "  Sample sizes differ.  "}],
        strength_ranking=[1, 0],
    )

    result = validate_response(raw, member_count=2)

    assert result.ok is True
    assert result.failure_reason is None
    assert result.narrative == "Both agree."  # surrounding whitespace stripped
    assert result.claims == [{"text": "Consistent.", "citations": [0, 1]}]
    assert result.disagreements == [{"indices": [0, 1], "description": "Sample sizes differ."}]
    assert result.strength_ranking == [1, 0]


def test_a_non_list_citations_value_is_treated_as_no_citations():
    # _valid_indices' list guard had no test: deleting it passed the whole file, because
    # every input in the suite already supplied a list. A model returning a bare integer
    # for a list-typed field would raise TypeError on iteration instead of being treated
    # as ungrounded.
    raw = _raw(claims=[{"text": "Grounded?", "citations": 5}])

    result = validate_response(raw, member_count=2)

    assert result.ok is False
    assert result.failure_reason == "citation_density"


def test_a_disagreement_naming_more_than_two_members_is_dropped():
    # The index-count guard was only ever tested on the "too few" side, so changing
    # `!= 2` to `< 2` passed every test -- silently admitting a three-member entry into
    # a field whose whole contract is that a disagreement names exactly two studies.
    raw = _raw(
        disagreements=[
            {"indices": [0, 1, 2], "description": "three members"},
            {"indices": [0, 1], "description": "kept"},
        ]
    )

    result = validate_response(raw, member_count=3)

    assert [d["description"] for d in result.disagreements] == ["kept"]


def test_a_claim_citing_both_clean_and_retracted_work_is_stripped():
    # The central judgement call of the retraction rule, and it had no test: `any` could
    # be narrowed to `all` and all 106 tests still passed. The two readings differ only
    # for a claim citing a valid member AND a retracted one, with enough clean claims
    # alongside that density survives either way.
    #
    # The literal spec reading -- any citation to retracted work disqualifies the claim --
    # is kept deliberately. The alternative, stripping just the retracted index and keeping
    # the claim, would let "Both studies found X" survive citing only one study: a false
    # statement wearing a valid-looking citation, which is worse than saying nothing.
    raw = _raw(
        claims=[
            {"text": "Clean one.", "citations": [0]},
            {"text": "Clean two.", "citations": [0]},
            {"text": "Leans partly on the retraction.", "citations": [0, 2]},
        ]
    )

    result = validate_response(raw, member_count=3, retracted_indices=[2])

    # Density is 2/3 either way, so `ok` cannot distinguish the readings -- the surviving
    # claim texts are what does.
    assert result.ok is True
    assert [c["text"] for c in result.claims] == ["Clean one.", "Clean two."]


def test_strength_ranking_naming_only_an_unscored_member_is_dropped():
    # The permutation check compares sets, and nothing pinned that: replacing it with a
    # length comparison passed everything, because the only existing test's ranking
    # differed in length as well as membership. This one has the same cardinality as the
    # expected set and the wrong members.
    raw = _raw(strength_ranking=[1])

    result = validate_response(raw, member_count=2, scored_indices=[0])

    assert result.strength_ranking == []
