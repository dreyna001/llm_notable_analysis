import { ArrowUp } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError, postChat } from "../api/client";
import type { ChatMode, ChatResponse } from "../types";
import { sanitizeChatAnswer } from "../utils/sanitizeChatAnswer";
import { MarkdownMessage } from "./MarkdownMessage";
import {
  ChatTypingIndicator,
  StreamingAssistantMessage,
} from "./StreamingAssistantMessage";

export type ChatTurn = {
  id: string;
  question: string;
  response?: ChatResponse;
  awaitingResponse: boolean;
  streaming: boolean;
};

export type ChatPanelState = {
  turns: ChatTurn[];
  sessionId: string | null;
  mode: ChatMode;
};

type ChatPanelProps = {
  mode: ChatMode;
  selectedCaseId?: string;
  initialTurns?: ChatTurn[];
  initialSessionId?: string | null;
  loadingHistory?: boolean;
  onStateChange?: (state: ChatPanelState) => void;
};

const COMPOSER_MAX_HEIGHT_PX = 200;

function newTurnId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function assistantStatusClass(status: string): string {
  if (status === "refused") return "text-destructive";
  if (status === "unknown") return "text-amber-400";
  return "text-foreground/90";
}

export function ChatPanel({
  mode,
  selectedCaseId,
  initialTurns = [],
  initialSessionId = null,
  loadingHistory = false,
  onStateChange,
}: ChatPanelProps) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>(initialTurns);
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isBusy = turns.some(
    (turn) => turn.awaitingResponse || turn.streaming,
  );

  const adjustComposerHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, COMPOSER_MAX_HEIGHT_PX)}px`;
  }, []);

  const scrollToBottom = useCallback(() => {
    const thread = threadRef.current;
    if (!thread) {
      return;
    }
    thread.scrollTop = thread.scrollHeight;
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [turns, loadingHistory, scrollToBottom]);

  useEffect(() => {
    onStateChange?.({ turns, sessionId, mode });
  }, [turns, sessionId, mode, onStateChange]);

  useEffect(() => {
    adjustComposerHeight();
  }, [question, adjustComposerHeight]);

  const markStreamingComplete = useCallback((turnId: string) => {
    setTurns((value) =>
      value.map((turn) =>
        turn.id === turnId ? { ...turn, streaming: false } : turn,
      ),
    );
  }, []);

  async function submitQuestion(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isBusy || loadingHistory) {
      if (!trimmed) {
        setError("Question is required.");
      }
      return;
    }

    const turnId = newTurnId();
    setQuestion("");
    setError(null);
    requestAnimationFrame(adjustComposerHeight);
    setTurns((value) => [
      ...value,
      {
        id: turnId,
        question: trimmed,
        awaitingResponse: true,
        streaming: false,
      },
    ]);

    try {
      const response = await postChat({
        mode,
        question: trimmed,
        selected_case_id: mode === "selected_case" ? selectedCaseId : undefined,
        session_id: sessionId,
      });
      if (response.session_id) {
        setSessionId(response.session_id);
      }
      const cleanedResponse = {
        ...response,
        answer: sanitizeChatAnswer(response.answer),
      };
      setTurns((value) =>
        value.map((turn) =>
          turn.id === turnId
            ? {
                ...turn,
                response: cleanedResponse,
                awaitingResponse: false,
                streaming: true,
              }
            : turn,
        ),
      );
    } catch (err: unknown) {
      const message =
        err instanceof ApiError
          ? `${err.status}: ${err.message}`
          : err instanceof Error
            ? err.message
            : "Unknown error";
      setTurns((value) => value.filter((turn) => turn.id !== turnId));
      setQuestion(trimmed);
      setError(message);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }
    event.preventDefault();
    void submitQuestion();
  }

  const hasSelectedCase = Boolean(selectedCaseId);
  const showEmptyState = !loadingHistory && !turns.length;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
      <div
        className="chat-scrollbar min-h-0 flex-1 overflow-y-auto"
        ref={threadRef}
      >
        <div
          className={cn(
            "mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-8",
            showEmptyState && "min-h-full justify-center",
          )}
        >
          {loadingHistory ? (
            <p className="text-center text-sm text-muted-foreground">
              Loading conversation...
            </p>
          ) : null}
          {showEmptyState ? (
            <div className="text-center">
              <h2 className="text-lg font-medium tracking-tight">
                How can I help?
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Ask about retained cases, the knowledge base, or any technology
                topic.
              </p>
            </div>
          ) : null}
          {turns.map((turn) => (
            <div className="flex flex-col gap-4" key={turn.id}>
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2.5 text-sm leading-relaxed">
                  {turn.question}
                </div>
              </div>
              {turn.awaitingResponse ? <ChatTypingIndicator /> : null}
              {turn.response && turn.streaming ? (
                <StreamingAssistantMessage
                  status={turn.response.answer_status}
                  text={turn.response.answer}
                  onUpdate={scrollToBottom}
                  onComplete={() => markStreamingComplete(turn.id)}
                />
              ) : null}
              {turn.response && !turn.streaming ? (
                <MarkdownMessage
                  className={cn(
                    assistantStatusClass(turn.response.answer_status),
                  )}
                  text={sanitizeChatAnswer(turn.response.answer)}
                />
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div className="bg-background px-4 pb-4 pt-2">
        <form className="mx-auto w-full max-w-3xl" onSubmit={submitQuestion}>
          {error ? (
            <p className="mb-2 text-sm text-destructive">{error}</p>
          ) : null}
          <div className="flex items-end gap-3 rounded-[26px] bg-muted/70 px-4 py-3 shadow-sm">
            <textarea
              ref={textareaRef}
              className="chat-scrollbar max-h-[200px] min-h-[24px] flex-1 resize-none overflow-y-auto border-0 bg-transparent py-0.5 text-sm leading-6 text-foreground outline-none placeholder:text-muted-foreground"
              placeholder={
                hasSelectedCase
                  ? "Ask about this case or any technology topic..."
                  : "Ask about cases, the knowledge base, or technology topics..."
              }
              rows={1}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={handleComposerKeyDown}
            />
            <Button
              className="size-8 shrink-0 rounded-full"
              disabled={isBusy || loadingHistory || !question.trim()}
              size="icon"
              type="submit"
            >
              <ArrowUp className="size-4" />
              <span className="sr-only">Send</span>
            </Button>
          </div>
          <p className="mt-3 text-center text-xs text-muted-foreground">
            AI Case Assistant can make mistakes. Check important info
          </p>
        </form>
      </div>
    </div>
  );
}
