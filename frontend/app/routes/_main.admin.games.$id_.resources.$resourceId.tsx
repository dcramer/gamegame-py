import { ArrowLeft, ExternalLink } from "lucide-react";
import { Link, Outlet, useParams } from "react-router";
import { ConnectionWarning } from "~/components/connection-warning";
import { PageHeader } from "~/components/page-header";
import { Button } from "~/components/ui/button";
import {
  NavigationTabs,
  NavigationTabsBadge,
  NavigationTabsContent,
  NavigationTabsLink,
  NavigationTabsList,
} from "~/components/ui/navigation-tabs";
import { Skeleton } from "~/components/ui/skeleton";
import { useAttachmentsByResource, useGame, useResource, useSegmentsByResource } from "~/hooks";
import { isNetworkError, isNotFoundError } from "~/lib/api-errors";

/**
 * Layout for resource detail pages with tabs navigation.
 * Shows: PageHeader + Tabs (Overview / Segments / Attachments)
 */
export default function ResourceLayout() {
  const { id, resourceId } = useParams<{ id: string; resourceId: string }>();
  const { game } = useGame(id);
  const { resource, isLoading, error, isFetching, refetch } = useResource(resourceId);
  const { segments } = useSegmentsByResource(resourceId);
  const { attachments } = useAttachmentsByResource(resourceId);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-9 w-64" />
        </div>
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  // True 404: no data and got a not-found error
  if (!resource && isNotFoundError(error)) {
    return (
      <div className="rounded-md bg-destructive/10 p-6 text-destructive">
        <p className="font-medium">Resource not found</p>
        <p className="text-sm mt-1">The requested resource could not be found.</p>
        <Button asChild className="mt-4" variant="outline">
          <Link to={`/admin/games/${id}/resources`}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Resources
          </Link>
        </Button>
      </div>
    );
  }

  // No data and network error on initial load
  if (!resource && isNetworkError(error)) {
    return (
      <div className="rounded-md bg-destructive/10 p-6 text-destructive">
        <p className="font-medium">Connection error</p>
        <p className="text-sm mt-1">
          Unable to load resource. Check your connection and try again.
        </p>
        <Button onClick={() => refetch()} className="mt-4" variant="outline" disabled={isFetching}>
          {isFetching ? "Retrying..." : "Retry"}
        </Button>
      </div>
    );
  }

  // No data for unknown reason
  if (!resource) {
    return (
      <div className="rounded-md bg-destructive/10 p-6 text-destructive">
        <p className="font-medium">Unable to load resource</p>
        <p className="text-sm mt-1">{error?.message || "An unexpected error occurred."}</p>
        <Button asChild className="mt-4" variant="outline">
          <Link to={`/admin/games/${id}/resources`}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Resources
          </Link>
        </Button>
      </div>
    );
  }

  const segmentCount = segments.length;
  const attachmentCount = attachments.length;

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
          { label: "Resources", to: `/admin/games/${id}/resources` },
          { label: resource.name },
        ]}
        title={resource.name}
        stats={resource.original_filename ?? undefined}
        actions={
          resource.url ? (
            <Button variant="outline" size="sm" asChild>
              <a href={resource.url} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="mr-2 h-4 w-4" />
                View File
              </a>
            </Button>
          ) : undefined
        }
      />

      <NavigationTabs>
        <NavigationTabsList>
          <NavigationTabsLink to={`/admin/games/${id}/resources/${resourceId}`} end>
            Overview
          </NavigationTabsLink>
          <NavigationTabsLink to={`/admin/games/${id}/resources/${resourceId}/segments`}>
            Segments
            {segmentCount > 0 && <NavigationTabsBadge>{segmentCount}</NavigationTabsBadge>}
          </NavigationTabsLink>
          <NavigationTabsLink to={`/admin/games/${id}/resources/${resourceId}/attachments`}>
            Attachments
            {attachmentCount > 0 && <NavigationTabsBadge>{attachmentCount}</NavigationTabsBadge>}
          </NavigationTabsLink>
        </NavigationTabsList>

        <NavigationTabsContent>
          <Outlet />
        </NavigationTabsContent>
      </NavigationTabs>
    </div>
  );
}
