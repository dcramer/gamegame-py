import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "~/api/client";
import type { ResourceUpdate } from "~/api/types";
import { queryKeys } from "~/lib/query";

// Poll interval for resources that are being processed
const PROCESSING_POLL_INTERVAL = 3000; // 3 seconds

export function useResources(gameIdOrSlug: string | undefined) {
  const query = useQuery({
    queryKey: queryKeys.resources.list(gameIdOrSlug ?? ""),
    queryFn: () => api.resources.list(gameIdOrSlug!),
    enabled: !!gameIdOrSlug,
    // Poll when any resource is processing or queued
    refetchInterval: (query) => {
      const resources = query.state.data;
      if (!resources) return false;
      const hasProcessing = resources.some(
        (r) => r.status === "processing" || r.status === "queued",
      );
      return hasProcessing ? PROCESSING_POLL_INTERVAL : false;
    },
  });

  return {
    resources: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error ?? null,
    isFetching: query.isFetching,
    refetch: query.refetch,
  };
}

export function useResource(id: string | undefined) {
  const query = useQuery({
    queryKey: queryKeys.resources.detail(id ?? ""),
    queryFn: () => api.resources.get(id!),
    enabled: !!id,
    // Poll when resource is processing or queued
    refetchInterval: (query) => {
      const resource = query.state.data;
      if (!resource) return false;
      const isProcessing = resource.status === "processing" || resource.status === "queued";
      return isProcessing ? PROCESSING_POLL_INTERVAL : false;
    },
  });

  return {
    resource: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ?? null,
    isFetching: query.isFetching,
    refetch: query.refetch,
  };
}

export function useUpdateResource() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ResourceUpdate }) =>
      api.resources.update(id, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all });
      queryClient.setQueryData(queryKeys.resources.detail(data.id), data);
    },
  });
}

export function useDeleteResource() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api.resources.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all });
    },
  });
}

export function useReprocessResource() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, startStage }: { id: string; startStage?: string }) =>
      api.resources.reprocess(id, startStage),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.all });
      queryClient.setQueryData(queryKeys.resources.detail(data.id), data);
    },
  });
}
