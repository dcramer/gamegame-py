import { Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { Game } from "~/api/types";
import { Badge } from "~/components/ui/badge";
import { Card, CardContent } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import type { Route } from "./+types/games._index";

// SSR loader - fetch games on server
export async function loader() {
  const baseUrl = process.env.API_URL || "http://localhost:8000";
  const response = await fetch(`${baseUrl}/api/games`);
  if (!response.ok) {
    throw new Response("Failed to load games", { status: response.status });
  }
  const games: Game[] = await response.json();
  return { games };
}

export function meta() {
  return [
    { title: "Games - GameGame" },
    { name: "description", content: "Browse our collection of board games" },
  ];
}

export default function GamesPage({ loaderData }: Route.ComponentProps) {
  const { games } = loaderData;
  const [searchQuery, setSearchQuery] = useState("");

  // Client-side filtering
  const filteredGames = games.filter(
    (game) =>
      game.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      game.description?.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
        <h1 className="text-3xl font-bold">Games</h1>
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search games..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {filteredGames.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-muted-foreground text-lg">
            {searchQuery
              ? "No games match your search"
              : "No games yet. Add some games to get started!"}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredGames.map((game) => (
            <Link key={game.id} to={`/games/${game.slug}`}>
              <Card className="h-full overflow-hidden hover:border-foreground/20 transition-colors group">
                {game.image_url ? (
                  <div className="aspect-[4/3] overflow-hidden">
                    <img
                      src={game.image_url}
                      alt={game.name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    />
                  </div>
                ) : (
                  <div className="aspect-[4/3] bg-muted flex items-center justify-center">
                    <span className="text-4xl text-muted-foreground">{game.name.charAt(0)}</span>
                  </div>
                )}
                <CardContent className="pt-4">
                  <h2 className="text-lg font-semibold mb-1 line-clamp-1">{game.name}</h2>
                  <div className="flex items-center gap-2">
                    {game.year && (
                      <span className="text-sm text-muted-foreground">{game.year}</span>
                    )}
                    {game.resource_count !== undefined && game.resource_count > 0 && (
                      <Badge variant="secondary" className="text-xs">
                        {game.resource_count} {game.resource_count === 1 ? "resource" : "resources"}
                      </Badge>
                    )}
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
