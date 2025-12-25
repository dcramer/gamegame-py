import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "~/api/client";
import type { GameUpdate } from "~/api/types";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "~/components/ui/dialog";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { Skeleton } from "~/components/ui/skeleton";
import { Textarea } from "~/components/ui/textarea";
import { useGame } from "~/hooks";
import { queryKeys } from "~/lib/query";

export default function EditGamePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { game, isLoading, error } = useGame(id);

  // Form state
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [year, setYear] = useState("");
  const [description, setDescription] = useState("");
  const [imageUrl, setImageUrl] = useState("");

  // Dialog state
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  // Populate form when game loads
  useEffect(() => {
    if (game) {
      setName(game.name);
      setSlug(game.slug);
      setYear(game.year?.toString() ?? "");
      setDescription(game.description ?? "");
      setImageUrl(game.image_url ?? "");
    }
  }, [game]);

  // Update game mutation
  const updateGame = useMutation({
    mutationFn: (data: GameUpdate) => api.games.update(id!, data),
    onSuccess: (updatedGame) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.games.all });
      queryClient.invalidateQueries({
        queryKey: queryKeys.games.detail(id!),
      });
      // Update the slug if it changed
      if (updatedGame.slug !== game?.slug) {
        navigate(`/admin/games/${updatedGame.id}`, { replace: true });
      }
    },
  });

  // Delete game mutation
  const deleteGame = useMutation({
    mutationFn: () => api.games.delete(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.games.all });
      navigate("/admin");
    },
  });

  // Sync BGG mutation
  const syncBgg = useMutation({
    mutationFn: () => api.games.syncBgg(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.games.detail(id!) });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const data: GameUpdate = {};

    // Only include changed fields
    if (name !== game?.name) data.name = name;
    if (slug !== game?.slug) data.slug = slug;

    const yearNum = year ? parseInt(year, 10) : null;
    if (yearNum !== game?.year) data.year = yearNum;

    const desc = description || null;
    if (desc !== game?.description) data.description = desc;

    const img = imageUrl || null;
    if (img !== game?.image_url) data.image_url = img;

    if (Object.keys(data).length > 0) {
      updateGame.mutate(data);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6 max-w-2xl">
        <Skeleton className="h-8 w-48" />
        <Card>
          <CardContent className="pt-6 space-y-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error || !game) {
    return (
      <div className="max-w-2xl">
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">{error || "Game not found"}</p>
            <Button asChild className="mt-4">
              <Link to="/admin">Back to Dashboard</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{game.name}</h1>
          <p className="text-muted-foreground">Edit game details</p>
        </div>
        {game.bgg_url && (
          <Button variant="outline" size="sm" asChild>
            <a href={game.bgg_url} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="mr-2 h-4 w-4" />
              BoardGameGeek
            </a>
          </Button>
        )}
      </div>

      {/* Game image preview */}
      {game.image_url && (
        <div className="flex items-center gap-4">
          <img src={game.image_url} alt={game.name} className="w-24 h-24 object-cover rounded-lg" />
          {game.bgg_id && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => syncBgg.mutate()}
              disabled={syncBgg.isPending}
            >
              {syncBgg.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              Sync from BGG
            </Button>
          )}
        </div>
      )}

      {syncBgg.error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {syncBgg.error.message}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Game Details</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Name *</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>

            <div className="space-y-2">
              <Label htmlFor="slug">Slug</Label>
              <Input id="slug" value={slug} onChange={(e) => setSlug(e.target.value)} />
              <p className="text-xs text-muted-foreground">
                URL-friendly identifier. Currently:{" "}
                <code className="bg-muted px-1 py-0.5 rounded">/games/{slug}</code>
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="year">Year</Label>
              <Input
                id="year"
                type="number"
                value={year}
                onChange={(e) => setYear(e.target.value)}
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
                rows={4}
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

            {updateGame.error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {updateGame.error.message}
              </div>
            )}

            <div className="flex gap-3">
              <Button type="submit" disabled={updateGame.isPending}>
                {updateGame.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  "Save Changes"
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Quick links */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Quick Links</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-3">
          <Button variant="outline" asChild>
            <Link to={`/admin/games/${game.id}/resources`}>Manage Resources</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link to={`/admin/games/${game.id}/attachments`}>View Attachments</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link to={`/games/${game.slug}`}>View Public Page</Link>
          </Button>
        </CardContent>
      </Card>

      {/* Danger zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-lg text-destructive">Danger Zone</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Delete this game</p>
              <p className="text-sm text-muted-foreground">
                This will permanently delete the game and all its resources.
              </p>
            </div>
            <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
              <DialogTrigger asChild>
                <Button variant="destructive" size="sm">
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Delete {game.name}?</DialogTitle>
                  <DialogDescription>
                    This action cannot be undone. This will permanently delete the game and all
                    associated resources, attachments, and fragments.
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setShowDeleteDialog(false)}>
                    Cancel
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => deleteGame.mutate()}
                    disabled={deleteGame.isPending}
                  >
                    {deleteGame.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="mr-2 h-4 w-4" />
                    )}
                    Delete
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>

          {deleteGame.error && (
            <div className="mt-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {deleteGame.error.message}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
