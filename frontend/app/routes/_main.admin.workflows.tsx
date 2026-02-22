import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  CheckCircle,
  Clock,
  ExternalLink,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "~/api/client";
import type { WorkflowRun, WorkflowStatus } from "~/api/types";
import { ConnectionWarning } from "~/components/connection-warning";
import { PageHeader } from "~/components/page-header";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
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
import { isNetworkError } from "~/lib/api-errors";
import { getErrorSuggestion } from "~/lib/error-helpers";
import { queryKeys } from "~/lib/query";

const STATUS_FILTERS: Array<{ value: WorkflowStatus | "all"; label: string }> = [
  { value: "all", label: "All" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

function statusVariant(
  status: WorkflowStatus,
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "completed":
      return "default";
    case "running":
      return "secondary";
    case "queued":
      return "outline";
    case "failed":
    case "cancelled":
      return "destructive";
    default:
      return "outline";
  }
}

function StatusIcon({ status }: { status: WorkflowStatus }) {
  switch (status) {
    case "completed":
      return <CheckCircle className="h-4 w-4 text-green-500" />;
    case "running":
      return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />;
    case "queued":
      return <Clock className="h-4 w-4 text-yellow-500" />;
    case "failed":
      return <AlertCircle className="h-4 w-4 text-red-500" />;
    case "cancelled":
      return <XCircle className="h-4 w-4 text-gray-500" />;
    default:
      return null;
  }
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  return date.toLocaleString();
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "-";
  const startDate = new Date(start);
  const endDate = end ? new Date(end) : new Date();
  const durationMs = endDate.getTime() - startDate.getTime();

  if (durationMs < 1000) return `${durationMs}ms`;
  if (durationMs < 60000) return `${Math.round(durationMs / 1000)}s`;
  return `${Math.round(durationMs / 60000)}m`;
}

function formatTimeAgo(dateStr: string | null): string {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  return `${diffDay}d ago`;
}

function formatWorkflowTime(workflow: WorkflowRun): { label: string; detail: string } {
  if (workflow.status === "running" || workflow.status === "queued") {
    const timeAgo = formatTimeAgo(workflow.started_at || workflow.created_at);
    const duration = workflow.started_at ? formatDuration(workflow.started_at, null) : "";
    return {
      label: workflow.started_at ? `Running ${duration}` : "Queued",
      detail: `Started ${timeAgo}`,
    };
  }
  // Completed, failed, or cancelled
  const timeAgo = formatTimeAgo(workflow.completed_at);
  const duration = formatDuration(workflow.started_at, workflow.completed_at);
  return {
    label: timeAgo,
    detail: duration !== "-" ? `Took ${duration}` : "",
  };
}

export default function WorkflowsPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | "all">("all");
  const [selectedWorkflow, setSelectedWorkflow] = useState<WorkflowRun | null>(null);

  // Poll interval for active workflows
  const WORKFLOW_POLL_INTERVAL = 3000; // 3 seconds

  const {
    data: workflows,
    isLoading,
    error,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: [...queryKeys.workflows.all, statusFilter],
    queryFn: () =>
      api.workflows.list({
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: 50,
      }),
    // Poll when any workflow is running or queued
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const hasActive = data.some((w) => w.status === "running" || w.status === "queued");
      return hasActive ? WORKFLOW_POLL_INTERVAL : false;
    },
  });

  const retryMutation = useMutation({
    mutationFn: (runId: string) => api.workflows.retry(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.all });
      toast({
        description: "Workflow retry started",
        variant: "success",
      });
    },
    onError: (err: Error) => {
      toast({
        title: "Retry failed",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (runId: string) => api.workflows.cancel(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.all });
      toast({
        description: "Workflow cancelled",
        variant: "success",
      });
    },
    onError: (err: Error) => {
      toast({
        title: "Cancel failed",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflows"
        description="Monitor background processing tasks"
        actions={
          <div className="flex items-center gap-2">
            <Select
              value={statusFilter}
              onValueChange={(v) => setStatusFilter(v as WorkflowStatus | "all")}
            >
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_FILTERS.map((filter) => (
                  <SelectItem key={filter.value} value={filter.value}>
                    {filter.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => queryClient.invalidateQueries({ queryKey: queryKeys.workflows.all })}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        }
      />

      <div className="space-y-4">
        {/* Show connection warning if we have stale data and a network error */}
        {workflows && isNetworkError(error) && (
          <ConnectionWarning onRetry={() => refetch()} isRetrying={isFetching} />
        )}

        {/* Show error only when we have no data */}
        {!workflows && error ? (
          <div className="rounded-md bg-destructive/10 p-4 text-destructive">
            <p className="font-medium">
              {isNetworkError(error) ? "Connection error" : "Error loading workflows"}
            </p>
            <p className="text-sm mt-1">
              {isNetworkError(error)
                ? "Unable to load workflows. Check your connection and try again."
                : (error as Error).message}
            </p>
            <Button
              onClick={() => refetch()}
              className="mt-4"
              variant="outline"
              disabled={isFetching}
            >
              {isFetching ? "Retrying..." : "Retry"}
            </Button>
          </div>
        ) : isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : !workflows || workflows.length === 0 ? (
          <div className="text-center py-12">
            <Activity className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
            <p className="text-muted-foreground">
              {statusFilter !== "all" ? `No ${statusFilter} workflows` : "No workflows yet"}
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Workflow</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Time</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workflows.map((workflow) => {
                const time = formatWorkflowTime(workflow);
                return (
                  <TableRow key={workflow.id}>
                    <TableCell>
                      <div className="font-medium">{workflow.workflow_name}</div>
                      <div className="text-xs text-muted-foreground truncate max-w-[200px]">
                        {workflow.run_id}
                      </div>
                      {workflow.resource_id && workflow.game_id && (
                        <Link
                          to={`/admin/games/${workflow.game_id}/resources/${workflow.resource_id}`}
                          className="flex items-center gap-1 text-xs text-primary hover:underline mt-1"
                        >
                          <ExternalLink className="h-3 w-3" />
                          View resource
                        </Link>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <StatusIcon status={workflow.status} />
                        <Badge variant={statusVariant(workflow.status)}>{workflow.status}</Badge>
                      </div>
                      {workflow.stage_label && workflow.status === "running" && (
                        <div className="text-xs text-muted-foreground mt-1">
                          {workflow.stage_label}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">
                      <div>{time.label}</div>
                      {time.detail && (
                        <div className="text-xs text-muted-foreground">{time.detail}</div>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Dialog>
                          <DialogTrigger asChild>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => setSelectedWorkflow(workflow)}
                            >
                              Details
                            </Button>
                          </DialogTrigger>
                          <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
                            <DialogHeader>
                              <DialogTitle>{selectedWorkflow?.workflow_name}</DialogTitle>
                              <DialogDescription>{selectedWorkflow?.run_id}</DialogDescription>
                            </DialogHeader>
                            {selectedWorkflow && (
                              <div className="space-y-4">
                                <div className="grid grid-cols-2 gap-4 text-sm">
                                  <div>
                                    <span className="text-muted-foreground">Status:</span>
                                    <Badge
                                      className="ml-2"
                                      variant={statusVariant(selectedWorkflow.status)}
                                    >
                                      {selectedWorkflow.status}
                                    </Badge>
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground">Duration:</span>
                                    <span className="ml-2">
                                      {formatDuration(
                                        selectedWorkflow.started_at,
                                        selectedWorkflow.completed_at,
                                      )}
                                    </span>
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground">Started:</span>
                                    <span className="ml-2">
                                      {formatDate(selectedWorkflow.started_at)}
                                    </span>
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground">Completed:</span>
                                    <span className="ml-2">
                                      {formatDate(selectedWorkflow.completed_at)}
                                    </span>
                                  </div>
                                  {selectedWorkflow.resource_id && selectedWorkflow.game_id && (
                                    <div className="col-span-2">
                                      <span className="text-muted-foreground">Resource:</span>
                                      <Link
                                        to={`/admin/games/${selectedWorkflow.game_id}/resources/${selectedWorkflow.resource_id}`}
                                        className="ml-2 text-primary hover:underline inline-flex items-center gap-1"
                                      >
                                        View resource
                                        <ExternalLink className="h-3 w-3" />
                                      </Link>
                                    </div>
                                  )}
                                </div>

                                {selectedWorkflow.error &&
                                  (() => {
                                    // Get suggestion from pattern-based helper or from backend extra_data
                                    const patternSuggestion = getErrorSuggestion(
                                      selectedWorkflow.error,
                                    );
                                    const backendSuggestion =
                                      (selectedWorkflow.extra_data?.suggestion as string) || null;
                                    // Prefer backend suggestion as it's more specific
                                    const suggestionText =
                                      backendSuggestion || patternSuggestion?.suggestion;
                                    return (
                                      <div className="rounded-md bg-destructive/10 p-4 space-y-2">
                                        <div className="font-medium text-destructive">
                                          {patternSuggestion?.title ?? "Error"}
                                          {selectedWorkflow.error_code &&
                                            ` (${selectedWorkflow.error_code})`}
                                        </div>
                                        <pre className="text-sm text-destructive whitespace-pre-wrap">
                                          {selectedWorkflow.error}
                                        </pre>
                                        {suggestionText && (
                                          <div className="text-sm text-muted-foreground border-t border-destructive/20 pt-2 mt-2">
                                            <strong>Suggestion:</strong> {suggestionText}
                                          </div>
                                        )}
                                      </div>
                                    );
                                  })()}

                                {selectedWorkflow.input_data && (
                                  <div>
                                    <div className="font-medium mb-1">Input Data</div>
                                    <pre className="text-xs bg-muted p-4 rounded-lg overflow-x-auto">
                                      {JSON.stringify(selectedWorkflow.input_data, null, 2)}
                                    </pre>
                                  </div>
                                )}

                                {selectedWorkflow.output_data && (
                                  <div>
                                    <div className="font-medium mb-1">Output Data</div>
                                    <pre className="text-xs bg-muted p-4 rounded-lg overflow-x-auto max-h-48">
                                      {JSON.stringify(selectedWorkflow.output_data, null, 2)}
                                    </pre>
                                  </div>
                                )}
                              </div>
                            )}
                          </DialogContent>
                        </Dialog>

                        {workflow.status === "failed" && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => retryMutation.mutate(workflow.run_id)}
                            disabled={retryMutation.isPending}
                          >
                            {retryMutation.isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <RefreshCw className="h-4 w-4" />
                            )}
                          </Button>
                        )}

                        {(workflow.status === "queued" || workflow.status === "running") && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => cancelMutation.mutate(workflow.run_id)}
                            disabled={cancelMutation.isPending}
                          >
                            {cancelMutation.isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <XCircle className="h-4 w-4 text-destructive" />
                            )}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
