from digest.compose import ComposedDigest, ComposedTopicSection
from digest.render import render_digest


def test_render_digest_produces_subject_with_topic_count():
    composed = ComposedDigest(
        sections=[
            ComposedTopicSection(topic_label="Myocardial Infarction", narrative="A new meta-analysis strengthens the evidence.", change_count=2),
            ComposedTopicSection(topic_label="Type 2 Diabetes", narrative="A trial was retracted.", change_count=1),
        ]
    )

    rendered = render_digest(composed, "researcher@example.com")

    assert rendered.subject == "Your weekly research digest: 2 topics updated"


def test_render_digest_html_and_text_bodies_include_all_sections():
    composed = ComposedDigest(
        sections=[ComposedTopicSection(topic_label="Myocardial Infarction", narrative="A new meta-analysis strengthens the evidence.", change_count=2)]
    )

    rendered = render_digest(composed, "researcher@example.com")

    assert "Myocardial Infarction" in rendered.html_body
    assert "A new meta-analysis strengthens the evidence." in rendered.html_body
    assert "<html" in rendered.html_body.lower()
    assert "Myocardial Infarction" in rendered.text_body
    assert "A new meta-analysis strengthens the evidence." in rendered.text_body
    assert "<html" not in rendered.text_body.lower()


def test_render_digest_subject_handles_single_topic():
    composed = ComposedDigest(sections=[ComposedTopicSection(topic_label="Solo Topic", narrative="Something changed.", change_count=1)])

    rendered = render_digest(composed, "researcher@example.com")

    assert rendered.subject == "Your weekly research digest: 1 topic updated"


def test_render_digest_html_body_autoescapes_metacharacters():
    """Verify that HTML metacharacters in narrative are escaped in HTML body but not in text body."""
    composed = ComposedDigest(
        sections=[ComposedTopicSection(topic_label="Risk Analysis", narrative="Risk fell by 5% & confidence rose <significantly>", change_count=1)]
    )

    rendered = render_digest(composed, "researcher@example.com")

    # HTML body should escape the & and < characters
    assert "&amp;" in rendered.html_body, "HTML body should escape & as &amp;"
    assert "&lt;" in rendered.html_body, "HTML body should escape < as &lt;"
    # Text body should NOT escape these characters
    assert "&amp;" not in rendered.text_body, "Text body should not escape & as &amp;"
    assert " & " in rendered.text_body, "Text body should contain raw & character"
    assert "<significantly>" in rendered.text_body, "Text body should contain raw < and > characters"


def test_render_digest_multiple_sections_render_in_both_bodies():
    """Verify that all sections render in both HTML and text bodies."""
    composed = ComposedDigest(
        sections=[
            ComposedTopicSection(topic_label="Myocardial Infarction", narrative="A new meta-analysis strengthens the evidence.", change_count=2),
            ComposedTopicSection(topic_label="Type 2 Diabetes", narrative="A trial was retracted.", change_count=1),
            ComposedTopicSection(topic_label="Hypertension", narrative="Treatment guidelines updated substantially.", change_count=3),
        ]
    )

    rendered = render_digest(composed, "researcher@example.com")

    # HTML body should contain content from all 3 sections
    assert "Myocardial Infarction" in rendered.html_body
    assert "A new meta-analysis strengthens the evidence." in rendered.html_body
    assert "Type 2 Diabetes" in rendered.html_body
    assert "A trial was retracted." in rendered.html_body
    assert "Hypertension" in rendered.html_body
    assert "Treatment guidelines updated substantially." in rendered.html_body

    # Text body should contain content from all 3 sections
    assert "Myocardial Infarction" in rendered.text_body
    assert "A new meta-analysis strengthens the evidence." in rendered.text_body
    assert "Type 2 Diabetes" in rendered.text_body
    assert "A trial was retracted." in rendered.text_body
    assert "Hypertension" in rendered.text_body
    assert "Treatment guidelines updated substantially." in rendered.text_body
