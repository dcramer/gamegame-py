import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router";
import { Spinner } from "~/components/ui/spinner";
import { useAuth } from "~/contexts/auth";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
}

export function ProtectedRoute({ children, requireAdmin = false }: ProtectedRouteProps) {
  const { isAuthenticated, isAdmin, isLoading, hasConnectionError, retryAuth } = useAuth();
  const location = useLocation();

  // Track if we've hydrated to avoid SSR/client mismatch
  const [hasMounted, setHasMounted] = useState(false);
  useEffect(() => setHasMounted(true), []);

  // Show consistent loading state during SSR and initial hydration
  // This prevents hydration mismatch between server (no auth) and client (loading auth)
  if (!hasMounted || isLoading) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  // Show connection error UI if auth check failed due to network/server error
  // This prevents redirecting to login when the user likely has a valid token
  if (hasConnectionError) {
    return (
      <div className="flex h-[50vh] flex-col items-center justify-center gap-4 px-4 text-center">
        <div className="text-muted-foreground">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="48"
            height="48"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" />
            <path d="m4.93 4.93 14.14 14.14" />
          </svg>
        </div>
        <div>
          <h2 className="text-lg font-semibold">Connection Lost</h2>
          <p className="text-muted-foreground text-sm">
            Unable to verify your session. Please check your connection.
          </p>
        </div>
        <button
          type="button"
          onClick={() => retryAuth()}
          className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-4 py-2 text-sm font-medium transition-colors"
        >
          Try Again
        </button>
      </div>
    );
  }

  // Redirect to sign in if not authenticated
  if (!isAuthenticated) {
    return <Navigate to="/auth/signin" state={{ from: location }} replace />;
  }

  // Check admin requirement
  if (requireAdmin && !isAdmin) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
