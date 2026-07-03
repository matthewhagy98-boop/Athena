# Evidence Engine — Design Spec

Status: Approved (pending user sign-off on this document)
Date: 2026-07-03
Scope: First sub-project of the research intelligence platform. Covers only the evidence ingestion, classification, scoring, and consensus-generation engine — not the web app, email digest, or enterprise API, which are separate future sub-projects that will consume this engine's output.

## 1. Purpose

Given a tracked research topic, continuously find relevant biomedical papers, classify and score each one for evidence strength, and maintain a synthesized "current consensus" grounded in the strongest available evidence — including flagging when evidence is insufficient or when a new paper contradicts established consensus.

This engine answers, per paper and per topic:
- What kind of study is this, and how strong is it?
- What are its specific methodological strengths and weaknesses?
- Does it agree or conflict with the current consensus?
- What is the current consensus overall, and how confident should we be in it?

## 2. Scope Decisions

- **Domain:** Biomedical only for v1 (richest structured metadata, clearest study-type taxonomy). Other domains (finance, physics, etc.) are explicitly out of scope until this is proven.
- **Data sources:** PubMed/PMC (E-utilities API), Semantic Scholar API, ClinicalTrials.gov.
- **Processing model:** Continuous ingestion pipeline (not on-demand). Required to support "what changed today," trending topics, and precomputed consensus.
- **Ingestion scope:** Topic-driven, not full-corpus. Only topics with an active interest profile or a user search are ingested and scored.
- **Topic definition:** Free-text interests/queries are normalized to MeSH (Medical Subject Headings) terms, so equivalent phrasings (e.g., "heart attack" / "myocardial infarction") share one topic's ingestion and consensus work. Mapping uses PubMed's own Automatic Term Mapping / ESearch translation (falling back to the UMLS Metathesaurus API for terms PubMed doesn't resolve) rather than a custom-built mapping.
- **Study-type classification:** PubMed Publication Type metadata tags are trusted when present; an LLM classifier reading the abstract is the fallback for missing/ambiguous tags or sources without a tagging scheme.
- **Journal reputation signal:** SCImago Journal Rank (SJR) — free, public, citation-weighted journal prestige metric. Journal Impact Factor (Clarivate/JCR) was rejected due to licensing cost; a self-computed citation proxy was rejected as easier to game and unfamiliar to users.
- **Evidence scoring method:** Deterministic GRADE-inspired base score (study-type tier, sample size, citation count, journal SJR) modified by LLM-detected risk-of-bias flags (no control group, no blinding, funding conflict of interest, underpowered sample, outcome switching vs. registered trial design). The same LLM pass produces the prose "quality breakdown" (strengths/weaknesses in methods, results, generalizability). Rejected alternatives: pure deterministic scoring (blind to real quality issues a number can't capture) and a learned ML model (no usable ground-truth dataset, opaque output, poor fit for users who must defend their sourcing).
- **Consensus generation:** Precomputed per topic (not per query), grounded only in the topic's current top-tier evidence (meta-analyses, systematic reviews, high-quality RCTs). Recomputed when that top-tier evidence set changes. Rejected alternative: generating consensus fresh at query time (slower, more expensive, inconsistent between users).

## 3. Architecture

Five components, each independently testable:

1. **Topic Registry** — canonical list of tracked topics (MeSH-normalized). Created when a user adds an interest or runs a novel search. Tracks per-topic ingestion state (last checked, last new paper found).
2. **Source Adapters** — one per external API (PubMed/PMC, Semantic Scholar, ClinicalTrials.gov). Given a topic, fetch matching records and normalize into a common `RawPaper` shape. Adapters know nothing about scoring.
3. **Classification & Scoring Engine** — takes a `RawPaper`, determines study type (metadata tag first, LLM fallback), extracts sample size, pulls citation count and journal SJR, runs the GRADE-inspired base score plus LLM risk-of-bias pass, and produces a `ScoredPaper` (numeric evidence-strength score, established/emerging/speculative tier, prose quality breakdown).
4. **Consensus Synthesizer** — runs per topic. Pulls current top-tier `ScoredPaper`s for a topic, generates the consensus paragraph grounded in those specific papers, and checks new incoming papers against it to raise contradiction flags. Re-runs when a topic's top-tier evidence set changes.
5. **Orchestrator** — scheduler driving the daily cycle: for each active topic, call adapters for new/updated records, score new papers, re-run consensus if warranted, and record what changed.

Data flows one direction: adapters → scoring → consensus, all writing into a shared store that downstream consumers (web app, email digest, enterprise API — future sub-projects) read from. None of them talk to the pipeline directly.

## 4. Data Model

Postgres as system of record (data is inherently relational).

- **Topic** — id, canonical MeSH term/ID, display label, known aliases, status, last-checked timestamp.
- **Paper** — id, external IDs per source (PMID, Semantic Scholar ID, NCT number), title, abstract, authors, journal, publication date, raw source metadata (retained as-is for audit/debugging).
- **PaperTopic** — many-to-many join; a paper can match multiple tracked topics.
- **Score** — paper_id, study type, extracted sample size, citation count, journal SJR, evidence-strength score, evidence tier (established/emerging/speculative), risk-of-bias flags, quality-breakdown text, `scored_at`, `model_version` (so scores stay traceable and reproducible as LLM prompts/models evolve).
- **ConsensusSnapshot** — topic_id, consensus paragraph, grounding paper IDs, contradiction notes, generated_at.
- **ChangeEvent** — topic_id, paper_id, event type (new paper / consensus updated / contradiction flagged), detected_at. Feeds "what changed today" and trending-topic detection.

Explicitly out of scope for this engine: full-text/semantic search indexing (embeddings, vector search) — that belongs to the future web app search sub-project, which reads from this store but is not part of the evidence engine.

## 5. Ingestion & Orchestration

- **New topic → backfill:** first time a topic is tracked, adapters query each source for the topic's full relevant history (not just "since yesterday"), accepting a short delay before a new topic's history is fully populated.
- **Steady state → daily incremental cycle:** for each active topic, adapters fetch records new/updated since `last_checked_at`; new records flow through scoring and, if warranted, consensus re-synthesis.
- **Cross-source deduplication:** the same paper often appears in both PubMed and Semantic Scholar. Adapters reconcile via DOI first, falling back to PMID cross-reference. Matched records merge into one `Paper`, combining fields from whichever source has them rather than discarding one source's data.
- **Rate limits:** PubMed E-utilities requires an API key for higher throughput (10 req/sec vs. 3 without). Semantic Scholar and ClinicalTrials.gov have their own limits. Every adapter implements backoff-and-retry, since a topic backfill can mean hundreds of paginated requests.

## 6. Error Handling & Edge Cases

- **Insufficient evidence:** if a topic has too few papers, or too few top-tier ones, the Consensus Synthesizer writes an explicit "insufficient evidence" state (a first-class value on `ConsensusSnapshot`, not an error) and falls back to listing only findings that recur across multiple independent papers.
- **Source adapter failures:** one adapter failing doesn't block the topic's cycle — the orchestrator proceeds with whatever sources succeeded and retries the failed one next cycle.
- **Scoring failures:** if the LLM call fails after retries, the paper is stored with adapter metadata in a `score_pending` state rather than blocking ingestion, and is retried next cycle.
- **Retractions:** as part of each topic's daily incremental cycle, previously-scored papers in that topic are rechecked against PubMed's retraction status. A retracted paper is flagged immediately and excluded from consensus grounding going forward.
- **Contradiction flagging:** a new paper whose extracted claims conflict with the topic's current `ConsensusSnapshot` is flagged ("contradicts current consensus") but still stored and scored normally — surfaced for the user's judgment, not suppressed.

## 7. Testing Strategy

- **Source adapters:** unit tests against recorded API-response fixtures, verifying normalization and dedup/merge logic against known overlapping-paper fixtures.
- **Deterministic scoring:** unit tests with known inputs (study type, sample size, citations, SJR) against expected output scores.
- **LLM classification & risk-of-bias:** evaluated against a hand-labeled golden set (~50-100 real papers with expert-agreed study type and known risk-of-bias issues). Run on every prompt/model change; deploys are gated on not regressing against this set — this is what makes `model_version` meaningful.
- **Consensus synthesis:** evaluated against a golden set of topics with expert-reviewed expected themes/claims, using an LLM-as-judge check (expected claims present, no unsupported claims) plus periodic human spot-checks.
- **Orchestrator:** integration tests running a full cycle (backfill → ingest → score → consensus) against mocked adapters, verifying `ChangeEvent` recording and that a single adapter failure doesn't block the topic.

## 8. Explicit Non-Goals (v1)

- Domains other than biomedical.
- The web app UI, search/filter experience, comparison tool, or bookmarking.
- Email digest generation and delivery.
- The enterprise API.
- Full-text/semantic search indexing.
- User interest-profile management (this spec assumes a `Topic` can be created; how users create/manage profiles that map to topics is a future sub-project's concern).
