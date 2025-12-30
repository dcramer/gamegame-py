import { Check, FileText, Image, Loader2, Search, Sparkles, Tag } from "lucide-react";
import type { ProcessingStage, ResourceStatus } from "~/api/types";
import { cn } from "~/lib/utils";

interface ProcessingTimelineProps {
  currentStage: ProcessingStage | null;
  status: ResourceStatus;
  className?: string;
}

const STAGES: Array<{
  id: ProcessingStage;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { id: "ingest", label: "Extract", icon: FileText },
  { id: "vision", label: "Analyze", icon: Image },
  { id: "cleanup", label: "Clean", icon: Sparkles },
  { id: "metadata", label: "Metadata", icon: Tag },
  { id: "embed", label: "Index", icon: Search },
  { id: "finalize", label: "Complete", icon: Check },
];

function getStageStatus(
  stageId: ProcessingStage,
  currentStage: ProcessingStage | null,
  resourceStatus: ResourceStatus,
): "completed" | "current" | "pending" | "error" {
  if (resourceStatus === "completed") {
    return "completed";
  }

  if (resourceStatus === "failed") {
    const stageIndex = STAGES.findIndex((s) => s.id === stageId);
    const currentIndex = currentStage ? STAGES.findIndex((s) => s.id === currentStage) : -1;

    if (stageIndex < currentIndex) {
      return "completed";
    }
    if (stageIndex === currentIndex) {
      return "error";
    }
    return "pending";
  }

  if (!currentStage) {
    return resourceStatus === "queued" ? "pending" : "completed";
  }

  const stageIndex = STAGES.findIndex((s) => s.id === stageId);
  const currentIndex = STAGES.findIndex((s) => s.id === currentStage);

  if (stageIndex < currentIndex) {
    return "completed";
  }
  if (stageIndex === currentIndex) {
    return "current";
  }
  return "pending";
}

export function ProcessingTimeline({ currentStage, status, className }: ProcessingTimelineProps) {
  return (
    <div className={cn("flex items-center justify-between gap-2", className)}>
      {STAGES.map((stage, index) => {
        const stageStatus = getStageStatus(stage.id, currentStage, status);
        const Icon = stage.icon;
        const isLast = index === STAGES.length - 1;

        return (
          <div key={stage.id} className="flex items-center flex-1">
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full border-2 transition-colors",
                  stageStatus === "completed" && "border-green-500 bg-green-500 text-white",
                  stageStatus === "current" && "border-blue-500 bg-blue-500 text-white",
                  stageStatus === "error" && "border-red-500 bg-red-500 text-white",
                  stageStatus === "pending" &&
                    "border-muted-foreground/30 text-muted-foreground/50",
                )}
              >
                {stageStatus === "current" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : stageStatus === "completed" ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <Icon className="h-4 w-4" />
                )}
              </div>
              <span
                className={cn(
                  "mt-1 text-xs font-medium",
                  stageStatus === "completed" && "text-green-500",
                  stageStatus === "current" && "text-blue-500",
                  stageStatus === "error" && "text-red-500",
                  stageStatus === "pending" && "text-muted-foreground/50",
                )}
              >
                {stage.label}
              </span>
            </div>
            {!isLast && (
              <div
                className={cn(
                  "flex-1 h-0.5 mx-2",
                  stageStatus === "completed" && "bg-green-500",
                  stageStatus === "current" && "bg-blue-500",
                  stageStatus === "error" && "bg-red-500",
                  stageStatus === "pending" && "bg-muted-foreground/20",
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
