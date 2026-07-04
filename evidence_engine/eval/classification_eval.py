import json
from dataclasses import dataclass

from evidence_engine.db.models import Paper, StudyType
from evidence_engine.scoring.classifier import classify_study_type


@dataclass
class EvalResult:
    accuracy: float
    mismatches: list[dict]


def run_classification_eval(golden_set_path: str) -> EvalResult:
    with open(golden_set_path, encoding="utf-8") as f:
        cases = json.load(f)

    mismatches = []
    correct = 0
    for case in cases:
        paper = Paper(
            title=case["title"],
            abstract=case["abstract"],
            publication_types=case["publication_types"],
        )
        predicted = classify_study_type(paper)
        expected = StudyType(case["expected_study_type"])
        if predicted == expected:
            correct += 1
        else:
            mismatches.append({"title": case["title"], "expected": expected.value, "predicted": predicted.value})

    accuracy = correct / len(cases) if cases else 0.0
    return EvalResult(accuracy=accuracy, mismatches=mismatches)
