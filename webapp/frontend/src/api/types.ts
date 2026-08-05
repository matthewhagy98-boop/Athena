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
