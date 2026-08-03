import { cn } from "@/lib/utils";

type ChatTypingIndicatorProps = {
  elapsedSeconds?: number;
};

export function ChatTypingIndicator({
  elapsedSeconds = 0,
}: ChatTypingIndicatorProps) {
  const showElapsed = elapsedSeconds >= 3;
  const showLongWait = elapsedSeconds >= 15;

  return (
    <div className="space-y-1.5 py-1">
      <div
        aria-label="Assistant is typing"
        className="flex min-h-6 items-center gap-1.5"
      >
        {[0, 1, 2].map((index) => (
          <span
            className="size-2 rounded-full bg-muted-foreground/50 animate-[chat-typing-bounce_1.2s_infinite_ease-in-out_both]"
            key={index}
            style={{ animationDelay: `${index * 0.12 - 0.24}s` }}
          />
        ))}
        {showElapsed ? (
          <span className="text-xs text-muted-foreground">
            Thinking... ({elapsedSeconds}s)
          </span>
        ) : null}
      </div>
      {showLongWait ? (
        <p className="text-xs text-muted-foreground">
          Still working — retrieval and synthesis can take some time. Stop cancels the request.
        </p>
      ) : null}
    </div>
  );
}
