import { AlertTriangle, RefreshCw, X } from "lucide-react";
import { useState } from "react";
import { Button } from "~/components/ui/button";

interface ConnectionWarningProps {
  onRetry: () => void;
  isRetrying?: boolean;
}

export function ConnectionWarning({ onRetry, isRetrying }: ConnectionWarningProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  return (
    <div className="rounded-md bg-warning/10 border border-warning/30 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 text-warning flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-warning-foreground">Connection issue</p>
          <p className="text-sm text-muted-foreground mt-1">
            Unable to refresh data. Showing last known state.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={onRetry}
            disabled={isRetrying}
            className="border-warning/30 hover:bg-warning/10"
          >
            <RefreshCw className={`h-4 w-4 ${isRetrying ? "animate-spin" : ""}`} />
          </Button>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="p-1 rounded hover:bg-warning/10"
          >
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>
      </div>
    </div>
  );
}
