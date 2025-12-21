import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "~/api/client";
import type { ResourceUpdate } from "~/api/types";
import { queryKeys } from "~/lib/query";

export function useResources(gameIdOrSlug: string | undefined) {
  const query = useQuery({
    queryKey: queryKeys.resources.byGame(gameIdOrSlug ?? ""),
    queryFn: () => api.resources.list(gameIdOrSlug!),
    enabled: !!gameIdOrSlug,
  });

  return {
    resources: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    refetch: query.refetch,
  };
}

export function useResource(id: string | undefined) {
  const query = useQuery({
    queryKey: queryKeys.resources.detail(id ?? ""),
    queryFn: () => api.resources.get(id!),
    enabled: !!id,
  });

  return {
    resource: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
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
