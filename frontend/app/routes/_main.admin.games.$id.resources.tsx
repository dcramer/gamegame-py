import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle, Clock, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "~/api/client";
import type { ResourceStatus } from "~/api/types";
import { FileUpload } from "~/components/file-upload";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "~/components/ui/dialog";
import { Progress } from "~/components/ui/progress";
import { Skeleton } from "~/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "~/components/ui/table";
import { useToast } from "~/contexts/toast";
import { useWorkflowTracking } from "~/contexts/workflow-tracking";
import { useResources } from "~/hooks";
import { queryKeys } from "~/lib/query";

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

export default function ResourcesTab() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { trackResource } = useWorkflowTracking();
  const { resources, isLoading, error } = useResources(id);

  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [deleteDialogResourceId, setDeleteDialogResourceId] = useState<string | null>(null);

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      setUploadProgress(0);
      return api.resources.upload(id!, file, (progress) => {
        setUploadProgress(progress);
      });
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.list(id!) });
      setUploadError(null);
      setShowUploadDialog(false);

      // Navigate to the resource details page immediately
      navigate(`/admin/games/${id}/resources/${data.id}`);

      // Track the processing workflow
      if (data.status === "queued" || data.status === "processing") {
        trackResource(data.id, data.name, {
          onComplete: () => {
            queryClient.invalidateQueries({ queryKey: queryKeys.resources.list(id!) });
            queryClient.invalidateQueries({ queryKey: queryKeys.resources.detail(data.id) });
          },
        });
      } else {
        toast({
          title: "Upload complete",
          description: `"${data.name}" is ready`,
          variant: "success",
        });
      }
    },
    onError: (err: Error) => {
      setUploadError(err.message);
      toast({
        title: "Upload failed",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  // Reprocess mutation
  const reprocessMutation = useMutation({
    mutationFn: (resourceId: string) => api.resources.reprocess(resourceId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.list(id!) });

      // Track the reprocessing workflow
      trackResource(data.id, data.name, {
        onComplete: () => {
          queryClient.invalidateQueries({ queryKey: queryKeys.resources.list(id!) });
        },
      });
    },
    onError: (err: Error) => {
      toast({
        title: "Reprocess failed",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (resourceId: string) => api.resources.delete(resourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.list(id!) });
      setDeleteDialogResourceId(null); // Close dialog on success
      toast({
        description: "Resource deleted",
        variant: "success",
      });
    },
    onError: (err: Error) => {
      toast({
        title: "Delete failed",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  const handleFilesSelected = useCallback(
    async (files: File[]) => {
      const file = files[0];
      if (!file) return;

      setUploading(true);
      setUploadError(null);
      setUploadProgress(0);
      setShowUploadDialog(true);

      try {
        await uploadMutation.mutateAsync(file);
      } finally {
        setUploading(false);
      }
    },
    [uploadMutation],
  );

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex justify-end">
          <Skeleton className="h-10 w-32" />
        </div>
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Upload button */}
      <div className="flex justify-end">
        <FileUpload
          accept=".pdf"
          variant="button"
          buttonText="Upload PDF"
          onFilesSelected={handleFilesSelected}
          disabled={uploading}
        />
      </div>

      {/* Upload progress dialog */}
      <Dialog
        open={showUploadDialog}
        onOpenChange={(open) => !uploading && setShowUploadDialog(open)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {uploading ? "Uploading..." : uploadError ? "Upload Failed" : "Upload Complete"}
            </DialogTitle>
            <DialogDescription>
              {uploading
                ? "Please wait while your file is being uploaded."
                : uploadError
                  ? "There was a problem uploading your file."
                  : "Your file has been uploaded and is now processing."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {uploading && (
              <div className="space-y-2">
                <Progress value={uploadProgress} />
                <p className="text-sm text-muted-foreground text-center">
                  {uploadProgress}% complete
                </p>
              </div>
            )}
            {uploadError && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {uploadError}
              </div>
            )}
            {!uploading && (
              <div className="flex justify-end">
                <Button variant="outline" onClick={() => setShowUploadDialog(false)}>
                  Close
                </Button>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {uploadError && !showUploadDialog && (
        <div className="rounded-md bg-destructive/10 p-4 text-sm text-destructive">
          {uploadError}
        </div>
      )}

      {error ? (
        <div className="rounded-md bg-destructive/10 p-4 text-destructive">{error.message}</div>
      ) : resources.length === 0 ? (
        <FileUpload
          accept=".pdf"
          variant="dropzone"
          dropzoneText="Drop PDF here or click to browse"
          maxSize={100 * 1024 * 1024}
          onFilesSelected={handleFilesSelected}
          disabled={uploading}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Pages</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {resources.map((resource) => (
              <TableRow key={resource.id}>
                <TableCell className="font-medium">
                  <Link
                    to={`/admin/games/${id}/resources/${resource.id}`}
                    className="hover:underline"
                  >
                    {resource.name}
                  </Link>
                  {resource.original_filename && (
                    <div className="text-xs text-muted-foreground truncate max-w-[200px]">
                      {resource.original_filename}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant="outline">{resource.resource_type}</Badge>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <StatusIcon status={resource.status} />
                    <Badge variant={statusVariant(resource.status)}>{resource.status}</Badge>
                    {resource.processing_stage && resource.status === "processing" && (
                      <span className="text-xs text-muted-foreground">
                        ({resource.processing_stage})
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell>{resource.page_count ?? "-"}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => reprocessMutation.mutate(resource.id)}
                      disabled={reprocessMutation.isPending || resource.status === "processing"}
                    >
                      {reprocessMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="h-4 w-4" />
                      )}
                    </Button>
                    <Dialog
                      open={deleteDialogResourceId === resource.id}
                      onOpenChange={(open) => setDeleteDialogResourceId(open ? resource.id : null)}
                    >
                      <DialogTrigger asChild>
                        <Button variant="outline" size="sm">
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </DialogTrigger>
                      <DialogContent>
                        <DialogHeader>
                          <DialogTitle>Delete Resource?</DialogTitle>
                          <DialogDescription>
                            This will permanently delete "{resource.name}" and all its associated
                            attachments and fragments.
                          </DialogDescription>
                        </DialogHeader>
                        <div className="flex justify-end gap-2 mt-4">
                          <Button variant="outline" onClick={() => setDeleteDialogResourceId(null)}>
                            Cancel
                          </Button>
                          <Button
                            variant="destructive"
                            onClick={() => deleteMutation.mutate(resource.id)}
                            disabled={deleteMutation.isPending}
                          >
                            {deleteMutation.isPending ? (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                              <Trash2 className="mr-2 h-4 w-4" />
                            )}
                            Delete
                          </Button>
                        </div>
                      </DialogContent>
                    </Dialog>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
