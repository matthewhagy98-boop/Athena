import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost } from "./client";
import type {
  ActivityResponse,
  ChangeFeedResponse,
  CitationHistoryResponse,
  FeatureFlags,
  PaperCompareResponse,
  PersonalDashboardResponse,
  SavedSearch,
  SavedSearchVelocityResponse,
  SearchParams,
  SearchResponse,
  SynthesisResult,
  TierDistribution,
  TimelineBucket,
  TopicCompareResponse,
  TopicRef,
  VelocityResponse,
} from "./types";

export function useFeatures() {
  return useQuery({ queryKey: ["features"], queryFn: () => apiGet<FeatureFlags>("/features") });
}

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

export function useSynthesis() {
  return useMutation({
    mutationFn: (input: { paperIds: string[]; userId: string | null }) =>
      apiPost<SynthesisResult>("/synthesis/papers", {
        paper_ids: input.paperIds,
        user_id: input.userId,
      }),
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

export function useActivityRanking(limit = 10) {
  return useQuery({
    queryKey: ["dashboard", "activity", limit],
    queryFn: () => apiGet<ActivityResponse>(`/dashboard/activity?limit=${limit}`),
  });
}

export function useChangeFeed(days = 7, limit = 20) {
  return useQuery({
    queryKey: ["dashboard", "changes", days, limit],
    queryFn: () => apiGet<ChangeFeedResponse>(`/dashboard/changes?days=${days}&limit=${limit}`),
  });
}

export function usePersonalDashboard(userId: string | null) {
  return useQuery({
    queryKey: ["dashboard", "personal", userId],
    // Disabled rather than called with a null id: the endpoint requires user_id and
    // would 422, turning the ordinary pre-identity render into an error state.
    enabled: Boolean(userId),
    queryFn: () => apiGet<PersonalDashboardResponse>(`/dashboard/personal?user_id=${userId}`),
  });
}

export function useAddInterest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { userId: string; freeText: string }) =>
      apiPost<{ topic: TopicRef; created: boolean }>("/interests", {
        user_id: input.userId,
        free_text: input.freeText,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard", "personal"] }),
  });
}

export function useRemoveInterest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { userId: string; topicId: string }) =>
      apiDelete(`/interests/${input.topicId}?user_id=${input.userId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard", "personal"] }),
  });
}
