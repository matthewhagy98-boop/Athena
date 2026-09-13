from synthesis.generate import generate_synthesis
from synthesis.prompt import MemberInput, build_prompt

MEMBERS = [
    MemberInput("First study", "established", "meta_analysis", "Long abstract.", False),
    MemberInput("Second study", "emerging", "rct", None, True),
]


def test_prompt_indexes_members_and_marks_retractions():
    prompt = build_prompt(MEMBERS)

    assert "[0] First study" in prompt
    assert "[1] Second study [RETRACTED]" in prompt
    assert "(no abstract available)" in prompt


def test_prompt_truncates_long_abstracts():
    long_member = MemberInput("Long", "emerging", "rct", "x" * 5000, False)

    prompt = build_prompt([long_member])

    assert "x" * 1200 in prompt
    assert "x" * 1201 not in prompt


def test_prompt_forbids_outside_sources():
    prompt = build_prompt(MEMBERS)

    assert "Use ONLY the studies listed below" in prompt
    assert "Do not state or imply causation" in prompt


def test_generate_returns_validated_result():
    def fake_call(prompt, tool, max_tokens):
        return {
            "narrative": "They agree.",
            "claims": [{"text": "Consistent effect.", "citations": [0, 1]}],
            "disagreements": [],
            "strength_ranking": [0, 1],
        }

    result, latency_ms = generate_synthesis(MEMBERS, call=fake_call)

    assert result.ok is True
    assert result.narrative == "They agree."
    assert latency_ms >= 0


def test_generate_reports_llm_unavailable_when_call_returns_none():
    result, _ = generate_synthesis(MEMBERS, call=lambda *a, **k: None)

    assert result.ok is False
    assert result.failure_reason == "llm_unavailable"


def test_generate_rejects_ungrounded_response():
    def fake_call(prompt, tool, max_tokens):
        return {
            "narrative": "Sweeping claim.",
            "claims": [{"text": "Uncited.", "citations": []}],
            "disagreements": [],
            "strength_ranking": [],
        }

    result, _ = generate_synthesis(MEMBERS, call=fake_call)

    assert result.ok is False
    assert result.failure_reason == "citation_density"


def test_generate_passes_member_count_to_validator():
    # Index 5 does not exist in a 2-member set and must be dropped.
    def fake_call(prompt, tool, max_tokens):
        return {
            "narrative": "Text.",
            "claims": [{"text": "Claim.", "citations": [0, 5]}],
            "disagreements": [],
            "strength_ranking": [],
        }

    result, _ = generate_synthesis(MEMBERS, call=fake_call)

    assert result.claims[0]["citations"] == [0]


def test_generate_does_not_propagate_an_exception_from_the_model_call():
    # The load-bearing property of this function: it sits in a request path, so a
    # transport failure beneath call_forced_tool must become a failed ValidationResult,
    # not an exception. The None-returning test above does not reach this path --
    # removing the try/except leaves it passing.
    def exploding(prompt, tool, max_tokens):
        raise ConnectionError("socket closed")

    result, latency_ms = generate_synthesis(MEMBERS, call=exploding)

    assert result.ok is False
    assert result.failure_reason == "llm_unavailable"
    assert result.narrative is None
    assert latency_ms >= 0


def test_generate_measures_elapsed_time_rather_than_reporting_a_constant():
    # `latency_ms >= 0` is satisfied by `return 0`, and Task 5 persists this value as
    # cost telemetry. Pin that it actually tracks the call's duration.
    import time

    def slow(prompt, tool, max_tokens):
        time.sleep(0.05)
        return {
            "narrative": "They agree.",
            "claims": [{"text": "Consistent.", "citations": [0]}],
            "disagreements": [],
            "strength_ranking": [],
        }

    _, latency_ms = generate_synthesis(MEMBERS, call=slow)

    assert latency_ms >= 50


def test_generate_passes_the_tool_schema_and_token_cap_to_the_call():
    # Every other fake here accepts (prompt, tool, max_tokens) and ignores the last two,
    # so nothing pinned what was actually sent: swapping the arguments to
    # call(prompt, MAX_TOKENS, SYNTHESIS_TOOL) passed the whole file. Forced-tool use is
    # what makes the response structured at all -- send the wrong object and the model
    # is unconstrained, which is precisely what validation.py exists to compensate for.
    from synthesis.generate import MAX_TOKENS
    from synthesis.prompt import SYNTHESIS_TOOL

    seen = {}

    def recording(prompt, tool, max_tokens):
        seen["prompt"] = prompt
        seen["tool"] = tool
        seen["max_tokens"] = max_tokens
        return {
            "narrative": "They agree.",
            "claims": [{"text": "Consistent.", "citations": [0]}],
            "disagreements": [],
            "strength_ranking": [],
        }

    generate_synthesis(MEMBERS, call=recording)

    assert seen["tool"] is SYNTHESIS_TOOL
    assert seen["max_tokens"] == MAX_TOKENS
    assert "First study" in seen["prompt"]
