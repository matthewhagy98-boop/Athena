from anthropic import Anthropic

from evidence_engine.config import get_settings


def get_anthropic_client() -> Anthropic:
    return Anthropic(api_key=get_settings().anthropic_api_key)
