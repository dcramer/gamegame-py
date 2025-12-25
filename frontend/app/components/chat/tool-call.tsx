import { Check, FileText, Image, Loader2, Search } from "lucide-react";
import type { ToolCall } from "~/api/types";

function getToolIcon(name: string, isActive: boolean) {
  if (isActive) {
    return <Loader2 className="h-3 w-3 animate-spin" />;
  }
  switch (name) {
    case "search_resources":
      return <Search className="h-3 w-3" />;
    case "search_images":
      return <Image className="h-3 w-3" />;
    case "list_resources":
      return <FileText className="h-3 w-3" />;
    case "get_attachment":
      return <Image className="h-3 w-3" />;
    default:
      return <Check className="h-3 w-3 text-green-500" />;
  }
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

function getToolParams(name: string, args?: Record<string, unknown>): string | null {
  if (!args) return null;

  if (name === "search_resources" || name === "search_images") {
    return args.query ? `"${args.query}"` : null;
  }

  return null;
}

interface ToolCallMessageProps {
  toolCall: ToolCall;
}

export function ToolCallMessage({ toolCall }: ToolCallMessageProps) {
  const isActive = toolCall.status === "running";
  const toolParams = getToolParams(toolCall.name, toolCall.args);

  return (
    <div className="flex items-start gap-2 p-2 bg-muted/30 rounded border border-muted text-muted-foreground text-sm">
      <div className="shrink-0 mt-0.5">{getToolIcon(toolCall.name, isActive)}</div>

      <div className="flex-1 flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="text-xs">{getToolLabel(toolCall.name, toolCall.args)}</span>
          {toolCall.durationMs && (
            <span className="text-muted-foreground/50 text-xs ml-auto">
              {toolCall.durationMs}ms
            </span>
          )}
          {isActive && !toolCall.durationMs && (
            <span className="text-muted-foreground/50 text-xs ml-auto">...</span>
          )}
        </div>

        {toolParams && <div className="text-muted-foreground/60 text-xs">{toolParams}</div>}
      </div>
    </div>
  );
}

interface ToolCallsListProps {
  toolCalls: ToolCall[];
}

export function ToolCallsList({ toolCalls }: ToolCallsListProps) {
  if (toolCalls.length === 0) return null;

  return (
    <div className="space-y-1">
      {toolCalls.map((tc) => (
        <ToolCallMessage key={tc.id} toolCall={tc} />
      ))}
    </div>
  );
}
