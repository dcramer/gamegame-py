import { Brain, Dices, ExternalLink, MessageCircle, Settings } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import type { Game } from "~/api/types";
import { ImageGallery, MessageBubble, ToolCallsList } from "~/components/chat";
import { ErrorBoundary } from "~/components/error-boundary";
import { Spinner } from "~/components/ui/spinner";
import { Button } from "~/components/ui/button";
import { Card, CardContent } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import { useAuth } from "~/contexts/auth";
import { useChat } from "~/hooks/useChat";
import type { Route } from "./+types/games.$gameIdOrSlug";

const DEFAULT_QUESTIONS = [
  "How does GameGame work?",
  "Where can I find more information about this game?",
  "How does setup work?",
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
  const [imageError, setImageError] = useState(false);
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
    sendMessage,
    dismissError,
  } = useChat(game.slug);

  // Scroll to bottom when messages change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView();
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

  const showThinkingIndicator =
    isChatLoading && !streamingContent && messages.length > 0;

  return (
    <div className="relative h-screen">
      {/* Floating header */}
      <div className="flex justify-between items-center h-16 lg:h-24 overflow-hidden absolute top-0 left-0 right-0 px-4 gap-4 border-b bg-card z-10">
        <div className="flex items-center gap-4 overflow-hidden whitespace-nowrap">
          <div className="w-8 h-8 lg:w-20 lg:h-20 relative flex-shrink-0">
            {game.image_url && !imageError ? (
              <img
                src={game.image_url}
                alt={game.name}
                className="w-full h-full object-cover object-top"
                onError={() => setImageError(true)}
              />
            ) : (
              <div className="w-full h-full bg-muted flex items-center justify-center">
                <Dices className="w-12 h-12 text-muted-foreground" />
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl lg:text-3xl font-bold">{game.name}</h2>
              {game.bgg_url && (
                <a
                  href={game.bgg_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={`View ${game.name} on BoardGameGeek`}
                  className="text-muted-foreground hover:text-foreground transition-colors"
                >
                  <ExternalLink className="w-4 h-4 lg:w-5 lg:h-5" />
                </a>
              )}
            </div>
            <div className="gap-4 items-center hidden lg:flex">
              {game.year && (
                <span className="text-muted-foreground text-sm">{game.year}</span>
              )}
              <p className="text-muted-foreground text-sm">
                <Button
                  size="sm"
                  variant="link"
                  onClick={() => sendMessage("What resources are you using?")}
                  className="p-0 h-auto"
                >
                  {game.resource_count || 0} resources
                </Button>
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {isAdmin && (
            <Link to={`/admin/games/${game.id}`}>
              <Button variant="ghost" size="sm" title="Edit game">
                <Settings className="w-5 h-5" />
                <span className="sr-only">Edit game</span>
              </Button>
            </Link>
          )}
          <Link to="/games">
            <Button variant="ghost">
              <span className="text-2xl">✕</span>
              <span className="sr-only">Close chat</span>
            </Button>
          </Link>
        </div>
      </div>

      {/* Chat card */}
      <ErrorBoundary onReset={dismissError}>
        <Card className="flex-1 flex absolute inset-0 max-w-full overflow-hidden w-full">
          <CardContent className="flex-1 flex items-stretch flex-col pt-20 lg:pt-32 pb-4 px-4">
            {/* Error display */}
            {chatError && (
              <div className="bg-destructive text-destructive-foreground font-bold p-2 lg:p-3 rounded mb-4">
                {chatError}
              </div>
            )}

            {/* Messages area */}
            <div className="flex-1 overflow-y-auto mb-4 gap-y-4 flex flex-col">
              {messages.length > 0 ? (
                <>
                  {messages.map((message, i) => (
                    <MessageBubble
                      key={i}
                      message={message}
                      citations={message.role === "assistant" ? citations : []}
                    />
                  ))}

                  {/* Tool calls for current turn (during streaming) */}
                  {isChatLoading && toolCalls.length > 0 && (
                    <ToolCallsList toolCalls={toolCalls} />
                  )}

                  {/* Thinking indicator - shows while loading, before streaming */}
                  {showThinkingIndicator && (
                    <div className="flex items-center gap-2 text-muted-foreground text-xs">
                      <Brain className="w-3 h-3 animate-pulse" />
                      <span>Thinking...</span>
                    </div>
                  )}

                  {/* Streaming content */}
                  {streamingContent && (
                    <MessageBubble
                      message={{ role: "assistant", content: streamingContent }}
                      citations={citations}
                      isStreaming
                    />
                  )}

                  {/* Images from tool calls - show after response */}
                  {!isChatLoading && images.length > 0 && <ImageGallery images={images} />}
                </>
              ) : (
                <div className="flex-1 flex flex-col gap-6 items-center justify-center text-muted-foreground lg:text-lg">
                  <Dices className="w-24 h-24" />
                  <ul className="flex flex-col items-center gap-2 text-sm flex-wrap">
                    {DEFAULT_QUESTIONS.map((question) => (
                      <li key={question}>
                        <Button
                          variant="default"
                          size="sm"
                          className="whitespace-normal text-left py-2 block h-auto"
                          onClick={() => handleSuggestion(question)}
                        >
                          {question}
                        </Button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {isChatLoading && (
                <div>
                  <div className="inline-flex flex-row items-center bg-muted text-muted-foreground rounded p-2 lg:p-3">
                    <Spinner size="sm" />
                  </div>
                </div>
              )}

              <div ref={scrollRef} />
            </div>

            {/* Input */}
            <form
              onSubmit={handleSubmit}
              className="flex items-center gap-2 h-12"
            >
              <Input
                ref={inputRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder={`Ask about ${game.name}...`}
                className="bg-background text-foreground placeholder-text-muted-foreground px-3 py-3 lg:py-5 h-full lg:text-base text-lg"
              />
              <Button type="submit" disabled={isChatLoading} className="gap-2 h-full">
                <MessageCircle className="w-5 h-5" />
                <span className="hidden lg:inline">Ask</span>
              </Button>
            </form>
          </CardContent>
        </Card>
      </ErrorBoundary>
    </div>
  );
}
