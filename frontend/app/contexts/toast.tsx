import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { Button } from "~/components/ui/button";
import { Progress } from "~/components/ui/progress";
import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "~/components/ui/toast";

function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;

  if (minutes === 0) {
    return `${seconds}s`;
  }

  return `${minutes}m ${remainingSeconds.toString().padStart(2, "0")}s`;
}

function ElapsedTime({ createdAt, completedAt }: { createdAt: number; completedAt?: number }) {
  const [elapsed, setElapsed] = useState(() =>
    completedAt ? completedAt - createdAt : Date.now() - createdAt,
  );

  useEffect(() => {
    // If completedAt is set, don't update the timer
    if (completedAt) {
      setElapsed(completedAt - createdAt);
      return;
    }

    // Update immediately
    setElapsed(Date.now() - createdAt);

    const intervalId = setInterval(() => {
      setElapsed(Date.now() - createdAt);
    }, 1000);
    return () => clearInterval(intervalId);
  }, [createdAt, completedAt]);

  return <span className="text-xs opacity-70 tabular-nums">{formatElapsed(elapsed)}</span>;
}

type ToastVariant = "default" | "destructive" | "success" | "info";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastData {
  id: string;
  title?: string;
  description: string | ReactNode;
  variant?: ToastVariant;
  duration?: number;
  progress?: number;
  createdAt?: number;
  completedAt?: number;
  actions?: ToastAction[];
}

export interface ToastHandle {
  id: string;
  update: (options: Partial<Omit<ToastData, "id">>) => void;
  dismiss: () => void;
}

interface ToastContextType {
  toasts: ToastData[];
  toast: (options: Omit<ToastData, "id">) => ToastHandle;
  dismiss: (id: string) => void;
  dismissAll: () => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

let toastCounter = 0;

export function ToastContextProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastData[]>([]);

  // Centralized timeout tracking - allows dismiss() to clear timeouts for any toast
  const timeoutsRef = useRef<Map<string, Set<ReturnType<typeof setTimeout>>>>(new Map());

  // Clear all timeouts for a specific toast
  const clearTimeoutsForToast = useCallback((id: string) => {
    const timeouts = timeoutsRef.current.get(id);
    if (timeouts) {
      for (const t of timeouts) {
        clearTimeout(t);
      }
      timeouts.clear();
      timeoutsRef.current.delete(id);
    }
  }, []);

  // Schedule auto-dismiss for a toast
  const scheduleAutoDismiss = useCallback((id: string, ms: number) => {
    if (!timeoutsRef.current.has(id)) {
      timeoutsRef.current.set(id, new Set());
    }
    const timeouts = timeoutsRef.current.get(id)!;
    const timeoutId = setTimeout(() => {
      timeouts.delete(timeoutId);
      if (timeouts.size === 0) {
        timeoutsRef.current.delete(id);
      }
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, ms);
    timeouts.add(timeoutId);
  }, []);

  // Cleanup all timeouts on unmount
  useEffect(() => {
    return () => {
      for (const [, timeouts] of timeoutsRef.current) {
        for (const t of timeouts) {
          clearTimeout(t);
        }
      }
      timeoutsRef.current.clear();
    };
  }, []);

  const dismiss = useCallback(
    (id: string) => {
      clearTimeoutsForToast(id);
      setToasts((prev) => prev.filter((t) => t.id !== id));
    },
    [clearTimeoutsForToast],
  );

  const dismissAll = useCallback(() => {
    // Clear all timeouts
    for (const [, timeouts] of timeoutsRef.current) {
      for (const t of timeouts) {
        clearTimeout(t);
      }
    }
    timeoutsRef.current.clear();
    setToasts([]);
  }, []);

  const toast = useCallback(
    ({
      title,
      description,
      variant = "default",
      duration = 5000,
      progress,
      createdAt,
      actions,
    }: Omit<ToastData, "id">): ToastHandle => {
      const id = `toast-${++toastCounter}`;
      const newToast: ToastData = {
        id,
        title,
        description,
        variant,
        duration,
        progress,
        createdAt: createdAt ?? Date.now(),
        actions,
      };
      setToasts((prev) => [...prev, newToast]);

      // Auto dismiss (only if duration > 0)
      if (duration && duration > 0) {
        scheduleAutoDismiss(id, duration);
      }

      const handle: ToastHandle = {
        id,
        update: (options) => {
          // Always clear existing timeouts on any update
          clearTimeoutsForToast(id);

          setToasts((prev) =>
            prev.map((t) => {
              if (t.id === id) {
                const updated = { ...t, ...options };
                // Reschedule auto-dismiss based on new or existing duration
                const newDuration = options.duration ?? t.duration;
                if (newDuration && newDuration > 0) {
                  scheduleAutoDismiss(id, newDuration);
                }
                return updated;
              }
              return t;
            }),
          );
        },
        dismiss: () => {
          dismiss(id);
        },
      };

      return handle;
    },
    [dismiss, clearTimeoutsForToast, scheduleAutoDismiss],
  );

  return (
    <ToastContext.Provider value={{ toasts, toast, dismiss, dismissAll }}>
      {/* Duration on provider disables Radix's default 5000ms auto-dismiss.
          We manage timing ourselves via our centralized timeout system. */}
      <ToastProvider swipeDirection="right" duration={86400000}>
        {children}
        {toasts.map((t) => (
          <Toast
            key={t.id}
            open={true}
            variant={t.variant}
            // Pass duration to Radix: 0 or undefined = use provider default (24h)
            // Positive value = use that for Radix auto-dismiss (backup to our system)
            duration={t.duration && t.duration > 0 ? t.duration : undefined}
            onOpenChange={(open) => !open && dismiss(t.id)}
          >
            <div className="grid gap-1 flex-1">
              {t.title && <ToastTitle>{t.title}</ToastTitle>}
              <ToastDescription>{t.description}</ToastDescription>
              {t.progress !== undefined && <Progress value={t.progress} className="h-1.5 mt-1" />}
              <div className="flex items-center justify-between gap-2 mt-1">
                {t.createdAt && <ElapsedTime createdAt={t.createdAt} completedAt={t.completedAt} />}
                {t.actions && t.actions.length > 0 && (
                  <div className="flex gap-2">
                    {t.actions.map((action, i) => (
                      <Button
                        key={i}
                        variant="outline"
                        size="sm"
                        className="h-6 px-2 text-xs border-current/30 bg-transparent hover:bg-white/10"
                        onClick={action.onClick}
                      >
                        {action.label}
                      </Button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <ToastClose />
          </Toast>
        ))}
        <ToastViewport />
      </ToastProvider>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastContextProvider");
  }
  return context;
}
