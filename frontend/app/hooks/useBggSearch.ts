import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "~/api/client";
import { queryKeys } from "~/lib/query";

export function useBggSearch(query: string, enabled: boolean = true) {
  const result = useQuery({
    queryKey: queryKeys.bgg.search(query),
    queryFn: () => api.bgg.search(query),
    enabled: enabled && query.length >= 2,
    retry: false, // BGG has strict rate limits, don't retry
    staleTime: 1000 * 60 * 10, // Cache for 10 minutes
  });

  return {
    results: result.data ?? [],
    isLoading: result.isLoading,
    isFetching: result.isFetching,
    error: result.error?.message ?? null,
  };
}

export function useBggThumbnail(bggId: number | undefined) {
  const result = useQuery({
    queryKey: queryKeys.bgg.thumbnail(bggId ?? 0),
    queryFn: () => api.bgg.thumbnail(bggId!),
    enabled: !!bggId,
  });

  return {
    thumbnailUrl: result.data?.thumbnail_url ?? null,
    isLoading: result.isLoading,
  };
}

export function useImportBggGame() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (bggId: number) => api.bgg.import(bggId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.games.all });
    },
  });
}
