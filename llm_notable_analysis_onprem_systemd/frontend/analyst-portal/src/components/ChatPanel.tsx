import { ArrowUp, ImagePlus, Square, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { postChat } from "../api/client";
import type {
  ChatContextUsage,
  ChatImagePayload,
  ChatMode,
  ChatResponse,
} from "../types";
import {
  formatChatApiError,
  isChatRecoverableServerSession,
} from "../utils/formatApiError";
import { answerStatusLabel, shouldShowAnswerStatus } from "../utils/answerStatus";
import { resolveChatEmptyState } from "../utils/chatEmptyState";
import {
  CHAT_IMAGE_ACCEPT_ATTR,
  fileToChatImagePayload,
  formatChatImageFileSize,
  validateChatImageFile,
} from "../utils/chatImageAttachment";
import { sanitizeChatAnswer } from "../utils/sanitizeChatAnswer";
import { ChatConversationSkeleton } from "./LoadingSkeletons";
import { ContextUsageIndicator } from "./ContextUsageIndicator";
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
  loadingHistory?: boolean;
  maxQuestionChars?: number;
  chatImagesEnabled?: boolean;
  maxChatImages?: number;
  maxChatImageBytes?: number;
  disabledReason?: string;
  composerDisabled?: boolean;
  serverSyncError?: string | null;
  onStateChange?: (state: ChatPanelState) => void;
  onChatCancelled?: (state: ChatPanelState) => void;
  onOrphanedChatResponse?: (payload: OrphanedChatResponse) => void;
};

type ComposerAttachment = {
  file: File;
  previewUrl: string;
  name: string;
  size: number;
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
  maxQuestionChars,
  chatImagesEnabled = false,
  maxChatImages,
  maxChatImageBytes,
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
  const [attachment, setAttachment] = useState<ComposerAttachment | null>(null);
  const [attachmentConverting, setAttachmentConverting] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatAbortRef = useRef<AbortController | null>(null);
  const chatRequestGenRef = useRef(0);
  const pendingQuestionRef = useRef<string | null>(null);
  const pendingAttachmentPayloadRef = useRef<ChatImagePayload | null>(null);

  const imageUploadEnabled =
    chatImagesEnabled === true && (maxChatImages ?? 1) >= 1;

  const buildPanelState = useCallback(
    (nextTurns: ChatTurn[]): ChatPanelState => ({
      turns: nextTurns,
      sessionId,
      mode,
    }),
    [mode, sessionId],
  );

  const isBusy = turns.some((turn) => turn.awaitingResponse);
  const inputDisabled =
    Boolean(disabledReason) || composerDisabled || loadingHistory;
  const sendDisabled =
    inputDisabled || !question.trim() || attachmentConverting;
  const latestContextUsage = [...turns]
    .reverse()
    .find((turn) => turn.response?.context_usage)?.response?.context_usage as
    | ChatContextUsage
    | null
    | undefined;

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

  const clearAttachment = useCallback(() => {
    setAttachment((current) => {
      if (current?.previewUrl) {
        URL.revokeObjectURL(current.previewUrl);
      }
      return null;
    });
    pendingAttachmentPayloadRef.current = null;
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, []);

  useEffect(() => {
    return () => {
      if (attachment?.previewUrl) {
        URL.revokeObjectURL(attachment.previewUrl);
      }
    };
  }, [attachment?.previewUrl]);

  function handleAttachmentSelect(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    const validationError = validateChatImageFile(file, {
      maxBytes: maxChatImageBytes,
    });
    if (validationError) {
      setError(validationError);
      return;
    }

    setAttachment((current) => {
      if (current?.previewUrl) {
        URL.revokeObjectURL(current.previewUrl);
      }
      const previewUrl = URL.createObjectURL(file);
      return {
        file,
        previewUrl,
        name: file.name,
        size: file.size,
      };
    });
    pendingAttachmentPayloadRef.current = null;
    setError(null);
  }

  function handleRemoveAttachment() {
    clearAttachment();
    setError(null);
  }

  async function resolveRequestImages(): Promise<ChatImagePayload[] | undefined> {
    if (!attachment) {
      return undefined;
    }
    if (pendingAttachmentPayloadRef.current) {
      return [pendingAttachmentPayloadRef.current];
    }

    setAttachmentConverting(true);
    try {
      const payload = await fileToChatImagePayload(attachment.file);
      pendingAttachmentPayloadRef.current = payload;
      return [payload];
    } finally {
      setAttachmentConverting(false);
    }
  }

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
    clearAttachment();
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

    let requestImages: ChatImagePayload[] | undefined;
    try {
      requestImages = await resolveRequestImages();
    } catch {
      setError("Could not read the selected image. Try choosing a different file.");
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
      const requestChat = (activeSessionId: string | null) =>
        postChat(
          {
            mode,
            question: trimmed,
            selected_case_id:
              mode === "selected_case" ? selectedCaseId : undefined,
            session_id: activeSessionId,
            ...(requestImages ? { images: requestImages } : {}),
          },
          { signal: abortController.signal },
        );

      let response;
      try {
        response = await requestChat(sessionId);
      } catch (err: unknown) {
        if (
          sessionId &&
          isChatRecoverableServerSession(err) &&
          !abortController.signal.aborted &&
          requestGen === chatRequestGenRef.current
        ) {
          setSessionId(null);
          response = await requestChat(null);
        } else {
          throw err;
        }
      }
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
      clearAttachment();
    } catch (err: unknown) {
      if (
        abortController.signal.aborted ||
        requestGen !== chatRequestGenRef.current
      ) {
        setTurns((value) => value.filter((turn) => !turn.awaitingResponse));
        clearAttachment();
        return;
      }
      setTurns((value) => value.filter((turn) => turn.id !== turnId));
      setQuestion(trimmed);
      if (isChatRecoverableServerSession(err)) {
        setSessionId(null);
      }
      setError(formatChatApiError(err, "Unknown error"));
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
  const chatEmptyState = resolveChatEmptyState(mode, selectedCaseId);

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
          {loadingHistory ? <ChatConversationSkeleton /> : null}
          {showEmptyState ? (
            <div className="text-center">
              <h2 className="text-lg font-medium tracking-tight">
                {chatEmptyState.title}
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {chatEmptyState.description}
              </p>
            </div>
          ) : null}
          {turns.map((turn) => (
            <div className="flex flex-col gap-4" key={turn.id}>
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-md bg-muted px-4 py-2.5 text-sm leading-relaxed">
                  {turn.question}
                </div>
              </div>
              {turn.awaitingResponse ? (
                <ChatTypingIndicator elapsedSeconds={waitingElapsedSec} />
              ) : null}
              {turn.response ? (
                <div className="space-y-1">
                  <MarkdownMessage
                    className={cn(
                      assistantStatusClass(turn.response.answer_status),
                    )}
                    text={sanitizeChatAnswer(turn.response.answer)}
                  />
                  {shouldShowAnswerStatus(turn.response.answer_status) ? (
                    <p
                      className={cn(
                        "text-xs",
                        assistantStatusClass(turn.response.answer_status),
                      )}
                    >
                      {answerStatusLabel(turn.response.answer_status)}
                    </p>
                  ) : null}
                </div>
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
          {imageUploadEnabled && attachment ? (
            <div className="mb-2 flex items-center gap-3 rounded-md border border-border bg-muted/40 px-3 py-2">
              <img
                alt=""
                className="size-10 shrink-0 rounded object-cover"
                src={attachment.previewUrl}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{attachment.name}</p>
                <p className="text-xs text-muted-foreground">
                  {formatChatImageFileSize(attachment.size)}
                </p>
              </div>
              <Button
                aria-label="Remove attached image"
                className="size-8 shrink-0"
                disabled={inputDisabled || attachmentConverting || isBusy}
                size="icon"
                type="button"
                variant="ghost"
                onClick={handleRemoveAttachment}
              >
                <X className="size-4" />
              </Button>
            </div>
          ) : null}
          {imageUploadEnabled && attachmentConverting ? (
            <p className="mb-2 text-sm text-muted-foreground">
              Preparing image...
            </p>
          ) : null}
          <div className="flex items-end gap-3 rounded-lg bg-muted/70 px-4 py-3 shadow-sm">
            {imageUploadEnabled ? (
              <>
                <input
                  ref={fileInputRef}
                  accept={CHAT_IMAGE_ACCEPT_ATTR}
                  className="sr-only"
                  disabled={inputDisabled || attachmentConverting || isBusy}
                  tabIndex={-1}
                  type="file"
                  onChange={handleAttachmentSelect}
                />
                <Button
                  aria-label="Attach image"
                  className="size-8 shrink-0 rounded-md"
                  disabled={
                    inputDisabled ||
                    attachmentConverting ||
                    isBusy ||
                    Boolean(attachment)
                  }
                  size="icon"
                  type="button"
                  variant="ghost"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <ImagePlus className="size-4" />
                </Button>
              </>
            ) : null}
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
            <ContextUsageIndicator
              disabled={inputDisabled}
              draftQuestion={question}
              usage={latestContextUsage ?? null}
            />
            {isBusy ? (
              <Button
                className="size-8 shrink-0 rounded-md"
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
                className="size-8 shrink-0 rounded-md"
                disabled={sendDisabled}
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
