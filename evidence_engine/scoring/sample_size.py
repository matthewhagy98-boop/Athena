from evidence_engine.config import get_settings
from evidence_engine.db.models import Paper
from evidence_engine.llm.client import get_anthropic_client

EXTRACT_TOOL = {
    "name": "extract_sample_size",
    "description": "Extract the study's reported sample size (number of participants/subjects) from its abstract.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sample_size_reported": {"type": "boolean"},
            "sample_size": {"type": ["integer", "null"]},
        },
        "required": ["sample_size_reported", "sample_size"],
    },
}


def extract_sample_size(paper: Paper) -> int | None:
    if not paper.abstract:
        return None

    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=100,
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_sample_size"},
        messages=[
            {
                "role": "user",
                "content": f"Title: {paper.title}\n\nAbstract: {paper.abstract}",
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use":
            if block.input.get("sample_size_reported"):
                return block.input.get("sample_size")
            return None
    return None
