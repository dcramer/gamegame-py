import { useQuery } from "@tanstack/react-query";
import { api } from "~/api/client";
import { queryKeys } from "~/lib/query";

interface UseSegmentsOptions {
  limit?: number;
  offset?: number;
}

export function useSegmentsByResource(
  resourceId: string | undefined,
  options?: UseSegmentsOptions,
) {
  const query = useQuery({
    queryKey: [...queryKeys.segments.byResource(resourceId ?? ""), options],
    queryFn: () => api.segments.listByResource(resourceId!, options),
    enabled: !!resourceId,
  });

  return {
    segments: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error ?? null,
    isFetching: query.isFetching,
    refetch: query.refetch,
  };
}

export function useSegment(id: string | undefined) {
  const query = useQuery({
    queryKey: queryKeys.segments.detail(id ?? ""),
    queryFn: () => api.segments.get(id!),
    enabled: !!id,
  });

  return {
    segment: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error ?? null,
    isFetching: query.isFetching,
    refetch: query.refetch,
  };
}
