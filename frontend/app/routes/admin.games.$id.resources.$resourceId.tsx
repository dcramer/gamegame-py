import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle,
  Clock,
  ExternalLink,
  Image,
  Loader2,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "~/api/client";
import type { ResourceStatus, ResourceType, ResourceUpdate } from "~/api/types";
import { Badge } from "~/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { Skeleton } from "~/components/ui/skeleton";
import { useAttachmentsByResource, useResource } from "~/hooks";
import { queryKeys } from "~/lib/query";

const RESOURCE_TYPES: ResourceType[] = ["rulebook", "expansion", "faq", "errata", "reference"];

const PROCESSING_STAGES = ["ingest", "vision", "cleanup", "metadata", "embed", "finalize"];

function StatusIcon({ status }: { status: ResourceStatus }) {
  switch (status) {
    case "completed":
      return <CheckCircle className="h-4 w-4 text-green-500" />;
    case "processing":
      return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />;
    case "queued":
      return <Clock className="h-4 w-4 text-yellow-500" />;
    case "failed":
      return <AlertCircle className="h-4 w-4 text-red-500" />;
    default:
      return null;
  }
}

export default function ResourceDetailPage() {
  const { id, resourceId } = useParams<{ id: string; resourceId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { resource, isLoading, error } = useResource(resourceId);
  const { attachments, isLoading: attachmentsLoading } = useAttachmentsByResource(resourceId);

  // Form state
  const [name, setName] = useState("");
  const [resourceType, setResourceType] = useState<ResourceType>("rulebook");

  // Dialog state
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [reprocessStage, setReprocessStage] = useState<string>("");

  // Populate form when resource loads
  useEffect(() => {
    if (resource) {
      setName(resource.name);
      setResourceType(resource.resource_type);
    }
  }, [resource]);

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: (data: ResourceUpdate) => api.resources.update(resourceId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.resources.detail(resourceId!),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.resources.list(id!),
      });
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: () => api.resources.delete(resourceId!),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.resources.list(id!),
      });
      navigate(`/admin/games/${id}/resources`);
    },
  });

  // Reprocess mutation
  const reprocessMutation = useMutation({
    mutationFn: (startStage?: string) => api.resources.reprocess(resourceId!, startStage),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.resources.detail(resourceId!),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.resources.list(id!),
      });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const data: ResourceUpdate = {};

    if (name !== resource?.name) data.name = name;
    if (resourceType !== resource?.resource_type) data.resource_type = resourceType;

    if (Object.keys(data).length > 0) {
      updateMutation.mutate(data);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6 max-w-2xl">
        <Skeleton className="h-8 w-48" />
        <Card>
          <CardContent className="pt-6 space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error || !resource) {
    return (
      <div className="max-w-2xl">
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">{error || "Resource not found"}</p>
            <Button asChild className="mt-4">
              <Link to={`/admin/games/${id}/resources`}>Back to Resources</Link>
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
          <h1 className="text-2xl font-bold">{resource.name}</h1>
          <p className="text-muted-foreground">
            {resource.original_filename || "Resource details"}
          </p>
        </div>
        {resource.url && (
          <Button variant="outline" size="sm" asChild>
            <a href={resource.url} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="mr-2 h-4 w-4" />
              View File
            </a>
          </Button>
        )}
      </div>

      {/* Status card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <StatusIcon status={resource.status} />
            Processing Status
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">Status:</span>
              <Badge
                className="ml-2"
                variant={resource.status === "completed" ? "default" : "secondary"}
              >
                {resource.status}
              </Badge>
            </div>
            {resource.processing_stage && (
              <div>
                <span className="text-muted-foreground">Stage:</span>
                <span className="ml-2">{resource.processing_stage}</span>
              </div>
            )}
            <div>
              <span className="text-muted-foreground">Pages:</span>
              <span className="ml-2">{resource.page_count ?? "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Images:</span>
              <span className="ml-2">{resource.image_count ?? "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Words:</span>
              <span className="ml-2">{resource.word_count?.toLocaleString() ?? "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Fragments:</span>
              <span className="ml-2">{resource.fragment_count ?? "-"}</span>
            </div>
          </div>

          <div className="flex items-center gap-2 pt-2 border-t">
            <span className="text-sm text-muted-foreground">Reprocess from:</span>
            <Select value={reprocessStage} onValueChange={setReprocessStage}>
              <SelectTrigger className="w-32">
                <SelectValue placeholder="Start" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__start__">Start</SelectItem>
                {PROCESSING_STAGES.map((stage) => (
                  <SelectItem key={stage} value={stage}>
                    {stage}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                reprocessMutation.mutate(
                  reprocessStage === "__start__" ? undefined : reprocessStage,
                )
              }
              disabled={reprocessMutation.isPending || resource.status === "processing"}
            >
              {reprocessMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              Reprocess
            </Button>
          </div>

          {reprocessMutation.error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {reprocessMutation.error.message}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Edit form */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Resource Details</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>

            <div className="space-y-2">
              <Label htmlFor="resourceType">Type</Label>
              <Select
                value={resourceType}
                onValueChange={(v) => setResourceType(v as ResourceType)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RESOURCE_TYPES.map((type) => (
                    <SelectItem key={type} value={type}>
                      {type.charAt(0).toUpperCase() + type.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {updateMutation.error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {updateMutation.error.message}
              </div>
            )}

            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? (
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

      {/* Attachments preview */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <Image className="h-5 w-5" />
            Attachments
            {!attachmentsLoading && <Badge variant="secondary">{attachments.length}</Badge>}
          </CardTitle>
          <Button variant="outline" size="sm" asChild>
            <Link to={`/admin/games/${id}/attachments`}>View All</Link>
          </Button>
        </CardHeader>
        <CardContent>
          {attachmentsLoading ? (
            <div className="grid grid-cols-4 gap-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="aspect-square rounded" />
              ))}
            </div>
          ) : attachments.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No attachments extracted yet
            </p>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              {attachments.slice(0, 8).map((attachment) => (
                <Link
                  key={attachment.id}
                  to={`/admin/games/${id}/attachments/${attachment.id}`}
                  className="block"
                >
                  <img
                    src={attachment.url}
                    alt={attachment.caption || "Attachment"}
                    className="aspect-square object-cover rounded hover:opacity-75 transition-opacity"
                  />
                </Link>
              ))}
              {attachments.length > 8 && (
                <Link
                  to={`/admin/games/${id}/attachments`}
                  className="aspect-square bg-muted rounded flex items-center justify-center text-muted-foreground hover:bg-muted/80 transition-colors"
                >
                  +{attachments.length - 8} more
                </Link>
              )}
            </div>
          )}
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
              <p className="font-medium">Delete this resource</p>
              <p className="text-sm text-muted-foreground">
                This will permanently delete the resource and all its attachments and fragments.
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
                  <DialogTitle>Delete {resource.name}?</DialogTitle>
                  <DialogDescription>
                    This action cannot be undone. This will permanently delete the resource and all
                    associated attachments and fragments.
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setShowDeleteDialog(false)}>
                    Cancel
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => deleteMutation.mutate()}
                    disabled={deleteMutation.isPending}
                  >
                    {deleteMutation.isPending ? (
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

          {deleteMutation.error && (
            <div className="mt-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {deleteMutation.error.message}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
