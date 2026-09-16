import time

from evidence_engine.llm.client import call_forced_tool
from synthesis.prompt import SYNTHESIS_TOOL, MemberInput, build_prompt
from synthesis.validation import ValidationResult, validate_response

MAX_TOKENS = 1500


def generate_synthesis(members: list[MemberInput], call=None) -> tuple[ValidationResult, int]:
    """Call the model once and validate the response. Never raises on model failure."""
    call = call or call_forced_tool
    prompt = build_prompt(members)

    started = time.monotonic()
    try:
        raw = call(prompt, SYNTHESIS_TOOL, MAX_TOKENS)
    except Exception:
        # call_forced_tool already swallows provider errors and returns None, but a
        # transport failure below it must not propagate into the request path.
        raw = None
    latency_ms = int((time.monotonic() - started) * 1000)

    # The validator enforces two spec post-conditions that need member state: claims
    # citing a retracted study are stripped, and strength_ranking must be a permutation of
    # the SCORED members (FR-B-004 -- ranking by methodological strength is meaningless for
    # a paper with no study type). `tier` is None exactly when the member has no usable
    # Score, which is what _score_for already decided.
    retracted_indices = [i for i, m in enumerate(members) if m.is_retracted]
    scored_indices = [i for i, m in enumerate(members) if m.tier is not None]

    return (
        validate_response(
            raw,
            member_count=len(members),
            retracted_indices=retracted_indices,
            scored_indices=scored_indices,
        ),
        latency_ms,
    )
