// API client for communicating with the backend

import type {
  Attachment,
  AttachmentUpdate,
  BggGame,
  ChatMessage,
  ChatResponse,
  DetectedType,
  FileUploadResponse,
  Game,
  GameCreate,
  GameUpdate,
  HealthCheck,
  HealthCheckDb,
  LoginResponse,
  ReprocessResponse,
  Resource,
  ResourceUpdate,
  SearchResponse,
  TokenResponse,
  User,
  WorkflowRun,
  WorkflowStatus,
} from "./types";

// SSR-safe base URL
const BASE_URL = typeof window !== "undefined" ? "/api" : "http://localhost:8000/api";

// SSR-safe localStorage access
function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

// Clear token and redirect to login (SSR-safe)
function handleAuthFailure(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("token");
  // Dispatch event so AuthContext can sync
  window.dispatchEvent(new StorageEvent("storage", { key: "token", newValue: null }));
  // Redirect to login if not already there
  if (!window.location.pathname.startsWith("/auth/")) {
    window.location.href = "/auth/signin";
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Default timeout for requests (30 seconds)
const DEFAULT_TIMEOUT = 30000;

async function request<T>(
  path: string,
  options: RequestInit & { timeout?: number; skipAuth?: boolean } = {},
): Promise<T> {
  const { timeout = DEFAULT_TIMEOUT, skipAuth = false, ...fetchOptions } = options;
  const token = getStoredToken();

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...fetchOptions.headers,
  };

  if (token && !skipAuth) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  // Create AbortController for timeout
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  // Combine with any existing signal
  const signal = fetchOptions.signal
    ? combineAbortSignals(fetchOptions.signal, controller.signal)
    : controller.signal;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...fetchOptions,
      headers,
      signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error) {
      if (err.name === "AbortError") {
        throw new ApiError(0, "Request timed out");
      }
      // Network error (no internet, DNS failure, etc.)
      throw new ApiError(0, `Network error: ${err.message}`);
    }
    throw new ApiError(0, "Unknown network error");
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));

    // Handle 401 Unauthorized - token expired or invalid
    if (response.status === 401 && !skipAuth) {
      handleAuthFailure();
      throw new ApiError(401, "Session expired. Please sign in again.");
    }

    throw new ApiError(response.status, error.detail || "Request failed");
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

// Helper to combine multiple AbortSignals
function combineAbortSignals(...signals: AbortSignal[]): AbortSignal {
  const controller = new AbortController();
  for (const signal of signals) {
    if (signal.aborted) {
      controller.abort();
      break;
    }
    signal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  return controller.signal;
}

// Special request for file uploads (multipart/form-data)
async function uploadRequest<T>(
  path: string,
  file: File,
  queryParams?: Record<string, string>,
  timeout: number = 120000, // 2 minutes for uploads
): Promise<T> {
  const token = getStoredToken();

  const headers: HeadersInit = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const formData = new FormData();
  formData.append("file", file);

  const url = queryParams
    ? `${BASE_URL}${path}?${new URLSearchParams(queryParams)}`
    : `${BASE_URL}${path}`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers,
      body: formData,
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error) {
      if (err.name === "AbortError") {
        throw new ApiError(0, "Upload timed out");
      }
      console.error("Upload network error:", err);
      throw new ApiError(0, `Network error: ${err.message}`);
    }
    throw new ApiError(0, "Unknown network error");
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    if (response.status === 401) {
      handleAuthFailure();
      throw new ApiError(401, "Session expired. Please sign in again.");
    }
    throw new ApiError(response.status, error.detail || "Upload failed");
  }

  return response.json();
}

// Upload with progress callback using XMLHttpRequest
function uploadWithProgress<T>(
  path: string,
  file: File,
  onProgress?: (percent: number) => void,
  timeout: number = 120000, // 2 minutes for uploads
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const token = getStoredToken();

    const formData = new FormData();
    formData.append("file", file);

    // Set timeout
    xhr.timeout = timeout;

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        const percent = Math.round((event.loaded / event.total) * 100);
        onProgress(percent);
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new ApiError(xhr.status, "Invalid JSON response"));
        }
      } else if (xhr.status === 401) {
        handleAuthFailure();
        reject(new ApiError(401, "Session expired. Please sign in again."));
      } else {
        try {
          const error = JSON.parse(xhr.responseText);
          reject(new ApiError(xhr.status, error.detail || "Upload failed"));
        } catch {
          reject(new ApiError(xhr.status, "Upload failed"));
        }
      }
    });

    xhr.addEventListener("error", () => {
      console.error("Upload network error");
      reject(new ApiError(0, "Network error"));
    });

    xhr.addEventListener("abort", () => {
      reject(new ApiError(0, "Upload aborted"));
    });

    xhr.addEventListener("timeout", () => {
      reject(new ApiError(0, "Upload timed out"));
    });

    xhr.open("POST", `${BASE_URL}${path}`);
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    xhr.send(formData);
  });
}

export const api = {
  // ============================================================================
  // Auth
  // ============================================================================
  auth: {
    login: (email: string) =>
      request<LoginResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email }),
      }),

    verify: (token: string) =>
      request<TokenResponse>("/auth/verify", {
        method: "POST",
        body: JSON.stringify({ token }),
      }),

    me: () => request<User>("/auth/me"),

    logout: () =>
      request<void>("/auth/logout", {
        method: "POST",
      }),

    refresh: () =>
      request<TokenResponse>("/auth/refresh", {
        method: "POST",
      }),
  },

  // ============================================================================
  // Games
  // ============================================================================
  games: {
    list: () => request<Game[]>("/games"),

    get: (idOrSlug: string) => request<Game>(`/games/${idOrSlug}`),

    create: (data: GameCreate) =>
      request<Game>("/games", {
        method: "POST",
        body: JSON.stringify(data),
      }),

    update: (id: string, data: GameUpdate) =>
      request<Game>(`/games/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),

    delete: (id: string) =>
      request<void>(`/games/${id}`, {
        method: "DELETE",
      }),

    syncBgg: (id: string) =>
      request<Game>(`/games/${id}/sync-bgg`, {
        method: "POST",
      }),

    // Get BGG info (preview before sync)
    getBggInfo: (bggId: number) =>
      request<{
        bgg_id: number;
        name: string;
        year: number | null;
        image_url: string | null;
        thumbnail_url: string | null;
        description: string | null;
        min_players: number | null;
        max_players: number | null;
        playing_time: number | null;
      }>(`/games/bgg/${bggId}`),
  },

  // ============================================================================
  // Resources
  // ============================================================================
  resources: {
    list: (gameIdOrSlug: string) => request<Resource[]>(`/games/${gameIdOrSlug}/resources`),

    get: (id: string) => request<Resource>(`/resources/${id}`),

    upload: (gameIdOrSlug: string, file: File, onProgress?: (percent: number) => void) =>
      uploadWithProgress<Resource>(`/games/${gameIdOrSlug}/resources`, file, onProgress),

    update: (id: string, data: ResourceUpdate) =>
      request<Resource>(`/resources/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),

    delete: (id: string) =>
      request<void>(`/resources/${id}`, {
        method: "DELETE",
      }),

    reprocess: (id: string, startStage?: string) => {
      const params = startStage ? `?start_stage=${encodeURIComponent(startStage)}` : "";
      return request<Resource>(`/resources/${id}/reprocess${params}`, {
        method: "POST",
      });
    },
  },

  // ============================================================================
  // Attachments
  // ============================================================================
  attachments: {
    get: (id: string) => request<Attachment>(`/attachments/${id}`),

    update: (id: string, data: AttachmentUpdate) =>
      request<Attachment>(`/attachments/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),

    listByResource: (
      resourceId: string,
      options?: { detectedType?: DetectedType; limit?: number; offset?: number },
    ) => {
      const params = new URLSearchParams();
      if (options?.detectedType) params.set("detected_type", options.detectedType);
      if (options?.limit) params.set("limit", options.limit.toString());
      if (options?.offset) params.set("offset", options.offset.toString());
      const query = params.toString() ? `?${params}` : "";
      return request<Attachment[]>(`/attachments/by-resource/${resourceId}${query}`);
    },

    listByGame: (
      gameId: string,
      options?: { detectedType?: DetectedType; limit?: number; offset?: number },
    ) => {
      const params = new URLSearchParams();
      if (options?.detectedType) params.set("detected_type", options.detectedType);
      if (options?.limit) params.set("limit", options.limit.toString());
      if (options?.offset) params.set("offset", options.offset.toString());
      const query = params.toString() ? `?${params}` : "";
      return request<Attachment[]>(`/attachments/by-game/${gameId}${query}`);
    },

    // Nested route version
    listForResource: (
      resourceId: string,
      options?: { detectedType?: DetectedType; limit?: number; offset?: number },
    ) => {
      const params = new URLSearchParams();
      if (options?.detectedType) params.set("detected_type", options.detectedType);
      if (options?.limit) params.set("limit", options.limit.toString());
      if (options?.offset) params.set("offset", options.offset.toString());
      const query = params.toString() ? `?${params}` : "";
      return request<Attachment[]>(`/resources/${resourceId}/attachments${query}`);
    },

    // Nested route version (admin only)
    listForGame: (
      gameIdOrSlug: string,
      options?: { detectedType?: DetectedType; limit?: number; offset?: number },
    ) => {
      const params = new URLSearchParams();
      if (options?.detectedType) params.set("detected_type", options.detectedType);
      if (options?.limit) params.set("limit", options.limit.toString());
      if (options?.offset) params.set("offset", options.offset.toString());
      const query = params.toString() ? `?${params}` : "";
      return request<Attachment[]>(`/games/${gameIdOrSlug}/attachments${query}`);
    },

    reprocess: (id: string) =>
      request<{
        success: boolean;
        message: string;
        attachment: Attachment;
      }>(`/attachments/${id}/reprocess`, {
        method: "POST",
      }),
  },

  // ============================================================================
  // Upload
  // ============================================================================
  upload: {
    file: (file: File, type?: "image" | "pdf") =>
      uploadRequest<FileUploadResponse>("/upload", file, type ? { type } : undefined),
  },

  // ============================================================================
  // Search
  // ============================================================================
  search: {
    search: (query: string, options?: { gameId?: string; limit?: number }) => {
      const params = new URLSearchParams({ q: query });
      if (options?.gameId) params.set("game_id", options.gameId);
      if (options?.limit) params.set("limit", options.limit.toString());
      return request<SearchResponse>(`/search?${params}`);
    },

    searchGame: (gameIdOrSlug: string, query: string, limit?: number) => {
      const params = new URLSearchParams({ q: query });
      if (limit) params.set("limit", limit.toString());
      return request<SearchResponse>(`/search/games/${gameIdOrSlug}?${params}`);
    },
  },

  // ============================================================================
  // Chat
  // ============================================================================
  chat: {
    send: (gameIdOrSlug: string, messages: ChatMessage[]) =>
      request<ChatResponse>(`/games/${gameIdOrSlug}/chat`, {
        method: "POST",
        body: JSON.stringify({ messages, stream: false }),
      }),

    // Stream chat response using SSE
    stream: async function* (
      gameIdOrSlug: string,
      messages: ChatMessage[],
      signal?: AbortSignal,
    ): AsyncGenerator<string, void, unknown> {
      const token = getStoredToken();

      const headers: HeadersInit = {
        "Content-Type": "application/json",
      };

      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }

      // Create combined controller for timeout and external signal
      const controller = new AbortController();
      const STREAM_TIMEOUT = 60000; // 60 seconds for initial response
      const READ_TIMEOUT = 30000; // 30 seconds between chunks
      let timeoutId = setTimeout(() => controller.abort(), STREAM_TIMEOUT);

      // Combine with external signal if provided
      const combinedSignal = signal
        ? combineAbortSignals(signal, controller.signal)
        : controller.signal;

      let response: Response;
      try {
        response = await fetch(`${BASE_URL}/games/${gameIdOrSlug}/chat`, {
          method: "POST",
          headers,
          body: JSON.stringify({ messages, stream: true }),
          signal: combinedSignal,
        });
      } catch (err) {
        clearTimeout(timeoutId);
        if (err instanceof Error) {
          if (err.name === "AbortError") {
            throw new ApiError(0, "Chat request timed out");
          }
          throw new ApiError(0, `Network error: ${err.message}`);
        }
        throw new ApiError(0, "Unknown network error");
      }

      if (!response.ok) {
        clearTimeout(timeoutId);
        const error = await response.json().catch(() => ({ detail: "Unknown error" }));
        if (response.status === 401) {
          handleAuthFailure();
          throw new ApiError(401, "Session expired. Please sign in again.");
        }
        throw new ApiError(response.status, error.detail || "Chat request failed");
      }

      const reader = response.body?.getReader();
      if (!reader) {
        clearTimeout(timeoutId);
        throw new ApiError(0, "No response body");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      try {
        while (true) {
          // Reset timeout for each read
          clearTimeout(timeoutId);
          timeoutId = setTimeout(() => controller.abort(), READ_TIMEOUT);

          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const data = line.slice(6);
              if (data === "[DONE]") {
                return;
              }
              yield data;
            }
          }
        }
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          throw new ApiError(0, "Chat stream timed out");
        }
        throw err;
      } finally {
        clearTimeout(timeoutId);
        reader.releaseLock();
      }
    },
  },

  // ============================================================================
  // BGG
  // ============================================================================
  bgg: {
    search: (query: string, limit?: number) => {
      const params = new URLSearchParams({ q: query });
      if (limit) params.set("limit", limit.toString());
      return request<
        Array<{
          bgg_id: number;
          name: string;
          year: number | null;
          game_type: string;
          is_imported: boolean;
          game_id: string | null;
          game_slug: string | null;
          game_image_url: string | null;
        }>
      >(`/bgg/search?${params}`);
    },

    import: (bggId: number) =>
      request<{
        id: string;
        name: string;
        slug: string;
        year: number | null;
        image_url: string | null;
        bgg_id: number;
        bgg_url: string;
      }>(`/bgg/games/${bggId}/import`, {
        method: "POST",
      }),

    thumbnail: (bggId: number) =>
      request<{
        thumbnail_url: string | null;
        cached: boolean;
      }>(`/bgg/games/${bggId}/thumbnail`),

    // Get full game info (cached)
    get: (bggId: number) => request<BggGame>(`/games/bgg/${bggId}`),
  },

  // ============================================================================
  // Workflows (Admin)
  // ============================================================================
  workflows: {
    list: (options?: {
      runIds?: string[];
      resourceIds?: string[];
      status?: WorkflowStatus;
      limit?: number;
      offset?: number;
    }) => {
      const params = new URLSearchParams();
      if (options?.runIds) {
        for (const id of options.runIds) params.append("runId", id);
      }
      if (options?.resourceIds) {
        for (const id of options.resourceIds) params.append("resourceId", id);
      }
      if (options?.status) params.set("status", options.status);
      if (options?.limit) params.set("limit", options.limit.toString());
      if (options?.offset) params.set("offset", options.offset.toString());
      const query = params.toString() ? `?${params}` : "";
      return request<WorkflowRun[]>(`/admin/workflows${query}`);
    },

    get: (runId: string) => request<WorkflowRun>(`/admin/workflows/${runId}`),

    retry: (runId: string) =>
      request<ReprocessResponse>(`/admin/workflows/${runId}/retry`, {
        method: "POST",
      }),

    cancel: (runId: string) =>
      request<ReprocessResponse>(`/admin/workflows/${runId}`, {
        method: "DELETE",
      }),
  },

  // ============================================================================
  // Health
  // ============================================================================
  health: {
    check: () => request<HealthCheck>("/health"),
    checkDb: () => request<HealthCheckDb>("/health/db"),
  },
};

// Helper to set/clear auth token (SSR-safe)
export function setAuthToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) {
    localStorage.setItem("token", token);
  } else {
    localStorage.removeItem("token");
  }
}

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function isAuthenticated(): boolean {
  return !!getAuthToken();
}
