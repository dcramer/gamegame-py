import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, getAuthToken, setAuthToken } from "~/api/client";
import type { User } from "~/api/types";

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  login: (email: string) => Promise<{ success: boolean; magicLink?: string }>;
  verify: (token: string) => Promise<boolean>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Only show loading on client side - server renders unauthenticated state
  const [isLoading, setIsLoading] = useState(typeof window !== "undefined");

  // Check auth on mount (client-side only)
  useEffect(() => {
    if (typeof window === "undefined") return;

    const checkAuth = async () => {
      const token = getAuthToken();
      if (!token) {
        setIsLoading(false);
        return;
      }

      try {
        const currentUser = await api.auth.me();
        setUser(currentUser);
      } catch {
        // Token invalid or expired, clear it
        setAuthToken(null);
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    };

    checkAuth();
  }, []);

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
    } catch {
      // Ignore logout errors
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

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: !!user,
    isAdmin: !!user?.is_admin,
    login,
    verify,
    logout,
    refresh,
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
