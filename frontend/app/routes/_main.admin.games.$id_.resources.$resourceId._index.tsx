import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle, Clock, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { api } from "~/api/client";
import type { ResourceStatus, ResourceType, ResourceUpdate } from "~/api/types";
import { ProcessingTimeline } from "~/components/processing-timeline";
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
import { useToast } from "~/contexts/toast";
import { useWorkflowTracking } from "~/contexts/workflow-tracking";
import { useResource } from "~/hooks";
import { queryKeys } from "~/lib/query";

const RESOURCE_TYPES: ResourceType[] = ["rulebook", "expansion", "faq", "errata", "reference"];

const PROCESSING_STAGES = [
  "ingest",
  "vision",
  "cleanup",
  "metadata",
  "segment",
  "embed",
  "finalize",
];

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

function statusVariant(
  status: ResourceStatus,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "completed":
      return "default";
    case "processing":
      return "secondary";
    case "queued":
      return "outline";
    case "failed":
      return "destructive";
    default:
      return "outline";
  }
}

export default function ResourceOverviewTab() {
  const { id, resourceId } = useParams<{ id: string; resourceId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { trackResource } = useWorkflowTracking();
  const { resource } = useResource(resourceId);

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
      // Default reprocess stage to failed stage when resource has failed
      if (resource.status === "failed" && resource.processing_stage) {
        setReprocessStage(resource.processing_stage);
      }
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
      toast({
        description: "Resource updated",
        variant: "success",
      });
    },
    onError: (err: Error) => {
      toast({
        title: "Update failed",
        description: err.message,
        variant: "destructive",
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
      toast({
        description: "Resource deleted",
        variant: "success",
      });
      navigate(`/admin/games/${id}/resources`);
    },
    onError: (err: Error) => {
      toast({
        title: "Delete failed",
        description: err.message,
        variant: "destructive",
      });
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

      // Track the workflow with the workflow tracking system
      trackResource(resourceId!, resource?.name || "Resource", {
        onComplete: () => {
          queryClient.invalidateQueries({
            queryKey: queryKeys.resources.detail(resourceId!),
          });
          queryClient.invalidateQueries({
            queryKey: queryKeys.resources.list(id!),
          });
        },
      });
    },
    onError: (err: Error) => {
      toast({
        title: "Reprocess failed",
        description: err.message,
        variant: "destructive",
        duration: 0, // Don't auto-dismiss errors
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

  if (!resource) {
    return null;
  }

  return (
    <div className="flex flex-col lg:flex-row gap-8">
      {/* Main content */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Status section */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <StatusIcon status={resource.status} />
              Processing Status
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Timeline for processing/queued/failed states */}
            {(resource.status === "processing" ||
              resource.status === "queued" ||
              resource.status === "failed") && (
              <ProcessingTimeline
                currentStage={resource.processing_stage}
                status={resource.status}
                className="py-2"
              />
            )}

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Status:</span>
                <Badge className="ml-2" variant={statusVariant(resource.status)}>
                  {resource.status}
                </Badge>
              </div>
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
                <span className="text-muted-foreground">Segments:</span>
                <span className="ml-2">{resource.segment_count ?? "-"}</span>
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
      </div>

      {/* Sidebar */}
      <div className="lg:w-[320px] space-y-6">
        {/* Danger zone */}
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle className="text-lg text-destructive">Danger Zone</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">
              Permanently delete this resource and all its attachments and fragments.
            </p>
            <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
              <DialogTrigger asChild>
                <Button variant="destructive" size="sm" className="w-full">
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete Resource
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

            {deleteMutation.error && (
              <div className="mt-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {deleteMutation.error.message}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
