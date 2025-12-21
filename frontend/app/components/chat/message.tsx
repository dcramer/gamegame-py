import Markdown from "react-markdown";
import type { ChatMessage, Citation } from "~/api/types";
import { Badge } from "~/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "~/components/ui/tooltip";

interface CitationLinkProps {
  number: number;
  citation?: Citation;
}

function CitationLink({ number, citation }: CitationLinkProps) {
  const locationLabel = citation?.page_number ? `p${citation.page_number}` : null;
  const pillLabel = citation
    ? [citation.resource_name, locationLabel].filter(Boolean).join(", ")
    : `Source ${number}`;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex align-middle">
            <span className="inline-flex items-center justify-center gap-1 mx-1 text-[0.7rem] leading-none font-semibold uppercase tracking-wide text-muted-foreground hover:text-primary cursor-help">
              {pillLabel}
            </span>
          </span>
        </TooltipTrigger>
        {citation && (
          <TooltipContent side="top" className="max-w-xs">
            <div>
              <div className="font-semibold">{citation.resource_name}</div>
              {citation.page_number && <div className="text-xs">Page {citation.page_number}</div>}
              {citation.section && (
                <div className="text-xs text-muted-foreground">{citation.section}</div>
              )}
            </div>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
}

interface MessageBubbleProps {
  message: ChatMessage;
  citations?: Citation[];
  isStreaming?: boolean;
}

export function MessageBubble({ message, citations = [], isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";

  // For user messages, just show plain text
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg px-4 py-2 bg-primary text-primary-foreground">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }

  // For assistant messages, render markdown
  // Process content to replace [n] citation markers with components
  const processContent = (content: string): React.ReactNode => {
    // Split on citation markers like [1], [2], etc.
    const parts = content.split(/(\[\d+\])/g);

    return parts.map((part, idx) => {
      const match = part.match(/^\[(\d+)\]$/);
      if (match) {
        const citationNumber = parseInt(match[1], 10);
        const citation = citations[citationNumber - 1];
        return <CitationLink key={`citation-${idx}`} number={citationNumber} citation={citation} />;
      }
      return part;
    });
  };

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-lg px-4 py-2 bg-muted text-foreground">
        <div className="prose prose-sm dark:prose-invert max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-headings:my-2">
          <Markdown
            components={{
              p: ({ children }) => <p>{processContent(String(children))}</p>,
              li: ({ children }) => <li>{processContent(String(children))}</li>,
              h1: ({ children }) => <h1>{processContent(String(children))}</h1>,
              h2: ({ children }) => <h2>{processContent(String(children))}</h2>,
              h3: ({ children }) => <h3>{processContent(String(children))}</h3>,
              h4: ({ children }) => <h4>{processContent(String(children))}</h4>,
            }}
          >
            {message.content}
          </Markdown>
        </div>
        {isStreaming && <span className="inline-block w-2 h-4 bg-current animate-pulse ml-1" />}
      </div>
    </div>
  );
}

interface CitationsListProps {
  citations: Citation[];
}

export function CitationsList({ citations }: CitationsListProps) {
  if (citations.length === 0) return null;

  return (
    <div className="border-t border-border pt-3 mt-3">
      <h4 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">
        Sources
      </h4>
      <div className="flex flex-wrap gap-2">
        {citations.map((citation, i) => (
          <TooltipProvider key={i}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="text-xs cursor-help">
                  {citation.resource_name}
                  {citation.page_number && ` (p. ${citation.page_number})`}
                </Badge>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs">
                <div>
                  <div className="font-semibold">{citation.resource_name}</div>
                  {citation.page_number && (
                    <div className="text-xs">Page {citation.page_number}</div>
                  )}
                  {citation.section && (
                    <div className="text-xs text-muted-foreground">{citation.section}</div>
                  )}
                  <div className="text-xs mt-1 text-muted-foreground capitalize">
                    {citation.relevance} source
                  </div>
                </div>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ))}
      </div>
    </div>
  );
}
