from collections.abc import Iterable
from dataclasses import dataclass, field

# At least 60% of surviving claims must carry a resolvable citation, or the whole
# synthesis is rejected. An ungrounded narrative is worse than no narrative.
MIN_CITATION_DENSITY = 0.6


@dataclass
class ValidationResult:
    ok: bool
    failure_reason: str | None = None
    narrative: str | None = None
    claims: list[dict] = field(default_factory=list)
    disagreements: list[dict] = field(default_factory=list)
    strength_ranking: list[int] = field(default_factory=list)


def _valid_indices(values, member_count: int) -> list[int]:
    if not isinstance(values, list):
        return []
    # bool is a subclass of int, so a JSON `true` would otherwise pass as index 1. That
    # is not a pedantic case here: a claim citing [true] would count as cited, inflating
    # citation density and admitting exactly the ungrounded narrative this module exists
    # to reject -- then rendering as a citation to a study the claim never referenced.
    return [
        v
        for v in values
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < member_count
    ]


def validate_response(
    raw: dict | None,
    member_count: int,
    *,
    retracted_indices: "Iterable[int]" = (),
    scored_indices: "Iterable[int] | None" = None,
) -> ValidationResult:
    """Structural + grounding validation. Nothing is stored or shown unless this returns ok.

    Implements spec 14.3's post-conditions in order: filter citation indices to range,
    drop claims left with zero citations, strip claims citing a retracted index, density
    check, verify strength_ranking is a permutation of the scored member indices, verify
    each disagreement names exactly two in-range distinct members.

    `scored_indices` defaults to None meaning "every member is scored"; FR-B-004 requires
    a member with no Score row to be excluded from strength_ranking.
    """
    if raw is None:
        return ValidationResult(ok=False, failure_reason="llm_unavailable")

    narrative = raw.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        return ValidationResult(ok=False, failure_reason="no_valid_claims")

    raw_claims = raw.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        return ValidationResult(ok=False, failure_reason="no_valid_claims")

    claims: list[dict] = []
    for entry in raw_claims:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        claims.append({"text": text.strip(), "citations": _valid_indices(entry.get("citations"), member_count)})

    if not claims:
        return ValidationResult(ok=False, failure_reason="no_valid_claims")

    # The denominator is every well-formed claim the model produced. What follows drops
    # claims from the OUTPUT, so computing density afterwards would make it trivially 1.0
    # -- density measures how much of what the model asserted survived grounding.
    claimed = len(claims)

    # Post-condition: drop claims left with zero citations. Previously these were kept and
    # merely counted as uncited, so the panel rendered them with no citation bracket --
    # an ungrounded assertion presented alongside grounded ones, which is the single thing
    # this module exists to prevent.
    grounded = [c for c in claims if c["citations"]]

    # Post-condition: strip claims citing a retracted index. Read literally, per spec: any
    # citation to retracted work disqualifies the claim, not only claims resting entirely
    # on it. A claim part-grounded in a retraction is still telling a researcher that
    # retracted work supports it.
    retracted = {i for i in retracted_indices}
    surviving = [c for c in grounded if not any(i in retracted for i in c["citations"])]

    # No early return when `surviving` is empty: that is a density of 0.0, which is a
    # grounding failure, not a structural one. Reporting no_valid_claims there would say
    # the model returned nothing usable when in fact it returned claims and none of them
    # were grounded -- a different diagnosis, and the one an operator would act on.
    if len(surviving) / claimed < MIN_CITATION_DENSITY:
        return ValidationResult(ok=False, failure_reason="citation_density")

    claims = surviving

    disagreements = []
    for entry in raw.get("disagreements") or []:
        if not isinstance(entry, dict):
            continue
        indices = _valid_indices(entry.get("indices"), member_count)
        description = entry.get("description")
        # A disagreement names exactly two members; anything else is unusable.
        # Distinct, per spec: a study cannot disagree with itself, and [1, 1] would
        # render as a conflict between one card and the same card.
        if (
            len(indices) != 2
            or indices[0] == indices[1]
            or not isinstance(description, str)
            or not description.strip()
        ):
            continue
        disagreements.append({"indices": indices, "description": description.strip()})

    seen: set[int] = set()
    strength_ranking = []
    for idx in _valid_indices(raw.get("strength_ranking"), member_count):
        if idx not in seen:
            seen.add(idx)
            strength_ranking.append(idx)

    # Post-condition: strength_ranking must be a permutation of the scored members, and is
    # dropped to [] rather than failing the whole synthesis. A partial ranking would be
    # read as "these are the strongest" when it is really "these are the ones the model
    # happened to list", and FR-B-004 excludes unscored members outright -- ranking a
    # paper by methodological strength requires knowing its study type.
    expected = set(range(member_count)) if scored_indices is None else set(scored_indices)
    if set(strength_ranking) != expected:
        strength_ranking = []

    return ValidationResult(
        ok=True,
        narrative=narrative.strip(),
        claims=claims,
        disagreements=disagreements,
        strength_ranking=strength_ranking,
    )
