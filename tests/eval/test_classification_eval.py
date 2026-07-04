import pytest

from evidence_engine.eval.classification_eval import run_classification_eval


@pytest.mark.eval
def test_classification_golden_set_accuracy_meets_bar():
    result = run_classification_eval("tests/fixtures/golden_set/classification_golden_set.json")
    assert result.accuracy >= 0.8, f"Mismatches: {result.mismatches}"


def test_run_classification_eval_computes_accuracy_and_mismatches_without_llm():
    """Sanity check on the harness's aggregation logic alone.

    Every case in this fixture carries a `publication_types` tag that
    `classify_study_type` resolves directly (see
    `evidence_engine.scoring.classifier.PUBLICATION_TYPE_MAP`), so this never
    falls through to a live Anthropic call and can run in the default
    (non-`eval`) test suite without an API key.
    """
    result = run_classification_eval("tests/fixtures/golden_set/classification_golden_set_tagged_only.json")

    assert result.accuracy == pytest.approx(4 / 5)
    assert result.mismatches == [
        {
            "title": "T5 deliberately wrong expectation",
            "expected": "case_series",
            "predicted": "opinion_editorial",
        }
    ]
