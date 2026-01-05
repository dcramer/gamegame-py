import { ArrowLeft, FileText } from "lucide-react";
import { Link, useParams } from "react-router";
import { ConnectionWarning } from "~/components/connection-warning";
import { PageHeader } from "~/components/page-header";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Skeleton } from "~/components/ui/skeleton";
import { useGame, useResource, useSegment } from "~/hooks";
import { isNetworkError, isNotFoundError } from "~/lib/api-errors";

function formatPageRange(pageStart: number | null, pageEnd: number | null): string {
  if (pageStart && pageEnd) {
    if (pageStart === pageEnd) {
      return `p. ${pageStart}`;
    }
    return `pp. ${pageStart}-${pageEnd}`;
  }
  if (pageStart) {
    return `p. ${pageStart}`;
  }
  return "-";
}

export default function SegmentDetailPage() {
  const { id, resourceId, segmentId } = useParams<{
    id: string;
    resourceId: string;
    segmentId: string;
  }>();
  const { game } = useGame(id);
  const { resource } = useResource(resourceId);
  const { segment, isLoading, error, isFetching, refetch } = useSegment(segmentId);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-9 w-64" />
        </div>
        <div className="grid lg:grid-cols-3 gap-6">
          <Skeleton className="h-64" />
          <Skeleton className="h-96 lg:col-span-2" />
        </div>
      </div>
    );
  }

  // True 404: no data and got a not-found error
  if (!segment && isNotFoundError(error)) {
    return (
      <div className="rounded-md bg-destructive/10 p-6 text-destructive">
        <p className="font-medium">Segment not found</p>
        <p className="text-sm mt-1">The requested segment could not be found.</p>
        <Button asChild className="mt-4" variant="outline">
          <Link to={`/admin/games/${id}/resources/${resourceId}/segments`}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Segments
          </Link>
        </Button>
      </div>
    );
  }

  // No data and network error on initial load
  if (!segment && isNetworkError(error)) {
    return (
      <div className="rounded-md bg-destructive/10 p-6 text-destructive">
        <p className="font-medium">Connection error</p>
        <p className="text-sm mt-1">Unable to load segment. Check your connection and try again.</p>
        <Button onClick={() => refetch()} className="mt-4" variant="outline" disabled={isFetching}>
          {isFetching ? "Retrying..." : "Retry"}
        </Button>
      </div>
    );
  }

  // No data for unknown reason
  if (!segment) {
    return (
      <div className="rounded-md bg-destructive/10 p-6 text-destructive">
        <p className="font-medium">Unable to load segment</p>
        <p className="text-sm mt-1">{error?.message || "An unexpected error occurred."}</p>
        <Button asChild className="mt-4" variant="outline">
          <Link to={`/admin/games/${id}/resources/${resourceId}/segments`}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Segments
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Show connection warning if we have stale data and a network error */}
      {isNetworkError(error) && (
        <ConnectionWarning onRetry={() => refetch()} isRetrying={isFetching} />
      )}

      <PageHeader
        breadcrumbs={[
          { label: "Admin", to: "/admin" },
          { label: game?.name || "Game", to: `/admin/games/${id}` },
          { label: resource?.name || "Resource", to: `/admin/games/${id}/resources/${resourceId}` },
          { label: "Segments", to: `/admin/games/${id}/resources/${resourceId}/segments` },
          { label: segment.title },
        ]}
        title={segment.title}
        stats={segment.hierarchy_path}
      />

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Metadata sidebar */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Metadata
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-4 text-sm">
              <div>
                <dt className="text-muted-foreground">Level</dt>
                <dd className="mt-1">
                  <Badge variant="secondary">H{segment.level}</Badge>
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Pages</dt>
                <dd className="mt-1">{formatPageRange(segment.page_start, segment.page_end)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Word Count</dt>
                <dd className="mt-1">{segment.word_count?.toLocaleString() ?? "-"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Character Count</dt>
                <dd className="mt-1">{segment.char_count?.toLocaleString() ?? "-"}</dd>
              </div>
              {segment.parent_id && (
                <div>
                  <dt className="text-muted-foreground">Parent Segment</dt>
                  <dd className="mt-1">
                    <Link
                      to={`/admin/games/${id}/resources/${resourceId}/segments/${segment.parent_id}`}
                      className="text-blue-600 hover:underline"
                    >
                      View Parent
                    </Link>
                  </dd>
                </div>
              )}
              <div>
                <dt className="text-muted-foreground">Resource</dt>
                <dd className="mt-1">
                  <Link
                    to={`/admin/games/${id}/resources/${resourceId}`}
                    className="text-blue-600 hover:underline"
                  >
                    {resource?.name || "View Resource"}
                  </Link>
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        {/* Content */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg">Content</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap text-sm bg-muted p-4 rounded-lg overflow-auto max-h-[600px] font-mono">
              {segment.content}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
