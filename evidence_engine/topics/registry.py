from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import Topic
from evidence_engine.topics.mesh import resolve_to_mesh


MAX_ALIASES: int = 50
"""How many alias strings one topic row may accumulate.

`aliases` is the one unbounded, caller-supplied, shared-row growth point reachable from
an unauthenticated endpoint. `POST /interests` (sub-project C) resolves free text through
here, so every accepted add could append up to MAX_FREE_TEXT = 200 characters to a Topic
row shared by every user interested in that topic. The rate limit is keyed on
`user:{uuid}` and `POST /users/anonymous` mints identities on demand, so the effective
limit on appends was 30 per minted identity -- which is to say none.

The array is also loaded whole on every call and deduplicated by a linear scan, so an
overgrown one makes this function progressively slower for everybody.

A cap rather than a different data structure: aliases exist to help a human recognise
what a topic was searched as, and fifty spellings is already far more than that needs.
Hitting the cap drops the new alias silently -- it is a convenience field, and failing an
interest add because a topic is popular would be the worse outcome.
"""


def _alias_key(value: str) -> str:
    """Comparison form for dedup: case- and whitespace-insensitive.

    The previous check was `free_text not in existing.aliases`, an exact match, so
    "Sepsis", "sepsis" and "sepsis " each earned their own entry. That is the same field
    growing three times faster than it needs to for no added recognisability.
    """
    return " ".join(value.split()).casefold()


def get_or_create_topic(session: Session, free_text: str) -> Topic:
    resolution = resolve_to_mesh(free_text)
    if resolution is None:
        raise ValueError(f"Could not resolve '{free_text}' to a MeSH term")

    existing = session.execute(
        select(Topic).where(Topic.mesh_id == resolution.mesh_id)
    ).scalar_one_or_none()

    if existing:
        known = {_alias_key(alias) for alias in existing.aliases}
        if _alias_key(free_text) not in known and len(existing.aliases) < MAX_ALIASES:
            existing.aliases = [*existing.aliases, free_text]
        return existing

    topic = Topic(
        mesh_id=resolution.mesh_id,
        canonical_label=resolution.canonical_label,
        aliases=[free_text],
        status="active",
    )
    session.add(topic)
    session.flush()
    return topic
