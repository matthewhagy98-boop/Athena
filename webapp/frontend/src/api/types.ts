export interface TopicRef {
  id: string;
  canonical_label: string;
}

export interface PaperRow {
  paper: { id: string; title: string; abstract: string | null; pub_date: string | null };
  score: {
    evidence_tier: "established" | "emerging" | "speculative";
    study_type: string | null;
    final_score: number;
  } | null;
  topics: TopicRef[];
}

export interface SearchResponse {
  rows: PaperRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface SearchParams {
  q?: string;
  topic_id?: string;
  tier?: string;
  study_type?: string;
  date_from?: string;
  date_to?: string;
}

export interface PaperCompareResponse {
  rows: PaperRow[];
  unresolved_ids: string[];
}

export interface TopicCompareRow {
  topic: TopicRef;
  consensus: { consensus_text: string } | null;
}

export interface TopicCompareResponse {
  rows: TopicCompareRow[];
  unresolved_ids: string[];
}

export interface SavedSearch {
  id: string;
  name: string;
  query_params: SearchParams;
  last_run_at?: string | null;
}

export interface TierDistribution {
  established: number;
  emerging: number;
  speculative: number;
}

export interface TimelineBucket {
  bucket_date: string;
  event_type: string;
  count: number;
}

export type VelocityStatus = "ready" | "insufficient_history" | "unrefreshable";

export interface PaperVelocity {
  status: VelocityStatus;
  velocity_per_30d: number | null;
  window_start_observed_at: string | null;
  window_end_observed_at: string | null;
  observation_count: number;
  first_observed_at: string | null;
  percentile: number | null;
  cohort_size: number;
  is_retracted: boolean;
  computed_at: string | null;
}

export interface VelocityResponse {
  velocities: Record<string, PaperVelocity>;
}

export interface CitationObservation {
  observed_on: string;
  citation_count: number;
  is_anomalous: boolean;
}

export interface CitationHistoryResponse {
  paper_id: string;
  observations: CitationObservation[];
  first_observed_at: string | null;
  source: string;
}

export interface SavedSearchVelocityPoint {
  week_start: string;
  median_velocity_per_30d: number;
}

export interface SavedSearchVelocityResponse {
  status: "ready" | "insufficient_coverage";
  papers_total: number;
  papers_examined: number;
  papers_with_history: number;
  series: SavedSearchVelocityPoint[];
  computed_at: string;
}
