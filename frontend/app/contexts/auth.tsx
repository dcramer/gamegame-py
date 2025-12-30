import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { ApiError, api, getAuthToken, setAuthToken } from "~/api/client";
import type { User } from "~/api/types";

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  /** True when auth check failed due to network/server error (not 401) */
  hasConnectionError: boolean;
  login: (email: string) => Promise<{ success: boolean; magicLink?: string }>;
  verify: (token: string) => Promise<boolean>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  /** Retry auth check after connection error */
  retryAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

// Retry configuration for auth check
const AUTH_RETRY_CONFIG = {
  maxRetries: 3,
  baseDelayMs: 500,
  maxDelayMs: 4000,
};

/** Calculate delay with exponential backoff and jitter */
function getRetryDelay(attempt: number): number {
  const exponentialDelay = AUTH_RETRY_CONFIG.baseDelayMs * 2 ** attempt;
  const cappedDelay = Math.min(exponentialDelay, AUTH_RETRY_CONFIG.maxDelayMs);
  // Add 10-30% jitter to prevent thundering herd
  const jitter = cappedDelay * (0.1 + Math.random() * 0.2);
  return cappedDelay + jitter;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Only show loading on client side - server renders unauthenticated state
  const [isLoading, setIsLoading] = useState(typeof window !== "undefined");
  const [hasConnectionError, setHasConnectionError] = useState(false);

  // Track if component is mounted to prevent state updates after unmount
  const isMounted = useRef(true);
  // Track retry timeout for cleanup
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Core auth check function with retry logic
  const performAuthCheck = useCallback(async (retryCount = 0): Promise<void> => {
    const token = getAuthToken();
    if (!token) {
      if (isMounted.current) {
        setIsLoading(false);
        setHasConnectionError(false);
      }
      return;
    }

    try {
      const currentUser = await api.auth.me();
      if (isMounted.current) {
        setUser(currentUser);
        setHasConnectionError(false);
        setIsLoading(false);
      }
    } catch (error) {
      if (!isMounted.current) return;

      // 401 means token is invalid - clear it and stop
      if (error instanceof ApiError && error.status === 401) {
        setAuthToken(null);
        setUser(null);
        setHasConnectionError(false);
        setIsLoading(false);
        return;
      }

      // Network or server error - retry with backoff
      const isNetworkError = error instanceof ApiError && error.status === 0;
      const isServerError = error instanceof ApiError && error.status >= 500;

      if ((isNetworkError || isServerError) && retryCount < AUTH_RETRY_CONFIG.maxRetries) {
        const delay = getRetryDelay(retryCount);
        console.debug(
          `Auth check failed (attempt ${retryCount + 1}), retrying in ${Math.round(delay)}ms...`,
        );

        retryTimeoutRef.current = setTimeout(() => {
          if (isMounted.current) {
            performAuthCheck(retryCount + 1);
          }
        }, delay);
        return;
      }

      // Max retries exceeded or non-retryable error
      console.warn("Auth check failed after retries:", error);
      setHasConnectionError(true);
      setIsLoading(false);
    }
  }, []);

  // Check auth on mount (client-side only)
  useEffect(() => {
    if (typeof window === "undefined") return;

    isMounted.current = true;
    performAuthCheck();

    return () => {
      isMounted.current = false;
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
    };
  }, [performAuthCheck]);

  // Sync auth state across tabs
  useEffect(() => {
    if (typeof window === "undefined") return;

    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === "token") {
        if (event.newValue === null) {
          // Token was removed in another tab - logout this tab
          setUser(null);
        } else if (event.newValue && !user) {
          // Token was added in another tab - check auth
          api.auth
            .me()
            .then((currentUser) => setUser(currentUser))
            .catch(() => {
              // Token might be invalid
              setUser(null);
            });
        }
      }
    };

    window.addEventListener("storage", handleStorageChange);
    return () => window.removeEventListener("storage", handleStorageChange);
  }, [user]);

  const login = useCallback(async (email: string) => {
    const response = await api.auth.login(email);
    return {
      success: true,
      magicLink: response.magic_link,
    };
  }, []);

  const verify = useCallback(async (token: string) => {
    try {
      const response = await api.auth.verify(token);
      setAuthToken(response.access_token);
      setUser(response.user);
      return true;
    } catch {
      return false;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } catch (error) {
      // Log but don't block logout - local cleanup is more important
      console.warn("Logout API call failed:", error);
    } finally {
      setAuthToken(null);
      setUser(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const response = await api.auth.refresh();
      setAuthToken(response.access_token);
      setUser(response.user);
    } catch {
      setAuthToken(null);
      setUser(null);
    }
  }, []);

  const retryAuth = useCallback(async () => {
    setIsLoading(true);
    setHasConnectionError(false);
    await performAuthCheck();
  }, [performAuthCheck]);

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: !!user,
    isAdmin: !!user?.is_admin,
    hasConnectionError,
    login,
    verify,
    logout,
    refresh,
    retryAuth,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
