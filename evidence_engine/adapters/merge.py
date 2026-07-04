from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.adapters.base import RawPaper
from evidence_engine.db.models import Paper, PaperTopic, Topic


def _merge_two(a: RawPaper, b: RawPaper) -> RawPaper:
    merged_fields = {}
    for f in a.__dataclass_fields__:
        a_val = getattr(a, f)
        b_val = getattr(b, f)
        if isinstance(a_val, list):
            merged_fields[f] = a_val or b_val
        elif isinstance(a_val, dict):
            merged_fields[f] = {**b_val, **a_val} if a_val else b_val
        else:
            merged_fields[f] = a_val if a_val is not None else b_val
    merged_fields["source"] = f"{a.source}+{b.source}"
    return RawPaper(**merged_fields)


def merge_raw_papers(raw_papers: list[RawPaper]) -> list[RawPaper]:
    groups: list[RawPaper] = []
    for raw_paper in raw_papers:
        match_index = None
        for i, existing in enumerate(groups):
            same_doi = raw_paper.doi and existing.doi and raw_paper.doi == existing.doi
            same_pmid = raw_paper.pmid and existing.pmid and raw_paper.pmid == existing.pmid
            if same_doi or same_pmid:
                match_index = i
                break
        if match_index is None:
            groups.append(raw_paper)
        else:
            groups[match_index] = _merge_two(groups[match_index], raw_paper)
    return groups


def upsert_paper(session: Session, topic: Topic, raw_paper: RawPaper) -> Paper:
    existing = None
    if raw_paper.doi:
        existing = session.execute(select(Paper).where(Paper.doi == raw_paper.doi)).scalar_one_or_none()
    if existing is None and raw_paper.pmid:
        existing = session.execute(select(Paper).where(Paper.pmid == raw_paper.pmid)).scalar_one_or_none()
    if existing is None and raw_paper.nct_id:
        existing = session.execute(select(Paper).where(Paper.nct_id == raw_paper.nct_id)).scalar_one_or_none()

    if existing:
        paper = existing
        paper.pmid = paper.pmid or raw_paper.pmid
        paper.doi = paper.doi or raw_paper.doi
        paper.nct_id = paper.nct_id or raw_paper.nct_id
        paper.semantic_scholar_id = paper.semantic_scholar_id or raw_paper.semantic_scholar_id
        paper.title = paper.title or raw_paper.title
        paper.abstract = paper.abstract or raw_paper.abstract
        paper.authors = paper.authors or raw_paper.authors
        paper.journal = paper.journal or raw_paper.journal
        paper.journal_issn = paper.journal_issn or raw_paper.journal_issn
        paper.pub_date = paper.pub_date or raw_paper.pub_date
        paper.publication_types = paper.publication_types or raw_paper.publication_types
    else:
        paper = Paper(
            pmid=raw_paper.pmid,
            doi=raw_paper.doi,
            nct_id=raw_paper.nct_id,
            semantic_scholar_id=raw_paper.semantic_scholar_id,
            title=raw_paper.title or "",
            abstract=raw_paper.abstract,
            authors=raw_paper.authors,
            journal=raw_paper.journal,
            journal_issn=raw_paper.journal_issn,
            pub_date=raw_paper.pub_date,
            publication_types=raw_paper.publication_types,
            raw_metadata=raw_paper.raw_metadata,
        )
        session.add(paper)
        session.flush()

    link_exists = session.execute(
        select(PaperTopic).where(PaperTopic.paper_id == paper.id, PaperTopic.topic_id == topic.id)
    ).scalar_one_or_none()
    if not link_exists:
        session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))

    return paper
