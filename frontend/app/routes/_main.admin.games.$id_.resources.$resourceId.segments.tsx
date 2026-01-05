import { FileText } from "lucide-react";
import { Link, useParams } from "react-router";
import { Skeleton } from "~/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "~/components/ui/table";
import { useSegmentsByResource } from "~/hooks";

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

export default function SegmentsTab() {
  const { id, resourceId } = useParams<{ id: string; resourceId: string }>();
  const { segments, isLoading, error } = useSegmentsByResource(resourceId);

  if (isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return <div className="rounded-md bg-destructive/10 p-4 text-destructive">{error.message}</div>;
  }

  if (segments.length === 0) {
    return (
      <div className="text-center py-12">
        <FileText className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
        <p className="text-muted-foreground">
          No segments found. The resource may still be processing.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Title</TableHead>
          <TableHead>Hierarchy</TableHead>
          <TableHead>Pages</TableHead>
          <TableHead className="text-right">Words</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {segments.map((segment) => (
          <TableRow key={segment.id}>
            <TableCell className="font-medium">
              <Link
                to={`/admin/games/${id}/resources/${resourceId}/segments/${segment.id}`}
                className="hover:underline flex items-center gap-2"
              >
                <span style={{ paddingLeft: `${(segment.level - 1) * 16}px` }}>
                  {segment.title}
                </span>
              </Link>
            </TableCell>
            <TableCell>
              <span className="text-sm text-muted-foreground">{segment.hierarchy_path}</span>
            </TableCell>
            <TableCell>{formatPageRange(segment.page_start, segment.page_end)}</TableCell>
            <TableCell className="text-right">
              {segment.word_count?.toLocaleString() ?? "-"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
