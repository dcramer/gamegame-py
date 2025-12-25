import { Filter, Image } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import type { DetectedType } from "~/api/types";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { Skeleton } from "~/components/ui/skeleton";
import { useAttachmentsByGame, useGame } from "~/hooks";

const DETECTED_TYPES: Array<{ value: DetectedType | "all"; label: string }> = [
  { value: "all", label: "All Types" },
  { value: "diagram", label: "Diagrams" },
  { value: "table", label: "Tables" },
  { value: "photo", label: "Photos" },
  { value: "icon", label: "Icons" },
  { value: "decorative", label: "Decorative" },
];

export default function AttachmentsPage() {
  const { id } = useParams<{ id: string }>();
  const { game, isLoading: gameLoading } = useGame(id);
  const [filter, setFilter] = useState<DetectedType | "all">("all");

  const {
    attachments,
    isLoading: attachmentsLoading,
    error,
  } = useAttachmentsByGame(id, {
    detectedType: filter === "all" ? undefined : filter,
  });

  const isLoading = gameLoading || attachmentsLoading;

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-10 w-32" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {Array.from({ length: 12 }).map((_, i) => (
            <Skeleton key={i} className="aspect-square rounded" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Attachments</h1>
          <p className="text-muted-foreground">{game?.name} - Extracted images and diagrams</p>
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <Select value={filter} onValueChange={(v) => setFilter(v as DetectedType | "all")}>
            <SelectTrigger className="w-40">
              <SelectValue />
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
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <Image className="h-5 w-5" />
            {attachments.length} {attachments.length === 1 ? "Attachment" : "Attachments"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="rounded-md bg-destructive/10 p-4 text-destructive">{error}</div>
          ) : attachments.length === 0 ? (
            <div className="text-center py-12">
              <Image className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-muted-foreground">
                {filter !== "all"
                  ? `No ${filter} attachments found`
                  : "No attachments yet. Upload a PDF to extract images."}
              </p>
              {filter !== "all" && (
                <Button variant="link" onClick={() => setFilter("all")} className="mt-2">
                  Clear filter
                </Button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
              {attachments.map((attachment) => (
                <Link
                  key={attachment.id}
                  to={`/admin/games/${id}/attachments/${attachment.id}`}
                  className="group relative"
                >
                  <div className="aspect-square overflow-hidden rounded-lg border border-border bg-muted">
                    <img
                      src={attachment.url}
                      alt={attachment.caption || "Attachment"}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                    />
                  </div>
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 rounded-lg transition-colors" />
                  <div className="absolute bottom-0 left-0 right-0 p-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <div className="flex gap-1 flex-wrap">
                      {attachment.detected_type && (
                        <Badge variant="secondary" className="text-xs">
                          {attachment.detected_type}
                        </Badge>
                      )}
                      {attachment.page_number && (
                        <Badge variant="outline" className="text-xs bg-background/80">
                          p. {attachment.page_number}
                        </Badge>
                      )}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
