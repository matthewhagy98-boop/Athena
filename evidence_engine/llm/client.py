from typing import Any

from anthropic import Anthropic

from evidence_engine.config import get_settings


def get_anthropic_client() -> Anthropic:
    return Anthropic(api_key=get_settings().anthropic_api_key)


def call_forced_tool(prompt: str, tool: dict, max_tokens: int) -> dict[str, Any] | None:
    client = get_anthropic_client()
    try:
        response = client.messages.create(
            model=get_settings().anthropic_model,
            max_tokens=max_tokens,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return None
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    return None
