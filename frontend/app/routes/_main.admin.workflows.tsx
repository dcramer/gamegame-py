import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  CheckCircle,
  Clock,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { api } from "~/api/client";
import type { WorkflowRun, WorkflowStatus } from "~/api/types";
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

export default function WorkflowsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | "all">("all");
  const [selectedWorkflow, setSelectedWorkflow] = useState<WorkflowRun | null>(null);

  const {
    data: workflows,
    isLoading,
    error,
  } = useQuery({
    queryKey: [...queryKeys.workflows.all, statusFilter],
    queryFn: () =>
      api.workflows.list({
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: 50,
      }),
  });

  const retryMutation = useMutation({
    mutationFn: (runId: string) => api.workflows.retry(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.all });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (runId: string) => api.workflows.cancel(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.all });
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Workflows</h1>
          <p className="text-muted-foreground">Monitor background processing tasks</p>
        </div>
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
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Activity className="h-5 w-5" />
            {workflows?.length ?? 0} Workflows
          </CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="rounded-md bg-destructive/10 p-4 text-destructive">
              {(error as Error).message}
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
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {workflows.map((workflow) => (
                  <TableRow key={workflow.id}>
                    <TableCell>
                      <div className="font-medium">{workflow.workflow_name}</div>
                      <div className="text-xs text-muted-foreground truncate max-w-[200px]">
                        {workflow.run_id}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <StatusIcon status={workflow.status} />
                        <Badge variant={statusVariant(workflow.status)}>{workflow.status}</Badge>
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">{formatDate(workflow.started_at)}</TableCell>
                    <TableCell className="text-sm">
                      {formatDuration(workflow.started_at, workflow.completed_at)}
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
                                </div>

                                {selectedWorkflow.error && (
                                  <div className="rounded-md bg-destructive/10 p-4">
                                    <div className="font-medium text-destructive mb-1">
                                      Error
                                      {selectedWorkflow.error_code &&
                                        ` (${selectedWorkflow.error_code})`}
                                    </div>
                                    <pre className="text-sm text-destructive whitespace-pre-wrap">
                                      {selectedWorkflow.error}
                                    </pre>
                                  </div>
                                )}

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
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
