import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "~/api/client";
import type { Attachment, ChatMessage, Citation, ToolCall } from "~/api/types";

// Image result from tool calls
export interface ChatImage {
  id: string;
  url: string;
  caption: string | null;
  description: string | null;
}

// Stream event types matching Python backend
interface TextDeltaEvent {
  type: "text-delta";
  id: string;
  text: string;
}

interface ToolInputStartEvent {
  type: "tool-input-start";
  id: string;
  toolName: string;
}

interface ToolInputAvailableEvent {
  type: "tool-input-available";
  id: string;
  input: Record<string, unknown>;
}

interface ToolOutputAvailableEvent {
  type: "tool-output-available";
  id: string;
  output: unknown;
}

interface FinishEvent {
  type: "finish";
  id: string;
  finishReason: string;
  totalUsage: {
    promptTokens: number;
    completionTokens: number;
  };
}

interface ErrorEvent {
  type: "error";
  id: string;
  error: string;
}

interface ContextDataEvent {
  type: "context-data";
  id: string;
  citations: Citation[];
  images: ChatImage[];
}

type StreamEvent =
  | TextDeltaEvent
  | ToolInputStartEvent
  | ToolInputAvailableEvent
  | ToolOutputAvailableEvent
  | FinishEvent
  | ErrorEvent
  | ContextDataEvent;

// Re-export ToolCall for consumers that import from this file
export type { ToolCall } from "~/api/types";

interface ChatState {
  messages: ChatMessage[];
  citations: Citation[];
  images: ChatImage[];
  toolCalls: ToolCall[];
  isLoading: boolean;
  error: string | null;
  streamingContent: string;
  tokenUsage: {
    promptTokens: number;
    completionTokens: number;
  } | null;
}

function getToolLabel(name: string, args?: Record<string, unknown>): string {
  switch (name) {
    case "search_resources":
      return args?.query ? `Searching: "${args.query}"` : "Searching rulebook";
    case "search_images":
      return args?.query ? `Finding images: "${args.query}"` : "Searching for images";
    case "list_resources":
      return "Checking available resources";
    case "get_attachment":
      return "Loading image";
    default:
      return name;
  }
}

export function useChat(gameSlug: string) {
  const [state, setState] = useState<ChatState>({
    messages: [],
    citations: [],
    images: [],
    toolCalls: [],
    isLoading: false,
    error: null,
    streamingContent: "",
    tokenUsage: null,
  });
  const abortControllerRef = useRef<AbortController | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  const sendMessage = useCallback(
    async (content: string, useStreaming: boolean = true) => {
      if (!content.trim() || state.isLoading) return;

      // Abort any existing request
      abortControllerRef.current?.abort();

      // Create new abort controller for this request
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      // Add user message
      const userMessage: ChatMessage = { role: "user", content: content.trim() };
      const updatedMessages = [...state.messages, userMessage];

      setState((prev) => ({
        ...prev,
        messages: updatedMessages,
        isLoading: true,
        error: null,
        streamingContent: "",
        toolCalls: [],
        images: [],
        tokenUsage: null,
      }));

      try {
        if (useStreaming) {
          // Streaming mode with AI SDK events
          let fullContent = "";
          const toolCallsMap = new Map<string, ToolCall>();
          const extractedCitations: Citation[] = [];
          const extractedImages: ChatImage[] = [];

          const stream = api.chat.stream(gameSlug, updatedMessages, abortController.signal);

          for await (const eventStr of stream) {
            // Check if aborted
            if (abortController.signal.aborted) {
              return;
            }

            // Parse the JSON event
            let event: StreamEvent;
            try {
              event = JSON.parse(eventStr);
            } catch {
              // Not JSON, could be raw text from older API
              fullContent += eventStr;
              setState((prev) => ({ ...prev, streamingContent: fullContent }));
              continue;
            }

            switch (event.type) {
              case "text-delta":
                fullContent += event.text;
                setState((prev) => ({ ...prev, streamingContent: fullContent }));
                break;

              case "tool-input-start":
                toolCallsMap.set(event.id, {
                  id: event.id,
                  name: event.toolName,
                  status: "running",
                  startTime: Date.now(),
                });
                setState((prev) => ({
                  ...prev,
                  toolCalls: Array.from(toolCallsMap.values()),
                }));
                break;

              case "tool-input-available":
                if (toolCallsMap.has(event.id)) {
                  const tc = toolCallsMap.get(event.id)!;
                  tc.args = event.input as Record<string, unknown>;
                  setState((prev) => ({
                    ...prev,
                    toolCalls: Array.from(toolCallsMap.values()),
                  }));
                }
                break;

              case "tool-output-available":
                if (toolCallsMap.has(event.id)) {
                  const tc = toolCallsMap.get(event.id)!;
                  tc.status = "completed";
                  tc.result = event.output;
                  if (tc.startTime) {
                    tc.durationMs = Date.now() - tc.startTime;
                  }

                  // Extract citations from search_resources results
                  if (tc.name === "search_resources" && Array.isArray(event.output)) {
                    for (const result of event.output) {
                      if (result.resource_id && result.resource_name) {
                        extractedCitations.push({
                          resource_id: result.resource_id,
                          resource_name: result.resource_name,
                          page_number: result.page_number ?? null,
                          section: result.section ?? null,
                          relevance: result.score > 0.5 ? "primary" : "supporting",
                        });
                      }
                    }
                  }

                  // Extract images from get_attachment results
                  if (tc.name === "get_attachment" && event.output) {
                    const attachment = event.output as Partial<Attachment>;
                    if (attachment.id && attachment.url) {
                      extractedImages.push({
                        id: attachment.id,
                        url: attachment.url,
                        caption: attachment.caption ?? null,
                        description: attachment.description ?? null,
                      });
                    }
                  }

                  // Extract images from search_images results
                  if (tc.name === "search_images" && Array.isArray(event.output)) {
                    for (const img of event.output) {
                      if (img.id && img.url) {
                        extractedImages.push({
                          id: img.id,
                          url: img.url,
                          caption: img.caption ?? null,
                          description: img.description ?? null,
                        });
                      }
                    }
                  }

                  setState((prev) => ({
                    ...prev,
                    toolCalls: Array.from(toolCallsMap.values()),
                    citations: extractedCitations,
                    images: extractedImages,
                  }));
                }
                break;

              case "finish":
                setState((prev) => ({
                  ...prev,
                  tokenUsage: {
                    promptTokens: event.totalUsage.promptTokens,
                    completionTokens: event.totalUsage.completionTokens,
                  },
                }));
                break;

              case "context-data":
                extractedCitations.push(...event.citations);
                extractedImages.push(...event.images);
                setState((prev) => ({
                  ...prev,
                  citations: extractedCitations,
                  images: extractedImages,
                }));
                break;

              case "error":
                throw new Error(event.error);
            }
          }

          // Deduplicate citations
          const uniqueCitations: Citation[] = [];
          const seenResources = new Set<string>();
          for (const c of extractedCitations) {
            if (!seenResources.has(c.resource_id)) {
              seenResources.add(c.resource_id);
              uniqueCitations.push(c);
            }
          }

          // Deduplicate images
          const uniqueImages: ChatImage[] = [];
          const seenImages = new Set<string>();
          for (const img of extractedImages) {
            if (!seenImages.has(img.id)) {
              seenImages.add(img.id);
              uniqueImages.push(img);
            }
          }

          // Add assistant message with structured metadata from this turn
          const assistantMessage: ChatMessage = {
            role: "assistant",
            content: fullContent,
            toolCalls: Array.from(toolCallsMap.values()),
            citations: uniqueCitations,
            images: uniqueImages,
          };

          setState((prev) => ({
            ...prev,
            messages: [...updatedMessages, assistantMessage],
            isLoading: false,
            streamingContent: "",
            toolCalls: [], // Clear - now stored in message
            citations: uniqueCitations,
            images: uniqueImages,
          }));
        } else {
          // Non-streaming mode
          const response = await api.chat.send(gameSlug, updatedMessages);

          const assistantMessage: ChatMessage = {
            role: "assistant",
            content: response.content,
            citations: response.citations,
          };

          setState((prev) => ({
            ...prev,
            messages: [...updatedMessages, assistantMessage],
            citations: response.citations,
            isLoading: false,
          }));
        }
      } catch (err) {
        // Ignore abort errors - they're expected when user cancels
        if (err instanceof Error && err.name === "AbortError") {
          setState((prev) => ({
            ...prev,
            isLoading: false,
          }));
          return;
        }

        const errorMessage =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to send message";

        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: errorMessage,
        }));
      }
    },
    [gameSlug, state.messages, state.isLoading],
  );

  const clearChat = useCallback(() => {
    // Abort any in-flight request
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;

    setState({
      messages: [],
      citations: [],
      images: [],
      toolCalls: [],
      isLoading: false,
      error: null,
      streamingContent: "",
      tokenUsage: null,
    });
  }, []);

  const dismissError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  return {
    messages: state.messages,
    citations: state.citations,
    images: state.images,
    toolCalls: state.toolCalls,
    isLoading: state.isLoading,
    error: state.error,
    streamingContent: state.streamingContent,
    tokenUsage: state.tokenUsage,
    sendMessage,
    clearChat,
    dismissError,
    getToolLabel,
  };
}
