from evidence_engine.db.models import Paper, StudyType
from evidence_engine.llm.client import call_forced_tool

PUBLICATION_TYPE_MAP = {
    "Meta-Analysis": StudyType.META_ANALYSIS,
    "Systematic Review": StudyType.SYSTEMATIC_REVIEW,
    "Randomized Controlled Trial": StudyType.RCT,
    "Case Reports": StudyType.CASE_SERIES,
    "Editorial": StudyType.OPINION_EDITORIAL,
    "Comment": StudyType.OPINION_EDITORIAL,
}

CLASSIFY_TOOL = {
    "name": "classify_study",
    "description": "Classify the study type of a biomedical paper based on its title and abstract.",
    "input_schema": {
        "type": "object",
        "properties": {
            "study_type": {
                "type": "string",
                "enum": [t.value for t in StudyType if t != StudyType.UNKNOWN],
            }
        },
        "required": ["study_type"],
    },
}


def classify_study_type(paper: Paper) -> StudyType:
    for pub_type in paper.publication_types:
        if pub_type in PUBLICATION_TYPE_MAP:
            return PUBLICATION_TYPE_MAP[pub_type]

    if not paper.abstract:
        return StudyType.UNKNOWN

    prompt = f"Title: {paper.title}\n\nAbstract: {paper.abstract}"
    result = call_forced_tool(prompt, CLASSIFY_TOOL, max_tokens=100)

    if result and result.get("study_type"):
        try:
            return StudyType(result["study_type"])
        except ValueError:
            return StudyType.UNKNOWN
    return StudyType.UNKNOWN
