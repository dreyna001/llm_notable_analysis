import { useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import { sanitizeChatAnswer } from "../utils/sanitizeChatAnswer";
import { MarkdownMessage } from "./MarkdownMessage";

type StreamingAssistantMessageProps = {
  text: string;
  status: string;
  onComplete?: () => void;
  onUpdate?: () => void;
};

function assistantStatusClass(status: string): string {
  if (status === "refused") return "text-destructive";
  if (status === "unknown") return "text-amber-400";
  return "text-foreground/90";
}

export function StreamingAssistantMessage({
  text,
  status,
  onComplete,
  onUpdate,
}: StreamingAssistantMessageProps) {
  const safeText = useMemo(() => sanitizeChatAnswer(text), [text]);

  useEffect(() => {
    onUpdate?.();
    onComplete?.();
  }, [onComplete, onUpdate, safeText]);

  return (
    <div className="max-w-3xl">
      <MarkdownMessage
        className={assistantStatusClass(status)}
        text={safeText}
      />
    </div>
  );
}

export function ChatTypingIndicator() {
  return (
    <div
      aria-label="Assistant is typing"
      className="flex min-h-6 items-center gap-1.5 py-1"
    >
      {[0, 1, 2].map((index) => (
        <span
          className="size-2 rounded-full bg-muted-foreground/50 animate-[chat-typing-bounce_1.2s_infinite_ease-in-out_both]"
          key={index}
          style={{ animationDelay: `${index * 0.12 - 0.24}s` }}
        />
      ))}
    </div>
  );
}
