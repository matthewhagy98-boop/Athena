from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.adapters.base import RawPaper, SourceAdapter
from evidence_engine.adapters.clinicaltrials import ClinicalTrialsAdapter
from evidence_engine.adapters.merge import merge_raw_papers, upsert_paper
from evidence_engine.adapters.pubmed import PubMedAdapter
from evidence_engine.adapters.retractions import recheck_retractions
from evidence_engine.adapters.semantic_scholar import SemanticScholarAdapter
from evidence_engine.consensus.contradiction import detect_contradiction
from evidence_engine.consensus.synthesizer import synthesize_consensus
from evidence_engine.db.models import ChangeEventType, ConsensusSnapshot, Score, Topic
from evidence_engine.orchestrator.change_events import record_change_event
from evidence_engine.scoring.assemble import score_paper

DEFAULT_ADAPTERS: list[SourceAdapter] = [PubMedAdapter(), SemanticScholarAdapter(), ClinicalTrialsAdapter()]


def _latest_consensus(session: Session, topic: Topic) -> ConsensusSnapshot | None:
    return (
        session.execute(
            select(ConsensusSnapshot)
            .where(ConsensusSnapshot.topic_id == topic.id)
            .order_by(ConsensusSnapshot.generated_at.desc())
        )
        .scalars()
        .first()
    )


def run_topic_cycle(
    session: Session,
    topic: Topic,
    model_version: str,
    adapters: list[SourceAdapter] | None = None,
) -> None:
    adapters = adapters if adapters is not None else DEFAULT_ADAPTERS
    since = topic.last_checked_at
    previous_consensus = _latest_consensus(session, topic)

    raw_papers: list[RawPaper] = []
    for adapter in adapters:
        try:
            raw_papers.extend(adapter.fetch_new(topic, since))
        except Exception:
            continue

    merged = merge_raw_papers(raw_papers)
    contradiction_notes: list[str] = []

    for raw_paper in merged:
        paper = upsert_paper(session, topic, raw_paper)
        session.flush()

        try:
            score_paper(session, paper, citation_count=raw_paper.citation_count or 0, model_version=model_version)
        except Exception:
            existing_score = session.execute(select(Score).where(Score.paper_id == paper.id)).scalar_one_or_none()
            pending = existing_score or Score(paper_id=paper.id, model_version=model_version)
            pending.is_pending = True
            if not existing_score:
                session.add(pending)
            session.flush()
            continue

        record_change_event(session, topic, ChangeEventType.NEW_PAPER, paper=paper)

        if previous_consensus and not previous_consensus.is_insufficient_evidence:
            contradiction = detect_contradiction(paper, previous_consensus)
            if contradiction.contradicts:
                record_change_event(session, topic, ChangeEventType.CONTRADICTION_FLAGGED, paper=paper)
                if contradiction.note:
                    contradiction_notes.append(f"{paper.title}: {contradiction.note}")

    for retracted_paper in recheck_retractions(session, topic):
        record_change_event(session, topic, ChangeEventType.PAPER_RETRACTED, paper=retracted_paper)

    new_consensus = synthesize_consensus(session, topic, model_version=model_version)
    if contradiction_notes:
        new_consensus.contradiction_notes = "\n".join(contradiction_notes)
        session.flush()

    consensus_changed = (
        previous_consensus is None
        or set(new_consensus.supporting_paper_ids) != set(previous_consensus.supporting_paper_ids)
        or new_consensus.is_insufficient_evidence != previous_consensus.is_insufficient_evidence
    )
    if consensus_changed:
        record_change_event(session, topic, ChangeEventType.CONSENSUS_UPDATED)

    topic.last_checked_at = datetime.utcnow()
