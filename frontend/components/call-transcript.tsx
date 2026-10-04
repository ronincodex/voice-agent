import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { TranscriptMessage } from "@/lib/types";

/**
 * Chat-style transcript of one call.
 *
 * User messages are right-aligned with an accent background;
 * assistant messages are left-aligned with muted background. This
 * mirrors the convention every messaging app uses, so the reader
 * knows who spoke without reading the label.
 *
 * The ScrollArea caps the height at 600px so a long call does not
 * push the rest of the page off-screen. A 20-minute call can have
 * 60+ messages; without the cap, the page scroll becomes enormous.
 */
function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function MessageBubble({ message }: { message: TranscriptMessage }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system" || message.role === "tool";

  if (isSystem) {
    return (
      <div className="flex justify-center">
        <span className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
          {message.text}
        </span>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-1",
        isUser ? "items-end" : "items-start",
      )}
    >
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-2 text-sm leading-relaxed",
          isUser
            ? "bg-primary text-primary-foreground rounded-br-sm"
            : "bg-muted rounded-bl-sm",
        )}
      >
        {message.text}
      </div>
      <span className="px-1 text-[10px] tabular-nums text-muted-foreground">
        {formatTime(message.created_at)}
      </span>
    </div>
  );
}

export function CallTranscript({
  messages,
}: {
  messages: TranscriptMessage[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">
          Transcript ({messages.length}{" "}
          {messages.length === 1 ? "message" : "messages"})
        </CardTitle>
      </CardHeader>
      <CardContent>
        {messages.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No transcript recorded for this call.
          </p>
        ) : (
          <ScrollArea className="h-[600px] pr-4">
            <div className="space-y-4">
              {messages.map((message, index) => (
                <MessageBubble
                  key={`${message.created_at}-${index}`}
                  message={message}
                />
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
