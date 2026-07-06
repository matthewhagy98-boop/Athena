import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost } from "./client";
import type {
  PaperCompareResponse,
  SavedSearch,
  SearchParams,
  SearchResponse,
  TierDistribution,
  TimelineBucket,
  TopicCompareResponse,
  TopicRef,
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
