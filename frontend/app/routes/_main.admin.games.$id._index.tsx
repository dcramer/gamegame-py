import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw, Trash2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
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
import { Textarea } from "~/components/ui/textarea";
import { useToast } from "~/contexts/toast";
import { useGame } from "~/hooks";
import { useFileInputWithDragDrop } from "~/hooks/use-file-input";
import { queryKeys } from "~/lib/query";
import { cn } from "~/lib/utils";

export default function GameDetailsTab() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { game } = useGame(id);

  // Form state
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [year, setYear] = useState("");
  const [description, setDescription] = useState("");

  // Image upload state
  const [isUploadingImage, setIsUploadingImage] = useState(false);
  const [isDraggingImage, setIsDraggingImage] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);

  // Dialog state
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  // Populate form when game loads
  useEffect(() => {
    if (game) {
      setName(game.name);
      setSlug(game.slug);
      setYear(game.year?.toString() ?? "");
      setDescription(game.description ?? "");
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
      toast({
        description: "Game updated",
        variant: "success",
      });
      if (updatedGame.slug !== game?.slug) {
        navigate(`/admin/games/${updatedGame.id}`, { replace: true });
      }
    },
    onError: (err: Error) => {
      toast({
        title: "Update failed",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  // Delete game mutation
  const deleteGame = useMutation({
    mutationFn: () => api.games.delete(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.games.all });
      toast({
        description: "Game deleted",
        variant: "success",
      });
      navigate("/admin");
    },
    onError: (err: Error) => {
      toast({
        title: "Delete failed",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  // Sync BGG mutation
  const syncBgg = useMutation({
    mutationFn: () => api.games.syncBgg(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.games.detail(id!) });
      toast({
        description: "Synced from BGG",
        variant: "success",
      });
    },
    onError: (err: Error) => {
      toast({
        title: "Sync failed",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  // Image upload handler
  const handleImageUpload = useCallback(
    async (files: File[]) => {
      const file = files[0];
      if (!file) return;

      // Validate file type
      if (!file.type.startsWith("image/")) {
        setImageError("Please select an image file");
        return;
      }

      // Validate file size (10MB max)
      if (file.size > 10 * 1024 * 1024) {
        setImageError("Image must be less than 10MB");
        return;
      }

      setImageError(null);
      setIsUploadingImage(true);

      try {
        // Upload the image
        const uploadResult = await api.upload.file(file, "image");

        // Update the game with the new image URL
        await api.games.update(id!, { image_url: uploadResult.url });

        // Refresh game data
        queryClient.invalidateQueries({ queryKey: queryKeys.games.detail(id!) });
        queryClient.invalidateQueries({ queryKey: queryKeys.games.all });

        toast({
          description: "Image updated",
          variant: "success",
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Upload failed";
        setImageError(message);
        toast({
          title: "Upload failed",
          description: message,
          variant: "destructive",
        });
      } finally {
        setIsUploadingImage(false);
      }
    },
    [id, queryClient, toast],
  );

  // Remove image handler
  const handleRemoveImage = useCallback(async () => {
    try {
      await api.games.update(id!, { image_url: null });
      queryClient.invalidateQueries({ queryKey: queryKeys.games.detail(id!) });
      queryClient.invalidateQueries({ queryKey: queryKeys.games.all });
      toast({
        description: "Image removed",
        variant: "success",
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to remove image";
      toast({
        title: "Error",
        description: message,
        variant: "destructive",
      });
    }
  }, [id, queryClient, toast]);

  // File input hook for image upload
  const { triggerFileInput: triggerImageInput, dragHandlers: imageDragHandlers } =
    useFileInputWithDragDrop({
      accept: "image/*",
      multiple: false,
      onSelect: handleImageUpload,
    });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const data: GameUpdate = {};

    if (name !== game?.name) data.name = name;
    if (slug !== game?.slug) data.slug = slug;

    const yearNum = year ? parseInt(year, 10) : null;
    if (yearNum !== game?.year) data.year = yearNum;

    const desc = description || null;
    if (desc !== game?.description) data.description = desc;

    if (Object.keys(data).length > 0) {
      updateGame.mutate(data);
    }
  };

  if (!game) return null;

  return (
    <div className="flex flex-col lg:flex-row gap-8">
      {/* Main content */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Sync BGG button */}
        {game.bgg_id && (
          <div className="flex items-center gap-4">
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
            {syncBgg.error && (
              <span className="text-sm text-destructive">{syncBgg.error.message}</span>
            )}
          </div>
        )}

        {/* Edit form */}
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
                  URL-friendly identifier:{" "}
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

              {/* Image Upload */}
              <div className="space-y-2">
                <Label>Game Image</Label>
                {game.image_url ? (
                  <div className="relative group">
                    <img
                      src={game.image_url}
                      alt={game.name}
                      className="w-full max-w-[200px] h-auto rounded-lg border border-border"
                    />
                    <div className="absolute inset-0 max-w-[200px] bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg flex items-center justify-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        onClick={triggerImageInput}
                        disabled={isUploadingImage}
                      >
                        {isUploadingImage ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Upload className="h-4 w-4" />
                        )}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        onClick={handleRemoveImage}
                        disabled={isUploadingImage}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div
                    onDragOver={(e) => {
                      imageDragHandlers.onDragOver(e);
                      setIsDraggingImage(true);
                    }}
                    onDragLeave={(e) => {
                      e.preventDefault();
                      setIsDraggingImage(false);
                    }}
                    onDrop={(e) => {
                      imageDragHandlers.onDrop(e);
                      setIsDraggingImage(false);
                    }}
                    onClick={triggerImageInput}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        triggerImageInput();
                      }
                    }}
                    className={cn(
                      "flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-background p-8 text-center transition-all cursor-pointer group",
                      "hover:border-primary",
                      isDraggingImage && "border-primary bg-primary/10",
                      isUploadingImage && "opacity-50 cursor-not-allowed",
                    )}
                    role="button"
                    tabIndex={0}
                  >
                    {isUploadingImage ? (
                      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-2" />
                    ) : (
                      <Upload className="h-8 w-8 text-muted-foreground mb-2" />
                    )}
                    <p className="text-sm font-medium">
                      {isUploadingImage ? "Uploading..." : "Drop image here or click to browse"}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      PNG, JPG, GIF, WebP up to 10MB
                    </p>
                  </div>
                )}
                {imageError && <p className="text-sm text-destructive">{imageError}</p>}
              </div>

              {updateGame.error && (
                <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                  {updateGame.error.message}
                </div>
              )}

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
            </form>
          </CardContent>
        </Card>
      </div>

      {/* Sidebar */}
      <div className="lg:w-[320px] space-y-6">
        {/* Quick links */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Quick Links</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button variant="outline" className="w-full justify-start" asChild>
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
            <p className="text-sm text-muted-foreground mb-4">
              Permanently delete this game and all its resources.
            </p>
            <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
              <DialogTrigger asChild>
                <Button variant="destructive" size="sm" className="w-full">
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete Game
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

            {deleteGame.error && (
              <div className="mt-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {deleteGame.error.message}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
