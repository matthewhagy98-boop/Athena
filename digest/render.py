from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from digest.compose import ComposedDigest

TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))


@dataclass
class RenderedDigest:
    subject: str
    html_body: str
    text_body: str


def _subject_for(composed: ComposedDigest) -> str:
    count = len(composed.sections)
    noun = "topic" if count == 1 else "topics"
    return f"Your weekly research digest: {count} {noun} updated"


def render_digest(composed: ComposedDigest, user_email: str) -> RenderedDigest:
    html_template = _env.get_template("digest_email.html.jinja2")
    text_template = _env.get_template("digest_email.txt.jinja2")

    return RenderedDigest(
        subject=_subject_for(composed),
        html_body=html_template.render(sections=composed.sections),
        text_body=text_template.render(sections=composed.sections),
    )
