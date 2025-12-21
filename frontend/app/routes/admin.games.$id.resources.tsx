import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle,
  Clock,
  FileText,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { api } from "~/api/client";
import type { ResourceStatus } from "~/api/types";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "~/components/ui/dialog";
import { Skeleton } from "~/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "~/components/ui/table";
import { useGame, useResources } from "~/hooks";
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

export default function ResourcesPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { game, isLoading: gameLoading } = useGame(id);
  const { resources, isLoading: resourcesLoading, error } = useResources(id);

  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const isLoading = gameLoading || resourcesLoading;

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      // The upload endpoint takes the file and game_id as a query param
      const token = localStorage.getItem("token");
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(`/api/games/${id}/resources`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(error.detail || "Upload failed");
      }

      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.list(id!) });
      setUploadError(null);
    },
    onError: (err: Error) => {
      setUploadError(err.message);
    },
  });

  // Reprocess mutation
  const reprocessMutation = useMutation({
    mutationFn: (resourceId: string) => api.resources.reprocess(resourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.list(id!) });
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (resourceId: string) => api.resources.delete(resourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.resources.list(id!) });
    },
  });

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadError(null);

    try {
      await uploadMutation.mutateAsync(file);
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-10 w-32" />
        </div>
        <Card>
          <CardContent className="pt-6">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full mb-2" />
            ))}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Resources</h1>
          <p className="text-muted-foreground">{game?.name} - Manage rulebooks and documents</p>
        </div>
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            onChange={handleFileSelect}
            className="hidden"
          />
          <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            {uploading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            Upload PDF
          </Button>
        </div>
      </div>

      {uploadError && (
        <div className="rounded-md bg-destructive/10 p-4 text-sm text-destructive">
          {uploadError}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">
            {resources.length} {resources.length === 1 ? "Resource" : "Resources"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="rounded-md bg-destructive/10 p-4 text-destructive">{error}</div>
          ) : resources.length === 0 ? (
            <div className="text-center py-8">
              <FileText className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-muted-foreground mb-4">No resources yet</p>
              <Button onClick={() => fileInputRef.current?.click()}>
                <Upload className="mr-2 h-4 w-4" />
                Upload Your First PDF
              </Button>
            </div>
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
                        <Dialog>
                          <DialogTrigger asChild>
                            <Button variant="outline" size="sm">
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </DialogTrigger>
                          <DialogContent>
                            <DialogHeader>
                              <DialogTitle>Delete Resource?</DialogTitle>
                              <DialogDescription>
                                This will permanently delete "{resource.name}" and all its
                                associated attachments and fragments.
                              </DialogDescription>
                            </DialogHeader>
                            <div className="flex justify-end gap-2 mt-4">
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
        </CardContent>
      </Card>
    </div>
  );
}
