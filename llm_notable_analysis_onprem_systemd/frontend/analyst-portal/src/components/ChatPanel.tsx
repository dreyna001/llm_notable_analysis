import { ArrowUp, Square } from "lucide-react";
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
import { postChat } from "../api/client";
import type { ChatMode, ChatResponse } from "../types";
import { formatApiError } from "../utils/formatApiError";
import { sanitizeChatAnswer } from "../utils/sanitizeChatAnswer";
import { MarkdownMessage } from "./MarkdownMessage";
import { ChatTypingIndicator } from "./StreamingAssistantMessage";

export type ChatTurn = {
  id: string;
  question: string;
  response?: ChatResponse;
  awaitingResponse: boolean;
};

export type ChatPanelState = {
  turns: ChatTurn[];
  sessionId: string | null;
  mode: ChatMode;
};

export type OrphanedChatResponse = {
  sessionId: string;
  completedTurnCountAtSubmit: number;
  expectedMessageCount: number;
};

type ChatPanelProps = {
  mode: ChatMode;
  selectedCaseId?: string;
  initialTurns?: ChatTurn[];
  initialSessionId?: string | null;
  resetKey?: string;
  loadingHistory?: boolean;
  maxQuestionChars?: number;
  disabledReason?: string;
  composerDisabled?: boolean;
  serverSyncError?: string | null;
  onStateChange?: (state: ChatPanelState) => void;
  onChatCancelled?: (state: ChatPanelState) => void;
  onOrphanedChatResponse?: (payload: OrphanedChatResponse) => void;
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
  resetKey,
  loadingHistory = false,
  maxQuestionChars,
  disabledReason,
  composerDisabled = false,
  serverSyncError,
  onStateChange,
  onChatCancelled,
  onOrphanedChatResponse,
}: ChatPanelProps) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>(initialTurns);
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [error, setError] = useState<string | null>(null);
  const [waitingElapsedSec, setWaitingElapsedSec] = useState(0);
  const threadRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatAbortRef = useRef<AbortController | null>(null);
  const chatRequestGenRef = useRef(0);
  const pendingQuestionRef = useRef<string | null>(null);

  const buildPanelState = useCallback(
    (nextTurns: ChatTurn[]): ChatPanelState => ({
      turns: nextTurns,
      sessionId,
      mode,
    }),
    [mode, sessionId],
  );

  const isBusy = turns.some((turn) => turn.awaitingResponse);
  const inputDisabled = Boolean(disabledReason) || composerDisabled || loadingHistory;

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
    chatRequestGenRef.current += 1;
    chatAbortRef.current?.abort();
    chatAbortRef.current = null;
    pendingQuestionRef.current = null;
    setTurns(initialTurns);
    setSessionId(initialSessionId);
    setError(null);
    setWaitingElapsedSec(0);
  }, [resetKey]);

  useEffect(() => {
    adjustComposerHeight();
  }, [question, adjustComposerHeight]);

  useEffect(() => {
    if (!isBusy) {
      setWaitingElapsedSec(0);
      return;
    }
    const startedAt = Date.now();
    setWaitingElapsedSec(0);
    const timer = window.setInterval(() => {
      setWaitingElapsedSec(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isBusy]);

  useEffect(() => {
    return () => {
      chatAbortRef.current?.abort();
    };
  }, []);

  function cancelPendingChat() {
    chatRequestGenRef.current += 1;
    chatAbortRef.current?.abort();
    chatAbortRef.current = null;

    const restoreRef = { text: pendingQuestionRef.current };
    pendingQuestionRef.current = null;

    let nextTurns: ChatTurn[] = [];
    setTurns((value) => {
      if (!restoreRef.text) {
        const pending = value.find((turn) => turn.awaitingResponse);
        if (pending) {
          restoreRef.text = pending.question;
        }
      }
      nextTurns = value.filter((turn) => !turn.awaitingResponse);
      return nextTurns;
    });

    if (restoreRef.text) {
      setQuestion(restoreRef.text);
      requestAnimationFrame(adjustComposerHeight);
    }
    setError("Stopped. You can edit and send again.");
    onChatCancelled?.(buildPanelState(nextTurns));
  }

  async function submitQuestion(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const trimmed = question.trim();
    if (disabledReason) {
      setError(disabledReason);
      return;
    }
    if (!trimmed || isBusy || loadingHistory) {
      if (!trimmed) {
        setError("Question is required.");
      }
      return;
    }
    if (maxQuestionChars != null && trimmed.length > maxQuestionChars) {
      setError(`Question must be ${maxQuestionChars} characters or fewer.`);
      return;
    }

    const turnId = newTurnId();
    const requestGen = chatRequestGenRef.current + 1;
    chatRequestGenRef.current = requestGen;
    const abortController = new AbortController();
    chatAbortRef.current = abortController;
    pendingQuestionRef.current = trimmed;
    const completedTurnCountAtSubmit = turns.filter(
      (turn) => turn.response,
    ).length;
    const orphanContext: OrphanedChatResponse = {
      sessionId: "",
      completedTurnCountAtSubmit,
      expectedMessageCount: completedTurnCountAtSubmit * 2 + 2,
    };
    setQuestion("");
    setError(null);
    requestAnimationFrame(adjustComposerHeight);
    setTurns((value) => [
      ...value,
      {
        id: turnId,
        question: trimmed,
        awaitingResponse: true,
      },
    ]);

    try {
      const response = await postChat(
        {
          mode,
          question: trimmed,
          selected_case_id: mode === "selected_case" ? selectedCaseId : undefined,
          session_id: sessionId,
        },
        { signal: abortController.signal },
      );
      if (
        abortController.signal.aborted ||
        requestGen !== chatRequestGenRef.current
      ) {
        if (response.session_id) {
          onOrphanedChatResponse?.({
            ...orphanContext,
            sessionId: response.session_id,
          });
        }
        return;
      }
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
              }
            : turn,
        ),
      );
    } catch (err: unknown) {
      if (
        abortController.signal.aborted ||
        requestGen !== chatRequestGenRef.current
      ) {
        setTurns((value) => value.filter((turn) => !turn.awaitingResponse));
        return;
      }
      setTurns((value) => value.filter((turn) => turn.id !== turnId));
      setQuestion(trimmed);
      setError(formatApiError(err, "Unknown error"));
    } finally {
      if (chatAbortRef.current === abortController) {
        chatAbortRef.current = null;
      }
      if (requestGen === chatRequestGenRef.current) {
        pendingQuestionRef.current = null;
      }
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
              {turn.awaitingResponse ? (
                <ChatTypingIndicator elapsedSeconds={waitingElapsedSec} />
              ) : null}
              {turn.response ? (
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
          {error || serverSyncError ? (
            <div className="mb-2 space-y-1 text-sm text-destructive">
              {error ? <p>{error}</p> : null}
              {serverSyncError ? <p>{serverSyncError}</p> : null}
            </div>
          ) : null}
          <div className="flex items-end gap-3 rounded-[26px] bg-muted/70 px-4 py-3 shadow-sm">
            <textarea
              ref={textareaRef}
              className="chat-scrollbar max-h-[200px] min-h-[24px] flex-1 resize-none overflow-y-auto border-0 bg-transparent py-0.5 text-sm leading-6 text-foreground outline-none placeholder:text-muted-foreground"
              placeholder={
                disabledReason
                  ? disabledReason
                  : hasSelectedCase
                    ? "Ask about this case or any technology topic..."
                    : "Ask about cases, the knowledge base, or technology topics..."
              }
              disabled={inputDisabled}
              rows={1}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              maxLength={maxQuestionChars}
            />
            {isBusy ? (
              <Button
                className="size-8 shrink-0 rounded-full"
                disabled={loadingHistory}
                size="icon"
                type="button"
                variant="outline"
                onClick={(event) => {
                  event.preventDefault();
                  cancelPendingChat();
                }}
              >
                <Square className="size-3.5 fill-current" />
                <span className="sr-only">Stop response</span>
              </Button>
            ) : (
              <Button
                className="size-8 shrink-0 rounded-full"
                disabled={
                  inputDisabled || !question.trim()
                }
                size="icon"
                type="submit"
              >
                <ArrowUp className="size-4" />
                <span className="sr-only">Send</span>
              </Button>
            )}
          </div>
          <p className="mt-3 text-center text-xs text-muted-foreground">
            AI Case Assistant can make mistakes. Check important info
          </p>
        </form>
      </div>
    </div>
  );
}
