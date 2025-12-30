import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { api } from "~/api/client";
import type { GameCreate } from "~/api/types";
import { PageHeader } from "~/components/page-header";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { Skeleton } from "~/components/ui/skeleton";
import { Textarea } from "~/components/ui/textarea";
import { useToast } from "~/contexts/toast";
import { useBggSearch, useDebounce, useImportBggGame } from "~/hooks";
import { queryKeys } from "~/lib/query";

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .trim();
}

export default function AddGamePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // Form state
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false);
  const [year, setYear] = useState("");
  const [description, setDescription] = useState("");
  const [imageUrl, setImageUrl] = useState("");

  // BGG search state
  const [bggQuery, setBggQuery] = useState("");
  const debouncedBggQuery = useDebounce(bggQuery, 400);
  const [showBggSearch, setShowBggSearch] = useState(true);
  const {
    results: bggResults,
    isLoading: bggLoading,
    isFetching: bggFetching,
    error: bggError,
  } = useBggSearch(debouncedBggQuery);
  const importBggGame = useImportBggGame();

  // Show loading when typing (debouncing) or when actually fetching
  const isSearching = (bggQuery !== debouncedBggQuery && bggQuery.length >= 2) || bggFetching;

  // Auto-generate slug from name
  useEffect(() => {
    if (!slugManuallyEdited && name) {
      setSlug(slugify(name));
    }
  }, [name, slugManuallyEdited]);

  // Create game mutation
  const createGame = useMutation({
    mutationFn: (data: GameCreate) => api.games.create(data),
    onSuccess: (game) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.games.all });
      toast({
        title: "Game created",
        description: `"${game.name}" has been added`,
        variant: "success",
      });
      navigate(`/admin/games/${game.id}`);
    },
    onError: (err: Error) => {
      toast({
        title: "Failed to create game",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  const handleBggImport = async (bggId: number) => {
    try {
      const result = await importBggGame.mutateAsync(bggId);
      toast({
        title: "Game imported",
        description: `"${result.name}" has been imported from BoardGameGeek`,
        variant: "success",
      });
      navigate(`/admin/games/${result.id}`);
    } catch (err) {
      toast({
        title: "Import failed",
        description: err instanceof Error ? err.message : "Failed to import game",
        variant: "destructive",
      });
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const data: GameCreate = {
      name,
      slug: slug || slugify(name),
      year: year ? parseInt(year, 10) : null,
      description: description || null,
      image_url: imageUrl || null,
    };

    createGame.mutate(data);
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <PageHeader
        breadcrumbs={[{ label: "Admin", to: "/admin" }, { label: "Add Game" }]}
        title="Add Game"
        description="Import from BoardGameGeek or create manually"
      />

      {/* BGG Search */}
      {showBggSearch && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Import from BoardGameGeek</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                type="search"
                placeholder="Search BoardGameGeek..."
                value={bggQuery}
                onChange={(e) => setBggQuery(e.target.value)}
                className="pl-9"
              />
              {isSearching && (
                <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground animate-spin" />
              )}
            </div>

            {bggError && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                Failed to search BoardGameGeek: {bggError}
              </div>
            )}

            {bggLoading && (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-16 w-full" />
                ))}
              </div>
            )}

            {bggResults.length > 0 && (
              <div className="space-y-2">
                {bggResults.map((result) => (
                  <div
                    key={result.bgg_id}
                    className="flex items-center justify-between p-3 rounded-lg border border-border hover:bg-muted transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      {result.game_image_url && (
                        <img
                          src={result.game_image_url}
                          alt={result.name}
                          className="w-12 h-12 object-cover rounded"
                        />
                      )}
                      <div>
                        <div className="font-medium">{result.name}</div>
                        <div className="text-sm text-muted-foreground">
                          {result.year ?? "Unknown year"}
                        </div>
                      </div>
                    </div>
                    {result.is_imported ? (
                      <Badge variant="secondary">
                        <Check className="mr-1 h-3 w-3" />
                        Imported
                      </Badge>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => handleBggImport(result.bgg_id)}
                        disabled={importBggGame.isPending}
                      >
                        {importBggGame.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          "Import"
                        )}
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {importBggGame.error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {importBggGame.error.message}
              </div>
            )}

            <div className="text-center">
              <Button
                variant="link"
                onClick={() => setShowBggSearch(false)}
                className="text-muted-foreground"
              >
                Or create game manually
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Manual form */}
      {!showBggSearch && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg">Create Game Manually</CardTitle>
              <Button
                variant="link"
                onClick={() => setShowBggSearch(true)}
                className="text-muted-foreground"
              >
                Import from BGG instead
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">Name *</Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Catan"
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="slug">Slug</Label>
                <Input
                  id="slug"
                  value={slug}
                  onChange={(e) => {
                    setSlug(e.target.value);
                    setSlugManuallyEdited(true);
                  }}
                  placeholder="e.g., catan"
                />
                <p className="text-xs text-muted-foreground">
                  URL-friendly identifier. Auto-generated from name if left empty.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="year">Year</Label>
                <Input
                  id="year"
                  type="number"
                  value={year}
                  onChange={(e) => setYear(e.target.value)}
                  placeholder="e.g., 1995"
                  min="1900"
                  max={new Date().getFullYear() + 1}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="A brief description of the game..."
                  rows={3}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="imageUrl">Image URL</Label>
                <Input
                  id="imageUrl"
                  type="url"
                  value={imageUrl}
                  onChange={(e) => setImageUrl(e.target.value)}
                  placeholder="https://..."
                />
              </div>

              {createGame.error && (
                <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                  {createGame.error.message}
                </div>
              )}

              <div className="flex gap-3">
                <Button type="submit" disabled={!name || createGame.isPending}>
                  {createGame.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Creating...
                    </>
                  ) : (
                    "Create Game"
                  )}
                </Button>
                <Button type="button" variant="outline" onClick={() => navigate("/admin")}>
                  Cancel
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
