import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost } from "./client";
import type {
  CitationHistoryResponse,
  PaperCompareResponse,
  SavedSearch,
  SavedSearchVelocityResponse,
  SearchParams,
  SearchResponse,
  TierDistribution,
  TimelineBucket,
  TopicCompareResponse,
  TopicRef,
  VelocityResponse,
} from "./types";

export function useTopics() {
  return useQuery({ queryKey: ["topics"], queryFn: () => apiGet<TopicRef[]>("/topics") });
}

export function useSearch(params: SearchParams) {
  return useQuery({
    queryKey: ["search", params],
    queryFn: () => apiGet<SearchResponse>("/search", { ...params, page_size: 50 }),
  });
}

export function useComparePapers(paperIds: string[]) {
  return useQuery({
    queryKey: ["compare-papers", paperIds],
    queryFn: () => apiGet<PaperCompareResponse>("/compare/papers", { paper_ids: paperIds }),
    enabled: paperIds.length > 0,
  });
}

export function useCompareTopics(topicIds: string[]) {
  return useQuery({
    queryKey: ["compare-topics", topicIds],
    queryFn: () => apiGet<TopicCompareResponse>("/compare/topics", { topic_ids: topicIds }),
    enabled: topicIds.length > 0,
  });
}

export function useSavedSearches(userId: string | null) {
  return useQuery({
    queryKey: ["saved-searches", userId],
    queryFn: () => apiGet<SavedSearch[]>("/saved-searches", { user_id: userId }),
    enabled: userId !== null,
  });
}

export function useCreateSavedSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { userId: string; name: string; queryParams: SearchParams }) =>
      apiPost<SavedSearch>("/saved-searches", {
        user_id: input.userId,
        name: input.name,
        query_params: input.queryParams,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["saved-searches"] }),
  });
}

export function useDeleteSavedSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { userId: string; savedSearchId: string }) =>
      apiDelete(`/saved-searches/${input.savedSearchId}`, { user_id: input.userId }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["saved-searches"] }),
  });
}

export function useRunSavedSearch() {
  return useMutation({
    mutationFn: (input: { userId: string; savedSearchId: string }) =>
      apiPost<SearchResponse>(`/saved-searches/${input.savedSearchId}/run`, undefined, {
        user_id: input.userId,
      }),
  });
}

export function useTierDistribution(topicId: string) {
  return useQuery({
    queryKey: ["tier-distribution", topicId],
    queryFn: () => apiGet<TierDistribution>(`/topics/${topicId}/tier-distribution`),
  });
}

const NINETY_DAYS_MS = 90 * 24 * 60 * 60 * 1000;

export function useTimeline(topicId: string) {
  return useQuery({
    queryKey: ["timeline", topicId],
    queryFn: () =>
      apiGet<TimelineBucket[]>(`/topics/${topicId}/timeline`, {
        window_start: new Date(Date.now() - NINETY_DAYS_MS).toISOString(),
        window_end: new Date().toISOString(),
      }),
  });
}

// Velocity changes at most once a day, so refetching on every mount is wasted work.
const VELOCITY_STALE_MS = 1_800_000;

export function usePaperVelocities(paperIds: string[]) {
  const sorted = [...paperIds].sort();
  return useQuery({
    queryKey: ["paper-velocities", sorted],
    queryFn: () => apiGet<VelocityResponse>("/papers/velocity", { paper_ids: sorted }),
    enabled: sorted.length > 0,
    staleTime: VELOCITY_STALE_MS,
  });
}

export function useCitationHistory(paperId: string | null, days = 365) {
  return useQuery({
    queryKey: ["citation-history", paperId, days],
    queryFn: () =>
      apiGet<CitationHistoryResponse>(`/papers/${paperId}/citation-history`, { days }),
    enabled: paperId !== null,
    staleTime: VELOCITY_STALE_MS,
  });
}

export function useSavedSearchVelocity(
  savedSearchId: string | null,
  userId: string | null,
  weeks = 12,
) {
  return useQuery({
    queryKey: ["saved-search-velocity", savedSearchId, weeks],
    queryFn: () =>
      apiGet<SavedSearchVelocityResponse>(`/saved-searches/${savedSearchId}/velocity`, {
        user_id: userId,
        weeks,
      }),
    enabled: savedSearchId !== null && userId !== null,
    staleTime: VELOCITY_STALE_MS,
  });
}
