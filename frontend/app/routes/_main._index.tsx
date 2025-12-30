import { Dices } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { Game } from "~/api/types";
import { Card, CardHeader, CardTitle } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import type { Route } from "./+types/_main._index";

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
  const [searchTerm, setSearchTerm] = useState("");
  const [imageErrors, setImageErrors] = useState<Set<string>>(new Set());

  // Client-side filtering
  const matchingGames = games.filter((game) =>
    game.name.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  return (
    <>
      <section className="text-center py-3 lg:py-12">
        <h1 className="text-2xl lg:text-5xl lg:mb-6 mb-2 font-bold">What are you playing?</h1>
        <p className="text-lg lg:text-xl mb-4 lg:mb-8 text-muted-foreground">
          Select your game to start getting answers about the rules.
        </p>
      </section>

      <div className="flex flex-col gap-6">
        <Input
          placeholder="Search games..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-8">
          {matchingGames.map((game) => (
            <Card
              key={game.id}
              className="relative rounded-lg overflow-hidden border-2 border-border hover:border-primary transition-colors group"
            >
              <div className="w-full aspect-[3/2] overflow-hidden relative bg-muted flex items-center justify-center">
                {game.image_url && !imageErrors.has(game.id) ? (
                  <img
                    src={game.image_url}
                    alt={game.name}
                    className="w-full h-full object-cover object-top group-hover:scale-105 transition-transform duration-300"
                    onError={() => {
                      setImageErrors((prev) => new Set(prev).add(game.id));
                    }}
                  />
                ) : (
                  <Dices className="w-16 h-16 text-muted-foreground" />
                )}
              </div>
              <CardHeader className="py-4">
                <CardTitle className="text-center text-xl leading-tight">{game.name}</CardTitle>
              </CardHeader>
              <Link to={`/games/${game.slug || game.id}`} className="inset-0 absolute" />
            </Card>
          ))}
        </div>

        {matchingGames.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <Dices className="w-12 h-12 text-muted-foreground mb-4" />
            <h3 className="text-xl font-semibold mb-2">
              {games.length === 0 ? "No games yet" : "No games found"}
            </h3>
            <p className="text-muted-foreground">
              {games.length === 0
                ? "Check with your administrator to add games."
                : "No games found matching your search. Try a different search term."}
            </p>
          </div>
        )}
      </div>
    </>
  );
}
