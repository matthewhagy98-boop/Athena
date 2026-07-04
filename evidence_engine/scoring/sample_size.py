from evidence_engine.db.models import Paper
from evidence_engine.llm.client import call_forced_tool

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

    prompt = f"Title: {paper.title}\n\nAbstract: {paper.abstract}"
    result = call_forced_tool(prompt, EXTRACT_TOOL, max_tokens=100)

    if result:
        if result.get("sample_size_reported"):
            return result.get("sample_size")
        return None
    return None
