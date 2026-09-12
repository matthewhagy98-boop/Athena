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
    return [v for v in values if isinstance(v, int) and 0 <= v < member_count]


def validate_response(raw: dict | None, member_count: int) -> ValidationResult:
    """Structural + grounding validation. Nothing is stored or shown unless this returns ok."""
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

    cited = sum(1 for c in claims if c["citations"])
    if cited / len(claims) < MIN_CITATION_DENSITY:
        return ValidationResult(ok=False, failure_reason="citation_density")

    disagreements = []
    for entry in raw.get("disagreements") or []:
        if not isinstance(entry, dict):
            continue
        indices = _valid_indices(entry.get("indices"), member_count)
        description = entry.get("description")
        # A disagreement names exactly two members; anything else is unusable.
        if len(indices) != 2 or not isinstance(description, str) or not description.strip():
            continue
        disagreements.append({"indices": indices, "description": description.strip()})

    seen: set[int] = set()
    strength_ranking = []
    for idx in _valid_indices(raw.get("strength_ranking"), member_count):
        if idx not in seen:
            seen.add(idx)
            strength_ranking.append(idx)

    return ValidationResult(
        ok=True,
        narrative=narrative.strip(),
        claims=claims,
        disagreements=disagreements,
        strength_ranking=strength_ranking,
    )
