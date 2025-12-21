import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { api } from "~/api/client";
import type { AttachmentUpdate, DetectedType, QualityRating } from "~/api/types";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Label } from "~/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { Skeleton } from "~/components/ui/skeleton";
import { Textarea } from "~/components/ui/textarea";
import { useAttachment } from "~/hooks";
import { queryKeys } from "~/lib/query";

const DETECTED_TYPES: Array<{ value: DetectedType; label: string }> = [
  { value: "diagram", label: "Diagram" },
  { value: "table", label: "Table" },
  { value: "photo", label: "Photo" },
  { value: "icon", label: "Icon" },
  { value: "decorative", label: "Decorative" },
];

const QUALITY_RATINGS: Array<{ value: QualityRating; label: string }> = [
  { value: "good", label: "Good" },
  { value: "bad", label: "Bad" },
];

export default function AttachmentDetailPage() {
  const { id, attachmentId } = useParams<{ id: string; attachmentId: string }>();
  const queryClient = useQueryClient();
  const { attachment, isLoading, error } = useAttachment(attachmentId);

  // Form state
  const [description, setDescription] = useState("");
  const [detectedType, setDetectedType] = useState<DetectedType | undefined>();
  const [quality, setQuality] = useState<QualityRating | undefined>();

  // Populate form when attachment loads
  useEffect(() => {
    if (attachment) {
      setDescription(attachment.description ?? "");
      setDetectedType(attachment.detected_type ?? undefined);
      setQuality(attachment.is_good_quality ?? undefined);
    }
  }, [attachment]);

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: (data: AttachmentUpdate) => api.attachments.update(attachmentId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.attachments.detail(attachmentId!),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.attachments.byGame(id!),
      });
    },
  });

  // Reprocess mutation
  const reprocessMutation = useMutation({
    mutationFn: () => api.attachments.reprocess(attachmentId!),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.attachments.detail(attachmentId!),
      });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const data: AttachmentUpdate = {};

    const desc = description || null;
    if (desc !== attachment?.description) data.description = desc;

    if (detectedType !== attachment?.detected_type) data.detected_type = detectedType ?? null;

    if (quality !== attachment?.is_good_quality) data.is_good_quality = quality ?? null;

    if (Object.keys(data).length > 0) {
      updateMutation.mutate(data);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid lg:grid-cols-2 gap-6">
          <Skeleton className="aspect-square max-h-[500px]" />
          <Card>
            <CardContent className="pt-6 space-y-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  if (error || !attachment) {
    return (
      <div className="max-w-2xl">
        <Card className="border-destructive">
          <CardContent className="pt-6">
            <p className="text-destructive">{error || "Attachment not found"}</p>
            <Button asChild className="mt-4">
              <Link to={`/admin/games/${id}/attachments`}>Back to Attachments</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{attachment.caption || "Attachment"}</h1>
          <p className="text-muted-foreground">
            {attachment.original_filename || `Page ${attachment.page_number ?? "?"}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => reprocessMutation.mutate()}
            disabled={reprocessMutation.isPending}
          >
            {reprocessMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" />
            )}
            Reprocess
          </Button>
        </div>
      </div>

      {reprocessMutation.error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {reprocessMutation.error.message}
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Image preview */}
        <Card>
          <CardContent className="p-4">
            <img
              src={attachment.url}
              alt={attachment.caption || "Attachment"}
              className="w-full max-h-[500px] object-contain rounded-lg"
            />
          </CardContent>
        </Card>

        {/* Edit form */}
        <div className="space-y-6">
          {/* Metadata */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Metadata</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <dt className="text-muted-foreground">Page</dt>
                  <dd className="font-medium">{attachment.page_number ?? "-"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Dimensions</dt>
                  <dd className="font-medium">
                    {attachment.width && attachment.height
                      ? `${attachment.width} x ${attachment.height}`
                      : "-"}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Type</dt>
                  <dd>
                    {attachment.detected_type ? (
                      <Badge variant="secondary">{attachment.detected_type}</Badge>
                    ) : (
                      "-"
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Quality</dt>
                  <dd>
                    {attachment.is_good_quality ? (
                      <Badge
                        variant={attachment.is_good_quality === "good" ? "default" : "destructive"}
                      >
                        {attachment.is_good_quality}
                      </Badge>
                    ) : (
                      "-"
                    )}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-muted-foreground mb-1">Resource</dt>
                  <dd>
                    <Link
                      to={`/admin/games/${id}/resources/${attachment.resource_id}`}
                      className="inline-flex items-center gap-1 text-blue-600 hover:underline"
                    >
                      <FileText className="h-4 w-4" />
                      View Resource
                    </Link>
                  </dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          {/* Edit form */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Edit Details</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="description">Description</Label>
                  <Textarea
                    id="description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Describe what this image shows..."
                    rows={3}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="detectedType">Type</Label>
                  <Select
                    value={detectedType ?? ""}
                    onValueChange={(v) => setDetectedType(v ? (v as DetectedType) : undefined)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select type..." />
                    </SelectTrigger>
                    <SelectContent>
                      {DETECTED_TYPES.map((type) => (
                        <SelectItem key={type.value} value={type.value}>
                          {type.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="quality">Quality Rating</Label>
                  <Select
                    value={quality ?? ""}
                    onValueChange={(v) => setQuality(v ? (v as QualityRating) : undefined)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Rate quality..." />
                    </SelectTrigger>
                    <SelectContent>
                      {QUALITY_RATINGS.map((rating) => (
                        <SelectItem key={rating.value} value={rating.value}>
                          {rating.label}
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

          {/* OCR text if available */}
          {attachment.ocr_text && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">OCR Text</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="whitespace-pre-wrap text-sm bg-muted p-4 rounded-lg max-h-48 overflow-y-auto">
                  {attachment.ocr_text}
                </pre>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
