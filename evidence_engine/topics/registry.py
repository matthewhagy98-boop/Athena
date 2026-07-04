from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import Topic
from evidence_engine.topics.mesh import resolve_to_mesh


def get_or_create_topic(session: Session, free_text: str) -> Topic:
    resolution = resolve_to_mesh(free_text)
    if resolution is None:
        raise ValueError(f"Could not resolve '{free_text}' to a MeSH term")

    existing = session.execute(
        select(Topic).where(Topic.mesh_id == resolution.mesh_id)
    ).scalar_one_or_none()

    if existing:
        if free_text not in existing.aliases:
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
