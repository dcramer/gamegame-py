import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { api } from "~/api/client";
import type { WorkflowRun } from "~/api/types";
import { type ToastHandle, useToast } from "./toast";

const STORAGE_KEY = "gamegame.trackedResources";
const POLL_INTERVAL = 3000;
const MAX_POLLS_WITHOUT_WORKFLOW = 10; // Give up after ~30 seconds if no workflow found

interface TrackedResource {
  resourceId: string;
  title: string;
  toastHandle: ToastHandle;
  lastWorkflowRunId?: string;
  workflowCreatedAt?: number;
  pollsWithoutWorkflow: number;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

// Note: Stage metadata is now computed on the backend (WorkflowRunRead)
// The frontend just reads progress_percent and stage_label from the API response

interface WorkflowTrackingContextValue {
  trackResource: (
    resourceId: string,
    title: string,
    options?: {
      onComplete?: () => void;
      onError?: (error: string) => void;
    },
  ) => void;
  untrackResource: (resourceId: string) => void;
  hasActiveWorkflows: boolean;
}

const WorkflowTrackingContext = createContext<WorkflowTrackingContextValue | null>(null);

interface StoredResource {
  id: string;
  title: string;
}

function getStoredResources(): StoredResource[] {
  if (typeof window === "undefined") return [];
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    // Support both old format (string[]) and new format (StoredResource[])
    return parsed.map((item): StoredResource => {
      if (typeof item === "string") {
        return { id: item, title: "Processing..." };
      }
      return item as StoredResource;
    });
  } catch {
    return [];
  }
}

function saveStoredResources(resources: StoredResource[]) {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(resources));
}

export function WorkflowTrackingProvider({ children }: { children: ReactNode }) {
  const { toast } = useToast();
  const trackedRef = useRef<Map<string, TrackedResource>>(new Map());
  const [hasActiveWorkflows, setHasActiveWorkflows] = useState(false);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const updateTrackedCount = useCallback(() => {
    setHasActiveWorkflows(trackedRef.current.size > 0);
  }, []);

  const persistTrackedResources = useCallback(() => {
    const resources: StoredResource[] = Array.from(trackedRef.current.entries()).map(
      ([id, tracked]) => ({ id, title: tracked.title }),
    );
    saveStoredResources(resources);
  }, []);

  const handleWorkflowUpdate = useCallback(
    (resourceId: string, workflow: WorkflowRun | null) => {
      const tracked = trackedRef.current.get(resourceId);
      if (!tracked) return;

      // No workflow found for this resource
      if (!workflow) {
        tracked.pollsWithoutWorkflow++;

        // If we've polled too many times without finding a workflow, give up
        if (tracked.pollsWithoutWorkflow >= MAX_POLLS_WITHOUT_WORKFLOW) {
          tracked.toastHandle.update({
            title: tracked.title,
            description: "Could not find workflow - it may have completed or failed to start",
            variant: "default",
            progress: undefined,
            duration: 5000,
            actions: undefined,
          });
          trackedRef.current.delete(resourceId);
          persistTrackedResources();
          updateTrackedCount();
        }
        return;
      }

      // Reset counter when we find a workflow
      tracked.pollsWithoutWorkflow = 0;

      // Store the workflow run_id for cancel/retry actions
      tracked.lastWorkflowRunId = workflow.run_id;

      // Store the workflow's created_at for accurate timing
      if (!tracked.workflowCreatedAt && workflow.created_at) {
        tracked.workflowCreatedAt = new Date(workflow.created_at).getTime();
        // Update the toast with the correct createdAt
        tracked.toastHandle.update({
          createdAt: tracked.workflowCreatedAt,
        });
      }

      // Use backend-computed fields directly
      const progress = workflow.progress_percent ?? 0;
      const stageName = workflow.stage_label;

      if (workflow.status === "running" || workflow.status === "queued") {
        tracked.toastHandle.update({
          title: tracked.title,
          description: stageName ?? (workflow.status === "queued" ? "Queued..." : "Processing..."),
          variant: "info",
          progress,
          duration: 0, // Don't auto-dismiss
          actions: [
            {
              label: "Cancel",
              onClick: async () => {
                try {
                  await api.workflows.cancel(workflow.run_id);
                } catch (err) {
                  console.error("Failed to cancel workflow:", err);
                  tracked.toastHandle.update({
                    description: "Failed to cancel",
                    variant: "destructive",
                    duration: 3000,
                  });
                }
              },
            },
          ],
        });
      } else if (workflow.status === "completed") {
        tracked.toastHandle.update({
          title: tracked.title,
          description: "Completed successfully",
          variant: "success",
          progress: 100,
          duration: 5000,
          actions: undefined,
          completedAt: workflow.completed_at
            ? new Date(workflow.completed_at).getTime()
            : Date.now(),
        });
        trackedRef.current.delete(resourceId);
        persistTrackedResources();
        updateTrackedCount();
        tracked.onComplete?.();
      } else if (workflow.status === "failed") {
        const errorMsg = workflow.error || "Unknown error";
        const retryInfo = workflow.can_retry
          ? ""
          : ` (retry limit reached: ${workflow.retry_count}/3)`;

        // Build actions based on whether retry is available
        const actions = [];
        if (workflow.can_retry) {
          actions.push({
            label: "Retry",
            onClick: async () => {
              // Update toast to show retrying
              tracked.toastHandle.update({
                description: "Retrying...",
                variant: "info",
                progress: 0,
                actions: undefined,
                completedAt: undefined,
              });

              try {
                await api.workflows.retry(workflow.run_id);
                // Reset counter so polling will find the new workflow
                tracked.pollsWithoutWorkflow = 0;
                // Re-add to tracking if it was removed
                if (!trackedRef.current.has(resourceId)) {
                  trackedRef.current.set(resourceId, tracked);
                  persistTrackedResources();
                  updateTrackedCount();
                }
              } catch (err) {
                console.error("Failed to retry workflow:", err);
                tracked.toastHandle.update({
                  description: "Retry failed - please try again",
                  variant: "destructive",
                  duration: 0,
                  actions: [
                    {
                      label: "Dismiss",
                      onClick: () => {
                        tracked.toastHandle.dismiss();
                        trackedRef.current.delete(resourceId);
                        persistTrackedResources();
                        updateTrackedCount();
                      },
                    },
                  ],
                });
              }
            },
          });
        }
        actions.push({
          label: "Dismiss",
          onClick: () => {
            tracked.toastHandle.dismiss();
            trackedRef.current.delete(resourceId);
            persistTrackedResources();
            updateTrackedCount();
          },
        });

        tracked.toastHandle.update({
          title: tracked.title,
          description: `Failed: ${errorMsg}${retryInfo}`,
          variant: "destructive",
          progress: undefined,
          duration: 0, // Don't auto-dismiss errors
          actions,
          completedAt: workflow.completed_at
            ? new Date(workflow.completed_at).getTime()
            : Date.now(),
        });
        // Don't delete from tracking - keep it so user can retry
        tracked.onError?.(errorMsg);
      } else if (workflow.status === "cancelled") {
        tracked.toastHandle.update({
          title: tracked.title,
          description: "Cancelled",
          variant: "default",
          progress: undefined,
          duration: 5000,
          actions: [
            {
              label: "Dismiss",
              onClick: () => {
                tracked.toastHandle.dismiss();
              },
            },
          ],
          completedAt: workflow.completed_at
            ? new Date(workflow.completed_at).getTime()
            : Date.now(),
        });
        trackedRef.current.delete(resourceId);
        persistTrackedResources();
        updateTrackedCount();
      }
    },
    [persistTrackedResources, updateTrackedCount],
  );

  const pollWorkflows = useCallback(async () => {
    const resourceIds = Array.from(trackedRef.current.keys());
    if (resourceIds.length === 0) return;

    try {
      // Only fetch workflows for the resources we're tracking
      const workflows = await api.workflows.list({
        resourceIds,
        limit: resourceIds.length * 3, // Buffer for retries
      });

      // Build a map of resource_id to most recent active workflow (or most recent overall)
      // API already returns sorted by created_at desc
      const workflowByResource = new Map<string, WorkflowRun>();
      for (const workflow of workflows) {
        if (workflow.resource_id) {
          const existing = workflowByResource.get(workflow.resource_id);
          const isActive = workflow.status === "running" || workflow.status === "queued";
          const existingIsActive =
            existing && (existing.status === "running" || existing.status === "queued");

          // Prefer: active over inactive, then most recent within same category
          if (!existing || (isActive && !existingIsActive)) {
            workflowByResource.set(workflow.resource_id, workflow);
          }
        }
      }

      for (const resourceId of resourceIds) {
        const workflow = workflowByResource.get(resourceId);
        handleWorkflowUpdate(resourceId, workflow ?? null);
      }
    } catch (error) {
      console.error("Failed to poll workflows:", error);
    }
  }, [handleWorkflowUpdate]);

  // Set up polling
  useEffect(() => {
    if (hasActiveWorkflows) {
      // Poll immediately
      void pollWorkflows();

      // Set up interval
      pollIntervalRef.current = setInterval(() => {
        void pollWorkflows();
      }, POLL_INTERVAL);

      return () => {
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
      };
    }
  }, [hasActiveWorkflows, pollWorkflows]);

  // NOTE: We intentionally don't add a beforeunload warning here.
  // Workflows continue on the backend regardless of the page being open,
  // and tracking state is persisted in session storage and rehydrated on reload.

  // Hydrate from session storage on mount
  useEffect(() => {
    let isMounted = true;
    const storedResources = getStoredResources();
    if (storedResources.length === 0) return;

    // Fetch current status and create toasts for active resources
    (async () => {
      try {
        // Only fetch workflows for stored resources
        const resourceIds = storedResources.map((r) => r.id);
        const workflows = await api.workflows.list({
          resourceIds,
          limit: resourceIds.length * 3,
        });

        // Check if still mounted before updating state
        if (!isMounted) return;

        // Build a map of resource_id to most recent active workflow
        // API already returns sorted by created_at desc
        const activeWorkflowByResource = new Map<string, WorkflowRun>();
        for (const workflow of workflows) {
          if (workflow.resource_id) {
            const existing = activeWorkflowByResource.get(workflow.resource_id);
            const isActive = workflow.status === "running" || workflow.status === "queued";

            // Only track active workflows, prefer most recent (already sorted)
            if (isActive && !existing) {
              activeWorkflowByResource.set(workflow.resource_id, workflow);
            }
          }
        }

        for (const stored of storedResources) {
          const workflow = activeWorkflowByResource.get(stored.id);
          if (workflow) {
            // Get title from stored data, or use backend-computed resource_name
            const title =
              stored.title !== "Processing..."
                ? stored.title
                : (workflow.resource_name ?? "Processing...");

            // Re-create toast for this resource
            const workflowCreatedAt = new Date(workflow.created_at).getTime();
            const handle = toast({
              title,
              description: "Resuming tracking...",
              variant: "info",
              duration: 0,
              createdAt: workflowCreatedAt,
            });

            trackedRef.current.set(stored.id, {
              resourceId: stored.id,
              title,
              toastHandle: handle,
              lastWorkflowRunId: workflow.run_id,
              workflowCreatedAt,
              pollsWithoutWorkflow: 0,
            });

            handleWorkflowUpdate(stored.id, workflow);
          }
        }

        // Clean up storage to only include still-active resources
        persistTrackedResources();
        updateTrackedCount();
      } catch (error) {
        console.error("Failed to hydrate workflows:", error);
        // Clear storage on error
        if (isMounted) {
          saveStoredResources([]);
        }
      }
    })();

    return () => {
      isMounted = false;
    };
  }, [toast, handleWorkflowUpdate, updateTrackedCount, persistTrackedResources]);

  useEffect(() => {
    return () => {
      trackedRef.current.clear();
    };
  }, []);

  const trackResource = useCallback(
    (
      resourceId: string,
      title: string,
      options?: {
        onComplete?: () => void;
        onError?: (error: string) => void;
      },
    ) => {
      // Check if already tracking
      if (trackedRef.current.has(resourceId)) {
        return;
      }

      const handle = toast({
        title,
        description: "Starting...",
        variant: "info",
        duration: 0,
        progress: 0,
      });

      trackedRef.current.set(resourceId, {
        resourceId,
        title,
        toastHandle: handle,
        pollsWithoutWorkflow: 0,
        onComplete: options?.onComplete,
        onError: options?.onError,
      });

      persistTrackedResources();
      updateTrackedCount();

      // Poll immediately to get current status
      void pollWorkflows();
    },
    [toast, persistTrackedResources, updateTrackedCount, pollWorkflows],
  );

  const untrackResource = useCallback(
    (resourceId: string) => {
      const tracked = trackedRef.current.get(resourceId);
      if (tracked) {
        tracked.toastHandle.dismiss();
        trackedRef.current.delete(resourceId);
        persistTrackedResources();
        updateTrackedCount();
      }
    },
    [persistTrackedResources, updateTrackedCount],
  );

  return (
    <WorkflowTrackingContext.Provider
      value={{ trackResource, untrackResource, hasActiveWorkflows }}
    >
      {children}
    </WorkflowTrackingContext.Provider>
  );
}

export function useWorkflowTracking() {
  const context = useContext(WorkflowTrackingContext);
  if (!context) {
    throw new Error("useWorkflowTracking must be used within a WorkflowTrackingProvider");
  }
  return context;
}
