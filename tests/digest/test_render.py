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
