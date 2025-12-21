import { ArrowLeft, Brain, ExternalLink, Loader2, Send, Settings, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import type { Game } from "~/api/types";
import { CitationsList, ImageGallery, MessageBubble, ToolCallsList } from "~/components/chat";
import { ErrorBoundary } from "~/components/error-boundary";
import { Button } from "~/components/ui/button";
import { Card } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import { ScrollArea } from "~/components/ui/scroll-area";
import { useAuth } from "~/contexts/auth";
import { useChat } from "~/hooks/useChat";
import type { Route } from "./+types/games.$gameIdOrSlug";

const INITIAL_SUGGESTIONS = [
  "How do I set up the game?",
  "What are the win conditions?",
  "Explain the turn structure",
];

const FOLLOWUP_SUGGESTIONS = [
  "Can you give me an example?",
  "Are there any exceptions to this rule?",
  "What happens if...?",
  "Show me a related diagram",
];

// SSR loader - fetch game data on server
export async function loader({ params }: Route.LoaderArgs) {
  const baseUrl = process.env.API_URL || "http://localhost:8000";
  const response = await fetch(`${baseUrl}/api/games/${params.gameIdOrSlug}`);
  if (!response.ok) {
    throw new Response("Game not found", { status: 404 });
  }
  const game: Game = await response.json();
  return { game };
}

export function meta({ data }: Route.MetaArgs) {
  const game = data?.game;
  return [
    { title: game ? `${game.name} - GameGame` : "Game - GameGame" },
    {
      name: "description",
      content: game?.description || "Ask questions about this game's rules",
    },
  ];
}

export default function GamePage({ loaderData }: Route.ComponentProps) {
  const { game } = loaderData;
  const { isAdmin } = useAuth();
  const [inputValue, setInputValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const {
    messages,
    citations,
    images,
    toolCalls,
    isLoading: isChatLoading,
    error: chatError,
    streamingContent,
    tokenUsage,
    sendMessage,
    clearChat,
    dismissError,
  } = useChat(game.slug);

  // Scroll to bottom when messages change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent, toolCalls, images]);

  // Focus input on mount
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputValue.trim() && !isChatLoading) {
      sendMessage(inputValue);
      setInputValue("");
    }
  };

  const handleSuggestion = (question: string) => {
    if (!isChatLoading) {
      sendMessage(question);
    }
  };

  const hasActiveToolCalls = toolCalls.some((tc) => tc.status === "running");
  const showThinkingIndicator = isChatLoading && !streamingContent && !hasActiveToolCalls;

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="max-w-4xl mx-auto">
        {/* Back link */}
        <Link
          to="/games"
          className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground mb-4"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Games
        </Link>

        {/* Game header */}
        <div className="flex items-start gap-6 mb-8">
          {game.image_url ? (
            <img
              src={game.image_url}
              alt={game.name}
              className="w-32 h-32 object-cover rounded-lg"
            />
          ) : (
            <div className="w-32 h-32 bg-muted rounded-lg flex items-center justify-center">
              <span className="text-4xl text-muted-foreground">{game.name.charAt(0)}</span>
            </div>
          )}
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold">{game.name}</h1>
              {game.bgg_url && (
                <a
                  href={game.bgg_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  title="View on BoardGameGeek"
                >
                  <ExternalLink className="h-5 w-5" />
                </a>
              )}
              {isAdmin && (
                <Link
                  to={`/admin/games/${game.id}`}
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  title="Edit game"
                >
                  <Settings className="h-5 w-5" />
                </Link>
              )}
            </div>
            <div className="flex items-center gap-3 mb-2 text-muted-foreground">
              {game.year && <span>{game.year}</span>}
              {game.resource_count !== undefined && game.resource_count > 0 && (
                <span>
                  {game.resource_count} {game.resource_count === 1 ? "resource" : "resources"}
                </span>
              )}
            </div>
            {game.description && (
              <p className="text-muted-foreground line-clamp-3">{game.description}</p>
            )}
          </div>
        </div>

        {/* Chat interface */}
        <ErrorBoundary onReset={clearChat}>
          <Card className="h-[600px] flex flex-col">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="font-semibold">Ask about the rules</h2>
              <div className="flex items-center gap-2">
                {tokenUsage && (
                  <span className="text-xs text-muted-foreground">
                    {tokenUsage.promptTokens + tokenUsage.completionTokens} tokens
                  </span>
                )}
                {messages.length > 0 && (
                  <Button variant="ghost" size="sm" onClick={clearChat}>
                    <X className="h-4 w-4 mr-1" />
                    Clear
                  </Button>
                )}
              </div>
            </div>

            {/* Messages */}
            <ScrollArea ref={scrollRef} className="flex-1 p-4">
              {messages.length === 0 && !streamingContent ? (
                <div className="h-full flex flex-col items-center justify-center text-center">
                  <p className="text-muted-foreground mb-4">
                    Ask any question about {game.name}'s rules!
                  </p>
                  <div className="flex flex-wrap gap-2 justify-center">
                    {INITIAL_SUGGESTIONS.map((suggestion) => (
                      <Button
                        key={suggestion}
                        variant="outline"
                        size="sm"
                        onClick={() => handleSuggestion(suggestion)}
                        disabled={isChatLoading}
                      >
                        {suggestion}
                      </Button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {messages.map((message, i) => (
                    <MessageBubble
                      key={i}
                      message={message}
                      citations={message.role === "assistant" ? citations : []}
                    />
                  ))}

                  {/* Tool calls indicator */}
                  {toolCalls.length > 0 && <ToolCallsList toolCalls={toolCalls} />}

                  {/* Images from tool calls */}
                  {images.length > 0 && <ImageGallery images={images} />}

                  {/* Streaming content */}
                  {streamingContent && (
                    <MessageBubble
                      message={{ role: "assistant", content: streamingContent }}
                      citations={citations}
                      isStreaming
                    />
                  )}

                  {/* Thinking indicator */}
                  {showThinkingIndicator && (
                    <div className="flex items-center gap-2 text-muted-foreground text-sm">
                      <Brain className="h-4 w-4 animate-pulse" />
                      <span>Thinking...</span>
                    </div>
                  )}

                  {/* Citations after last message */}
                  {!isChatLoading && messages.length > 0 && <CitationsList citations={citations} />}

                  {/* Follow-up suggestions after response */}
                  {!isChatLoading && messages.length > 0 && (
                    <div className="mt-4 pt-3 border-t border-border">
                      <p className="text-xs text-muted-foreground mb-2 uppercase tracking-wide">
                        Follow-up questions
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {FOLLOWUP_SUGGESTIONS.map((suggestion) => (
                          <Button
                            key={suggestion}
                            variant="outline"
                            size="sm"
                            onClick={() => handleSuggestion(suggestion)}
                            className="text-xs"
                          >
                            {suggestion}
                          </Button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </ScrollArea>

            {/* Error display */}
            {chatError && (
              <div className="mx-4 mb-2 p-2 bg-destructive/10 border border-destructive rounded-md flex items-center justify-between">
                <span className="text-sm text-destructive">{chatError}</span>
                <Button variant="ghost" size="sm" onClick={dismissError} className="h-6 w-6 p-0">
                  <X className="h-3 w-3" />
                </Button>
              </div>
            )}

            {/* Input */}
            <form onSubmit={handleSubmit} className="border-t border-border p-4 flex gap-2">
              <Input
                ref={inputRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder={`Ask about ${game.name}...`}
                disabled={isChatLoading}
                className="flex-1"
              />
              <Button type="submit" disabled={!inputValue.trim() || isChatLoading}>
                {isChatLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </form>
          </Card>
        </ErrorBoundary>
      </div>
    </div>
  );
}
