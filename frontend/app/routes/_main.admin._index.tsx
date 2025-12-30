import { Gamepad2, Plus } from "lucide-react";
import { Link } from "react-router";
import { PageHeader } from "~/components/page-header";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Skeleton } from "~/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "~/components/ui/table";
import { useGames } from "~/hooks";

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

export function meta() {
  return [{ title: "Admin Dashboard - GameGame" }];
}

export default function AdminDashboard() {
  const { games, isLoading, error } = useGames();

  const totalResources = games.reduce((sum, g) => sum + (g.resource_count ?? 0), 0);
  const gamesWithResources = games.filter((g) => (g.resource_count ?? 0) > 0).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Manage your games and resources"
        actions={
          <Button asChild>
            <Link to="/admin/games/new">
              <Plus className="mr-2 h-4 w-4" />
              Add Game
            </Link>
          </Button>
        }
      />

      {/* Stats cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Games</CardTitle>
            <Gamepad2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {isLoading ? <Skeleton className="h-8 w-16" /> : games.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Resources</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {isLoading ? <Skeleton className="h-8 w-16" /> : totalResources}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">With Resources</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {isLoading ? <Skeleton className="h-8 w-16" /> : gamesWithResources}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Games list */}
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Games</h2>

        {error ? (
          <div className="rounded-md bg-destructive/10 p-4 text-destructive">{error}</div>
        ) : isLoading ? (
          <TableSkeleton />
        ) : games.length === 0 ? (
          <div className="text-center py-8 border rounded-lg">
            <p className="text-muted-foreground mb-4">No games yet</p>
            <Button asChild>
              <Link to="/admin/games/new">
                <Plus className="mr-2 h-4 w-4" />
                Add Your First Game
              </Link>
            </Button>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Year</TableHead>
                <TableHead>Slug</TableHead>
                <TableHead>Resources</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {games.map((game) => (
                <TableRow key={game.id}>
                  <TableCell className="font-medium">
                    <Link to={`/admin/games/${game.id}`} className="hover:underline">
                      {game.name}
                    </Link>
                  </TableCell>
                  <TableCell>{game.year ?? "-"}</TableCell>
                  <TableCell>
                    <code className="text-xs bg-muted px-1 py-0.5 rounded">{game.slug}</code>
                  </TableCell>
                  <TableCell>
                    {(game.resource_count ?? 0) > 0 ? (
                      <Badge variant="secondary">
                        {game.resource_count} {game.resource_count === 1 ? "resource" : "resources"}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground text-sm">None</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/admin/games/${game.id}/resources`}>Resources</Link>
                      </Button>
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`/admin/games/${game.id}`}>Edit</Link>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
