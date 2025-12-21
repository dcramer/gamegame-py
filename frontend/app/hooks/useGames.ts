import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "~/api/client";
import { queryKeys } from "~/lib/query";

export function useGames() {
  const [searchQuery, setSearchQuery] = useState("");

  const query = useQuery({
    queryKey: queryKeys.games.all,
    queryFn: () => api.games.list(),
  });

  const filteredGames = useMemo(() => {
    if (!query.data || !searchQuery.trim()) {
      return query.data ?? [];
    }
    const lowerQuery = searchQuery.toLowerCase();
    return query.data.filter(
      (game) =>
        game.name.toLowerCase().includes(lowerQuery) ||
        game.slug.toLowerCase().includes(lowerQuery),
    );
  }, [query.data, searchQuery]);

  return {
    games: query.data ?? [],
    filteredGames,
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    refetch: query.refetch,
    searchQuery,
    setSearchQuery,
  };
}
