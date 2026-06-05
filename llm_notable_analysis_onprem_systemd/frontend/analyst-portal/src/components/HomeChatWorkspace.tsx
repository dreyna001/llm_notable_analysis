import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, deleteChatSession, fetchChatSessionMessages, fetchChatSessions } from "../api/client";
import type { ChatMode, ChatSessionMessage } from "../types";
import { ChatAssistantControls } from "./ChatAssistantControls";
import { ChatPanel, type ChatPanelState, type ChatTurn } from "./ChatPanel";
import { PortalSidebar } from "./PortalSidebar";
import { sanitizeChatAnswer } from "../utils/sanitizeChatAnswer";
import {
  createEmptySession,
  findUnusedSession,
  isUnusedSession,
  loadChatSessionStore,
  saveChatSessionStore,
  sessionTitleFromQuestion,
  type ChatSessionStore,
  type StoredChatSession,
  type StoredChatTurn,
} from "../utils/chatSessionStore";

type HomeChatWorkspaceProps = {
  sidebarMeta: ReactNode;
  selectedCaseId?: string;
  selectedCaseName?: string;
  selectedCaseProcessedAt?: string;
  selectedCaseLoading?: boolean;
  onClearSelectedCase?: () => void;
};

function storedTurnsToPanelTurns(turns: StoredChatTurn[]): ChatTurn[] {
  return turns.map((turn) => ({
    id: turn.id,
    question: turn.question,
    response: turn.response
      ? {
          answer: sanitizeChatAnswer(turn.response.answer),
          answer_status: turn.response.answer_status,
          session_id: null,
        }
      : undefined,
    awaitingResponse: false,
    streaming: false,
  }));
}

function panelTurnsToStoredTurns(turns: ChatTurn[]): StoredChatTurn[] {
  return turns
    .filter((turn) => !turn.awaitingResponse)
    .map((turn) => ({
      id: turn.id,
      question: turn.question,
      response: turn.response
        ? {
            answer: turn.response.answer,
            answer_status: turn.response.answer_status,
          }
        : undefined,
    }));
}

function messagesToStoredTurns(messages: ChatSessionMessage[]): StoredChatTurn[] {
  const turns: StoredChatTurn[] = [];
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (message.role !== "user") {
      continue;
    }
    const next = messages[index + 1];
    turns.push({
      id: `loaded-${index}`,
      question: message.content,
      response:
        next?.role === "assistant"
          ? {
              answer: sanitizeChatAnswer(next.content),
              answer_status: "answered",
            }
          : undefined,
    });
  }
  return turns;
}

function mergeServerSessions(
  store: ChatSessionStore,
  serverItems: Array<{
    session_id: string;
    title: string;
    mode: ChatMode;
    selected_case_id: string | null;
    updated_at: string | null;
  }>,
): ChatSessionStore {
  const localOnly = store.sessions.filter((session) => !session.serverSessionId);
  const serverSessions: StoredChatSession[] = serverItems.map((item) => {
    const existing = store.sessions.find(
      (session) => session.serverSessionId === item.session_id,
    );
    return {
      localId: existing?.localId ?? item.session_id,
      serverSessionId: item.session_id,
      title: item.title || "New chat",
      updatedAt: item.updated_at ?? new Date().toISOString(),
      mode: item.mode,
      selectedCaseId: item.selected_case_id ?? undefined,
      turns: existing?.turns ?? [],
    };
  });
  return {
    activeLocalId: store.activeLocalId,
    sessions: [...serverSessions, ...localOnly],
  };
}

export function HomeChatWorkspace({
  sidebarMeta,
  selectedCaseId,
  selectedCaseName,
  selectedCaseProcessedAt,
  selectedCaseLoading,
  onClearSelectedCase,
}: HomeChatWorkspaceProps) {
  const [store, setStore] = useState<ChatSessionStore>(() => loadChatSessionStore());
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);

  const availableModes = useMemo<ChatMode[]>(
    () => (selectedCaseId ? ["selected_case", "global_archive"] : ["global_archive"]),
    [selectedCaseId],
  );

  const sortedSessions = useMemo(
    () =>
      [...store.sessions].sort((left, right) =>
        right.updatedAt.localeCompare(left.updatedAt),
      ),
    [store.sessions],
  );

  const activeSession = useMemo(
    () =>
      store.sessions.find((session) => session.localId === store.activeLocalId) ??
      store.sessions[0],
    [store],
  );

  const activeMode = useMemo(() => {
    const mode = activeSession?.mode ?? "global_archive";
    return availableModes.includes(mode) ? mode : "global_archive";
  }, [activeSession?.mode, availableModes]);

  const persistStore = useCallback((next: ChatSessionStore) => {
    setStore(next);
    saveChatSessionStore(next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchChatSessions()
      .then((payload) => {
        if (cancelled || !payload.history_enabled || !payload.items.length) {
          return;
        }
        setStore((current) => {
          const merged = mergeServerSessions(current, payload.items);
          saveChatSessionStore(merged);
          return merged;
        });
      })
      .catch(() => {
        // Local chat history remains available when server history is disabled.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleNewChat = useCallback(() => {
    const active = store.sessions.find((item) => item.localId === store.activeLocalId);
    if (active && isUnusedSession(active)) {
      return;
    }

    const existingUnused = findUnusedSession(store.sessions);
    if (existingUnused) {
      persistStore({ ...store, activeLocalId: existingUnused.localId });
      return;
    }

    const session = createEmptySession(
      selectedCaseId ? "selected_case" : "global_archive",
      selectedCaseId,
    );
    persistStore({
      activeLocalId: session.localId,
      sessions: [session, ...store.sessions],
    });
  }, [persistStore, selectedCaseId, store]);

  const handleSelectSession = useCallback(
    async (localId: string) => {
      const session = store.sessions.find((item) => item.localId === localId);
      if (!session || session.localId === store.activeLocalId) {
        return;
      }

      persistStore({ ...store, activeLocalId: localId });

      if (!session.serverSessionId || session.turns.length) {
        return;
      }

      setLoadingSessionId(localId);
      try {
        const payload = await fetchChatSessionMessages(session.serverSessionId);
        const turns = messagesToStoredTurns(payload.messages);
        setStore((current) => {
          const next: ChatSessionStore = {
            ...current,
            sessions: current.sessions.map((item) =>
              item.localId === localId
                ? {
                    ...item,
                    mode: payload.mode,
                    selectedCaseId: payload.selected_case_id ?? undefined,
                    turns,
                  }
                : item,
            ),
          };
          saveChatSessionStore(next);
          return next;
        });
      } catch (err: unknown) {
        const message =
          err instanceof ApiError
            ? `${err.status}: ${err.message}`
            : err instanceof Error
              ? err.message
              : "Unknown error";
        window.alert(message);
      } finally {
        setLoadingSessionId(null);
      }
    },
    [persistStore, store],
  );

  const handleModeChange = useCallback(
    (mode: ChatMode) => {
      if (!activeSession) {
        return;
      }
      persistStore({
        ...store,
        sessions: store.sessions.map((session) =>
          session.localId === activeSession.localId ? { ...session, mode } : session,
        ),
      });
    },
    [activeSession, persistStore, store],
  );

  const handleDeleteSession = useCallback(
    async (localId: string) => {
      const session = store.sessions.find((item) => item.localId === localId);
      if (!session) {
        return;
      }

      const confirmed = window.confirm(
        `Delete "${session.title}" and all its messages? This cannot be undone.`,
      );
      if (!confirmed) {
        return;
      }

      if (session.serverSessionId) {
        try {
          await deleteChatSession(session.serverSessionId);
        } catch (err: unknown) {
          if (!(err instanceof ApiError && err.status === 404)) {
            const message =
              err instanceof ApiError
                ? `${err.status}: ${err.message}`
                : err instanceof Error
                  ? err.message
                  : "Unknown error";
            window.alert(message);
            return;
          }
        }
      }

      const remaining = store.sessions.filter((item) => item.localId !== localId);
      if (!remaining.length) {
        const replacement = createEmptySession(
          selectedCaseId ? "selected_case" : "global_archive",
          selectedCaseId,
        );
        persistStore({
          activeLocalId: replacement.localId,
          sessions: [replacement],
        });
        return;
      }

      persistStore({
        activeLocalId:
          store.activeLocalId === localId ? remaining[0].localId : store.activeLocalId,
        sessions: remaining,
      });
    },
    [persistStore, selectedCaseId, store],
  );

  const handlePanelStateChange = useCallback(
    (state: ChatPanelState) => {
      setStore((current) => {
        const active = current.sessions.find(
          (session) => session.localId === current.activeLocalId,
        );
        if (!active) {
          return current;
        }
        const storedTurns = panelTurnsToStoredTurns(state.turns);
        const firstQuestion = storedTurns[0]?.question ?? "";
        const title =
          active.title === "New chat" && firstQuestion
            ? sessionTitleFromQuestion(firstQuestion)
            : active.title;
        const next: ChatSessionStore = {
          ...current,
          sessions: current.sessions.map((session) =>
            session.localId === active.localId
              ? {
                  ...session,
                  title,
                  updatedAt: new Date().toISOString(),
                  mode: state.mode,
                  selectedCaseId,
                  serverSessionId: state.sessionId ?? session.serverSessionId,
                  turns: storedTurns,
                }
              : session,
          ),
        };
        saveChatSessionStore(next);
        return next;
      });
    },
    [selectedCaseId],
  );

  if (!activeSession) {
    return null;
  }

  return (
    <div className="flex h-full min-h-0 w-full">
      <PortalSidebar
        activeLocalId={store.activeLocalId}
        assistantControls={
          <ChatAssistantControls
            mode={activeMode}
            modes={availableModes}
            selectedCaseId={selectedCaseId}
            selectedCaseLoading={selectedCaseLoading}
            selectedCaseName={selectedCaseName}
            selectedCaseProcessedAt={selectedCaseProcessedAt}
            onClearSelectedCase={onClearSelectedCase}
            onModeChange={handleModeChange}
          />
        }
        meta={sidebarMeta}
        sessions={sortedSessions}
        onNewChat={handleNewChat}
        onDeleteSession={(localId) => {
          void handleDeleteSession(localId);
        }}
        onSelectSession={(localId) => {
          void handleSelectSession(localId);
        }}
      />
      <ChatPanel
        key={activeSession.localId}
        initialSessionId={activeSession.serverSessionId}
        initialTurns={storedTurnsToPanelTurns(activeSession.turns)}
        loadingHistory={loadingSessionId === activeSession.localId}
        mode={activeMode}
        selectedCaseId={selectedCaseId}
        onStateChange={handlePanelStateChange}
      />
    </div>
  );
}
