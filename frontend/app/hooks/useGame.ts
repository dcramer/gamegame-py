import { useQuery } from "@tanstack/react-query";
import { api } from "~/api/client";
import { queryKeys } from "~/lib/query";

export function useGame(idOrSlug: string | undefined) {
  const query = useQuery({
    queryKey: queryKeys.games.detail(idOrSlug ?? ""),
    queryFn: () => api.games.get(idOrSlug!),
    enabled: !!idOrSlug,
  });

  return {
    game: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    refetch: query.refetch,
  };
}
