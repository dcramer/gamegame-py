import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { Link, Outlet, useParams } from "react-router";
import { api } from "~/api/client";
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
import { queryKeys } from "~/lib/query";

/**
 * Layout for game detail pages with tabs navigation.
 * Shows: PageHeader + Tabs (Details / Resources / Attachments)
 */
export default function GameLayout() {
  const { id } = useParams<{ id: string }>();

  const { data: game, isLoading: gameLoading } = useQuery({
    queryKey: queryKeys.games.detail(id!),
    queryFn: () => api.games.get(id!),
    enabled: !!id,
  });

  const { data: resources } = useQuery({
    queryKey: queryKeys.resources.list(id!),
    queryFn: () => api.resources.list(id!),
    enabled: !!id,
  });

  const { data: attachments } = useQuery({
    queryKey: queryKeys.attachments.byGame(id!),
    queryFn: () => api.attachments.listForGame(id!),
    enabled: !!id,
  });

  if (gameLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <Skeleton className="h-9 w-64" />
            <Skeleton className="h-5 w-48" />
          </div>
        </div>
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!game) {
    return (
      <div className="rounded-md bg-destructive/10 p-6 text-destructive">
        <p className="font-medium">Game not found</p>
        <p className="text-sm mt-1">The requested game could not be found.</p>
        <Button asChild variant="outline" className="mt-4">
          <Link to="/admin">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Games
          </Link>
        </Button>
      </div>
    );
  }

  const resourceCount = resources?.length ?? game.resource_count ?? 0;
  const attachmentCount = attachments?.length ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Admin", to: "/admin" }, { label: game.name }]}
        title={
          <div className="flex items-center gap-4">
            {game.image_url && (
              <img
                src={game.image_url}
                alt={game.name}
                className="w-12 h-12 object-cover rounded-lg"
              />
            )}
            <span>{game.name}</span>
          </div>
        }
        stats={game.year ? `${game.year}` : undefined}
        actions={
          game.bgg_url ? (
            <Button variant="outline" size="sm" asChild>
              <a href={game.bgg_url} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="mr-2 h-4 w-4" />
                BoardGameGeek
              </a>
            </Button>
          ) : undefined
        }
      />

      <NavigationTabs>
        <NavigationTabsList>
          <NavigationTabsLink to={`/admin/games/${id}`} end>
            Details
          </NavigationTabsLink>
          <NavigationTabsLink to={`/admin/games/${id}/resources`}>
            Resources
            {resourceCount > 0 && <NavigationTabsBadge>{resourceCount}</NavigationTabsBadge>}
          </NavigationTabsLink>
          <NavigationTabsLink to={`/admin/games/${id}/attachments`}>
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
