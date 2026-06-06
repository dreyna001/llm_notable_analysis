import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  deleteChatSession,
  deleteLastChatTurn,
  fetchCapabilities,
  fetchCase,
  fetchChatSessionMessages,
  fetchChatSessions,
} from "../api/client";
import type {
  CaseSummary,
  ChatMode,
  ChatSessionMessage,
  PortalCapabilities,
} from "../types";
import { ChatAssistantControls } from "./ChatAssistantControls";
import { ConfirmDialog } from "./ConfirmDialog";
import {
  ChatPanel,
  type ChatPanelState,
  type ChatTurn,
  type OrphanedChatResponse,
} from "./ChatPanel";
import { PortalCapabilityBanner } from "./PortalCapabilityBanner";
import { PortalSidebar } from "./PortalSidebar";
import { caseDetailToSummary } from "../utils/caseSummary";
import { formatApiError } from "../utils/formatApiError";
import { sanitizeChatAnswer } from "../utils/sanitizeChatAnswer";
import {
  capChatSessionStore,
  capChatSessionStoreWithMeta,
  createEmptySession,
  DEFAULT_MAX_CHAT_SESSIONS,
  ensureChatSessionStore,
  findUnusedSession,
  isUnusedSession,
  loadChatSessionStore,
  saveChatSessionStore,
  sessionTitleFromQuestion,
  switchToChatContext,
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
  attachError?: string | null;
  onAttachCase?: (caseId: string) => void;
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
              answer_status: next.answer_status ?? "unknown",
            }
          : undefined,
    });
  }
  return turns;
}

function formatWorkspaceError(err: unknown, fallback: string): string {
  return formatApiError(err, fallback);
}

function applySessionCap(
  store: ChatSessionStore,
  maxSessions: number,
  onEvicted?: (count: number) => void,
): ChatSessionStore {
  const { store: capped, evictedCount } = capChatSessionStoreWithMeta(
    store,
    maxSessions,
  );
  if (evictedCount > 0) {
    onEvicted?.(evictedCount);
  }
  return capped;
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
  const merged = [...serverSessions, ...localOnly];
  if (!merged.length) {
    return ensureChatSessionStore(store);
  }
  return ensureChatSessionStore({
    activeLocalId: store.activeLocalId,
    sessions: merged,
  });
}

export function HomeChatWorkspace({
  sidebarMeta,
  selectedCaseId,
  selectedCaseName,
  selectedCaseProcessedAt,
  selectedCaseLoading,
  attachError,
  onAttachCase,
  onClearSelectedCase,
}: HomeChatWorkspaceProps) {
  const [store, setStore] = useState<ChatSessionStore>(() =>
    ensureChatSessionStore(loadChatSessionStore()),
  );
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<PortalCapabilities | null>(null);
  const [capabilitiesLoaded, setCapabilitiesLoaded] = useState(false);
  const [capabilitiesError, setCapabilitiesError] = useState(false);
  const [historyLoadError, setHistoryLoadError] = useState<string | null>(null);
  const [sessionCapNotice, setSessionCapNotice] = useState<string | null>(null);
  const maxChatSessions =
    capabilities?.max_chat_sessions_per_user ?? DEFAULT_MAX_CHAT_SESSIONS;
  const [attachedCasePreview, setAttachedCasePreview] = useState<CaseSummary | null>(
    null,
  );
  const [resolvedCaseById, setResolvedCaseById] = useState<
    Record<string, CaseSummary>
  >({});
  const [resolvingCaseId, setResolvingCaseId] = useState<string | null>(null);
  const [pendingDeleteSession, setPendingDeleteSession] =
    useState<StoredChatSession | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [orphanCleanupError, setOrphanCleanupError] = useState<string | null>(null);
  const sessionHistoryAbortRef = useRef<AbortController | null>(null);

  const sortedSessions = useMemo(
    () =>
      [...store.sessions].sort((left, right) =>
        right.updatedAt.localeCompare(left.updatedAt),
      ),
    [store.sessions],
  );

  const safeStore = useMemo(() => ensureChatSessionStore(store), [store]);

  const activeSession = useMemo(
    () =>
      safeStore.sessions.find(
        (session) => session.localId === safeStore.activeLocalId,
      ) ?? safeStore.sessions[0],
    [safeStore],
  );

  const hasCaseContext = Boolean(selectedCaseId || activeSession?.selectedCaseId);

  const capabilitiesReady =
    capabilitiesLoaded && !capabilitiesError && capabilities !== null;

  const availableModes = useMemo<ChatMode[]>(
    () => {
      if (!capabilitiesReady) {
        return [];
      }
      const modes: ChatMode[] = [];
      if (hasCaseContext) {
        modes.push("selected_case");
      }
      if (capabilities.global_retrieval_enabled) {
        modes.push("global_archive");
      }
      return modes;
    },
    [capabilities, capabilitiesReady, hasCaseContext],
  );

  const activeMode = useMemo(() => {
    const storedMode = activeSession?.mode;
    if (storedMode && availableModes.includes(storedMode)) {
      return storedMode;
    }
    if (selectedCaseId && availableModes.includes("selected_case")) {
      return "selected_case";
    }
    return availableModes[0] ?? "global_archive";
  }, [activeSession?.mode, availableModes, selectedCaseId]);

  const chatDisabledReason = useMemo(() => {
    if (!capabilitiesLoaded) {
      return "Checking portal capabilities…";
    }
    if (capabilitiesError) {
      return "Could not load portal capabilities.";
    }
    if (capabilities && !capabilities.case_qa_enabled) {
      return "Case Q&A is disabled on this portal. Chat is unavailable.";
    }
    if (!availableModes.length) {
      return "Select a case to chat. Cross-case archive chat is disabled for this portal.";
    }
    return undefined;
  }, [
    availableModes.length,
    capabilities,
    capabilitiesError,
    capabilitiesLoaded,
  ]);

  const noteSessionEviction = useCallback((count: number) => {
    if (count <= 0) {
      return;
    }
    setSessionCapNotice(
      "Oldest local chats were removed from this browser to stay within the session limit.",
    );
  }, []);

  const effectiveSelectedCaseId =
    activeMode === "selected_case"
      ? selectedCaseId ?? activeSession?.selectedCaseId
      : undefined;

  const resolvedCaseSummary = effectiveSelectedCaseId
    ? resolvedCaseById[effectiveSelectedCaseId]
    : undefined;

  const effectiveSelectedCaseName =
    effectiveSelectedCaseId === selectedCaseId
      ? selectedCaseName
      : attachedCasePreview?.case_id === effectiveSelectedCaseId
        ? attachedCasePreview.search_name ?? undefined
        : resolvedCaseSummary?.search_name ?? undefined;

  const effectiveSelectedCaseProcessedAt =
    effectiveSelectedCaseId === selectedCaseId
      ? selectedCaseProcessedAt
      : attachedCasePreview?.case_id === effectiveSelectedCaseId
        ? attachedCasePreview.processed_at ?? undefined
        : resolvedCaseSummary?.processed_at ?? undefined;

  const effectiveSelectedCaseLoading =
    effectiveSelectedCaseId === selectedCaseId
      ? selectedCaseLoading
      : resolvingCaseId === effectiveSelectedCaseId;

  const initialPanelTurns = useMemo(
    () => storedTurnsToPanelTurns(activeSession?.turns ?? []),
    [activeSession?.turns],
  );

  const panelResetKey = [
    activeSession?.localId ?? "",
    activeSession?.serverSessionId ?? "",
    loadingSessionId === activeSession?.localId ? "loading" : "ready",
  ].join(":");

  const persistStore = useCallback(
    (next: ChatSessionStore) => {
      const capped = ensureChatSessionStore(
        applySessionCap(next, maxChatSessions, noteSessionEviction),
      );
      setStore(capped);
      saveChatSessionStore(capped, maxChatSessions);
    },
    [maxChatSessions, noteSessionEviction],
  );

  useEffect(() => {
    if (
      safeStore.activeLocalId === store.activeLocalId &&
      safeStore.sessions === store.sessions
    ) {
      return;
    }
    persistStore(safeStore);
  }, [persistStore, safeStore, store.activeLocalId, store.sessions]);

  useEffect(() => {
    setStore((current) => {
      const capped = applySessionCap(current, maxChatSessions, noteSessionEviction);
      if (
        capped.sessions.length === current.sessions.length &&
        capped.activeLocalId === current.activeLocalId
      ) {
        return current;
      }
      saveChatSessionStore(capped, maxChatSessions);
      return capped;
    });
  }, [maxChatSessions, noteSessionEviction]);

  useEffect(() => {
    let cancelled = false;
    fetchChatSessions()
      .then((payload) => {
        if (cancelled || !payload.history_enabled || !payload.items.length) {
          return;
        }
        setStore((current) => {
          const merged = applySessionCap(
            mergeServerSessions(current, payload.items),
            maxChatSessions,
            noteSessionEviction,
          );
          saveChatSessionStore(merged, maxChatSessions);
          return merged;
        });
      })
      .catch(() => {
        // Local chat history remains available when server history is disabled.
      });
    return () => {
      cancelled = true;
    };
  }, [maxChatSessions, noteSessionEviction]);

  useEffect(() => {
    const caseId = effectiveSelectedCaseId;
    if (!caseId || caseId === selectedCaseId) {
      setResolvingCaseId(null);
      return;
    }
    if (attachedCasePreview?.case_id === caseId || resolvedCaseById[caseId]) {
      setResolvingCaseId(null);
      return;
    }

    let cancelled = false;
    setResolvingCaseId(caseId);
    fetchCase(caseId)
      .then((detail) => {
        if (!cancelled) {
          const summary = caseDetailToSummary(detail);
          setResolvedCaseById((current) => ({
            ...current,
            [caseId]: summary,
          }));
        }
      })
      .catch(() => {
        // Keep the case id visible when metadata cannot be loaded.
      })
      .finally(() => {
        if (!cancelled) {
          setResolvingCaseId((current) => (current === caseId ? null : current));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    attachedCasePreview?.case_id,
    effectiveSelectedCaseId,
    resolvedCaseById,
    selectedCaseId,
  ]);

  useEffect(() => {
    if (!selectedCaseId) {
      return;
    }
    setStore((current) => {
      const next = capChatSessionStore(
        switchToChatContext(current, "selected_case", selectedCaseId),
        maxChatSessions,
      );
      saveChatSessionStore(next, maxChatSessions);
      return next;
    });
  }, [maxChatSessions, selectedCaseId]);

  useEffect(() => {
    return () => {
      sessionHistoryAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    setOrphanCleanupError(null);
  }, [activeSession.localId]);

  useEffect(() => {
    let cancelled = false;
    fetchCapabilities()
      .then((payload) => {
        if (!cancelled) {
          setCapabilities(payload);
          setCapabilitiesError(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCapabilities(null);
          setCapabilitiesError(true);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCapabilitiesLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleNewChat = useCallback(() => {
    setStore((current) => {
      const active = current.sessions.find(
        (item) => item.localId === current.activeLocalId,
      );
      if (active && isUnusedSession(active)) {
        return current;
      }

      const existingUnused = findUnusedSession(current.sessions);
      if (existingUnused) {
        const next = { ...current, activeLocalId: existingUnused.localId };
        const capped = ensureChatSessionStore(
          capChatSessionStore(next, maxChatSessions),
        );
        saveChatSessionStore(capped, maxChatSessions);
        return capped;
      }

      const session = createEmptySession(
        selectedCaseId ? "selected_case" : "global_archive",
        selectedCaseId,
      );
      const next = {
        activeLocalId: session.localId,
        sessions: [session, ...current.sessions],
      };
      const capped = ensureChatSessionStore(
        capChatSessionStore(next, maxChatSessions),
      );
      saveChatSessionStore(capped, maxChatSessions);
      return capped;
    });
  }, [maxChatSessions, selectedCaseId]);

  const handleSelectSession = useCallback(
    async (localId: string) => {
      setHistoryLoadError(null);
      let targetSession: StoredChatSession | null = null;
      let shouldLoadHistory = false;

      setStore((current) => {
        const session = current.sessions.find((item) => item.localId === localId);
        if (!session || session.localId === current.activeLocalId) {
          return current;
        }
        targetSession = session;
        shouldLoadHistory = Boolean(
          session.serverSessionId && session.turns.length === 0,
        );
        const next = { ...current, activeLocalId: localId };
        const capped = capChatSessionStore(next, maxChatSessions);
        saveChatSessionStore(capped, maxChatSessions);
        return capped;
      });

      if (!targetSession) {
        return;
      }

      const session = targetSession;
      sessionHistoryAbortRef.current?.abort();
      const abortController = new AbortController();
      sessionHistoryAbortRef.current = abortController;

      if (session.mode === "selected_case" && session.selectedCaseId) {
        onAttachCase?.(session.selectedCaseId);
      } else {
        onClearSelectedCase?.();
      }

      if (!shouldLoadHistory || !session.serverSessionId) {
        return;
      }

      const serverSessionId = session.serverSessionId;
      setLoadingSessionId(localId);
      try {
        const payload = await fetchChatSessionMessages(serverSessionId, {
          signal: abortController.signal,
        });
        if (abortController.signal.aborted) {
          return;
        }

        const turns = messagesToStoredTurns(payload.messages);
        setStore((current) => {
          if (current.activeLocalId !== localId) {
            return current;
          }
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
          const capped = capChatSessionStore(next, maxChatSessions);
          saveChatSessionStore(capped, maxChatSessions);
          return capped;
        });

        if (abortController.signal.aborted) {
          return;
        }

        if (payload.mode === "selected_case" && payload.selected_case_id) {
          onAttachCase?.(payload.selected_case_id);
        } else {
          onClearSelectedCase?.();
        }
      } catch (err: unknown) {
        if (abortController.signal.aborted) {
          return;
        }
        setHistoryLoadError(
          `Could not load chat history. ${formatWorkspaceError(err, "Unknown error")}`,
        );
      } finally {
        setLoadingSessionId((current) => (current === localId ? null : current));
      }
    },
    [maxChatSessions, onAttachCase, onClearSelectedCase],
  );

  const handleModeChange = useCallback(
    (mode: ChatMode) => {
      if (mode === "global_archive") {
        setAttachedCasePreview(null);
        onClearSelectedCase?.();
      }
      setStore((current) => {
        const next = switchToChatContext(
          current,
          mode,
          mode === "selected_case"
            ? current.sessions.find(
                (session) => session.localId === current.activeLocalId,
              )?.selectedCaseId ?? selectedCaseId
            : undefined,
        );
        const capped = capChatSessionStore(next, maxChatSessions);
        saveChatSessionStore(capped, maxChatSessions);
        return capped;
      });
    },
    [maxChatSessions, onClearSelectedCase, selectedCaseId],
  );

  const handleAttachCase = useCallback(
    (caseSummary: CaseSummary) => {
      setAttachedCasePreview(caseSummary);
      setStore((current) => {
        const next = capChatSessionStore(
          switchToChatContext(current, "selected_case", caseSummary.case_id),
          maxChatSessions,
        );
        saveChatSessionStore(next, maxChatSessions);
        return next;
      });
      onAttachCase?.(caseSummary.case_id);
    },
    [maxChatSessions, onAttachCase],
  );

  const handleClearSelectedCase = useCallback(() => {
    setAttachedCasePreview(null);
    if (capabilitiesReady && capabilities?.global_retrieval_enabled) {
      setStore((current) => {
        const next = capChatSessionStore(
          switchToChatContext(current, "global_archive"),
          maxChatSessions,
        );
        saveChatSessionStore(next, maxChatSessions);
        return next;
      });
    }
    onClearSelectedCase?.();
  }, [
    capabilities?.global_retrieval_enabled,
    capabilitiesReady,
    maxChatSessions,
    onClearSelectedCase,
  ]);

  const requestDeleteSession = useCallback(
    (localId: string) => {
      const session = store.sessions.find((item) => item.localId === localId);
      if (!session) {
        return;
      }
      setDeleteError(null);
      setPendingDeleteSession(session);
    },
    [store.sessions],
  );

  const cancelDeleteSession = useCallback(() => {
    if (deleteBusy) {
      return;
    }
    setPendingDeleteSession(null);
    setDeleteError(null);
  }, [deleteBusy]);

  const confirmDeleteSession = useCallback(async () => {
    const session = pendingDeleteSession;
    if (!session || deleteBusy) {
      return;
    }

    setDeleteBusy(true);
    setDeleteError(null);
    const localId = session.localId;

    try {
      if (session.serverSessionId) {
        try {
          await deleteChatSession(session.serverSessionId);
        } catch (err: unknown) {
          if (!(err instanceof ApiError && err.status === 404)) {
            throw err;
          }
        }
      }

      setStore((current) => {
        const remaining = current.sessions.filter((item) => item.localId !== localId);
        let next: ChatSessionStore;
        if (!remaining.length) {
          const replacement = createEmptySession(
            selectedCaseId ? "selected_case" : "global_archive",
            selectedCaseId,
          );
          next = {
            activeLocalId: replacement.localId,
            sessions: [replacement],
          };
        } else {
          next = {
            activeLocalId:
              current.activeLocalId === localId
                ? remaining[0].localId
                : current.activeLocalId,
            sessions: remaining,
          };
        }
        const capped = ensureChatSessionStore(
          capChatSessionStore(next, maxChatSessions),
        );
        saveChatSessionStore(capped, maxChatSessions);
        return capped;
      });
      setPendingDeleteSession(null);
    } catch (err: unknown) {
      const message = formatWorkspaceError(err, "Unknown error");
      setDeleteError(message);
    } finally {
      setDeleteBusy(false);
    }
  }, [
    deleteBusy,
    maxChatSessions,
    pendingDeleteSession,
    selectedCaseId,
  ]);

  const syncPanelState = useCallback(
    (state: ChatPanelState, options?: { removeEmptySession?: boolean }) => {
      setStore((current) => {
        const active = current.sessions.find(
          (session) => session.localId === current.activeLocalId,
        );
        if (!active) {
          return current;
        }

        const storedTurns = panelTurnsToStoredTurns(state.turns);
        const isEmpty = storedTurns.length === 0;

        if (
          options?.removeEmptySession &&
          isEmpty &&
          isUnusedSession({ ...active, turns: storedTurns })
        ) {
          const remaining = current.sessions.filter(
            (session) => session.localId !== active.localId,
          );
          if (remaining.length > 0) {
            const next: ChatSessionStore = {
              activeLocalId: remaining[0].localId,
              sessions: remaining,
            };
            const capped = capChatSessionStore(next, maxChatSessions);
            saveChatSessionStore(capped, maxChatSessions);
            return capped;
          }
        }

        const firstQuestion = storedTurns[0]?.question ?? "";
        const title = isEmpty
          ? "New chat"
          : active.title === "New chat" && firstQuestion
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
                  selectedCaseId:
                    state.mode === "selected_case"
                      ? active.selectedCaseId ?? selectedCaseId
                      : undefined,
                  serverSessionId: state.sessionId ?? session.serverSessionId,
                  turns: storedTurns,
                }
              : session,
          ),
        };
        const capped = capChatSessionStore(next, maxChatSessions);
        saveChatSessionStore(capped, maxChatSessions);
        return capped;
      });
    },
    [maxChatSessions, selectedCaseId],
  );

  const handlePanelStateChange = useCallback(
    (state: ChatPanelState) => {
      syncPanelState(state);
    },
    [syncPanelState],
  );

  const handleChatCancelled = useCallback(
    (state: ChatPanelState) => {
      syncPanelState(state, { removeEmptySession: true });
    },
    [syncPanelState],
  );

  const handleOrphanedChatResponse = useCallback(
    (payload: OrphanedChatResponse) => {
      if (!capabilities?.chat_history_enabled) {
        return;
      }

      void (async () => {
        const snapshot = loadChatSessionStore(maxChatSessions);
        const linkedSession = snapshot.sessions.find(
          (session) => session.serverSessionId === payload.sessionId,
        );
        const completedTurnsNow =
          linkedSession?.turns.filter((turn) => turn.response).length ?? 0;
        if (completedTurnsNow > payload.completedTurnCountAtSubmit) {
          return;
        }

        try {
          if (payload.completedTurnCountAtSubmit === 0) {
            await deleteChatSession(payload.sessionId);
            setStore((current) => {
              const next: ChatSessionStore = {
                ...current,
                sessions: current.sessions.map((session) =>
                  session.serverSessionId === payload.sessionId
                    ? { ...session, serverSessionId: null }
                    : session,
                ),
              };
              const capped = capChatSessionStore(next, maxChatSessions);
              saveChatSessionStore(capped, maxChatSessions);
              return capped;
            });
            setOrphanCleanupError(null);
            return;
          }

          await deleteLastChatTurn(payload.sessionId, {
            expectedMessageCount: payload.expectedMessageCount,
          });
          setOrphanCleanupError(null);
        } catch (err: unknown) {
          if (
            err instanceof ApiError &&
            (err.status === 404 || err.status === 409)
          ) {
            setOrphanCleanupError(null);
            return;
          }
          const detail = formatWorkspaceError(
            err,
            "Could not reach the server.",
          );
          setOrphanCleanupError(
            `Stopped locally, but the server could not remove the cancelled reply. Saved chat history may be out of sync. (${detail})`,
          );
        }
      })();
    },
    [capabilities?.chat_history_enabled, maxChatSessions],
  );

  return (
    <div className="flex h-full min-h-0 w-full">
      <PortalSidebar
        activeLocalId={store.activeLocalId}
        assistantControls={
          <ChatAssistantControls
            mode={activeMode}
            modes={availableModes.length ? availableModes : [activeMode]}
            selectedCaseId={effectiveSelectedCaseId}
            selectedCaseLoading={effectiveSelectedCaseLoading}
            selectedCaseName={effectiveSelectedCaseName}
            selectedCaseProcessedAt={effectiveSelectedCaseProcessedAt}
            caseAttachEnabled={capabilitiesReady && capabilities.case_qa_enabled}
            onAttachCase={handleAttachCase}
            onClearSelectedCase={handleClearSelectedCase}
            onModeChange={handleModeChange}
          />
        }
        meta={sidebarMeta}
        sessions={sortedSessions}
        onNewChat={handleNewChat}
        onDeleteSession={requestDeleteSession}
        onSelectSession={(localId) => {
          void handleSelectSession(localId);
        }}
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <PortalCapabilityBanner
          capabilities={capabilities}
          capabilitiesLoaded={capabilitiesLoaded}
          capabilitiesError={capabilitiesError}
          attachError={attachError}
          historyLoadError={historyLoadError}
          sessionCapNotice={sessionCapNotice}
          chatDisabledReason={chatDisabledReason}
        />
        <ChatPanel
          key={activeSession.localId}
          initialSessionId={activeSession.serverSessionId}
          initialTurns={initialPanelTurns}
          loadingHistory={loadingSessionId === activeSession.localId}
          maxQuestionChars={capabilities?.max_question_chars}
          mode={activeMode}
          resetKey={panelResetKey}
          selectedCaseId={effectiveSelectedCaseId}
          disabledReason={chatDisabledReason}
          composerDisabled={!capabilitiesLoaded || capabilitiesError}
          serverSyncError={orphanCleanupError}
          onStateChange={handlePanelStateChange}
          onChatCancelled={handleChatCancelled}
          onOrphanedChatResponse={handleOrphanedChatResponse}
        />
      </div>
      <ConfirmDialog
        cancelLabel="Cancel"
        confirmLabel="Delete chat"
        confirming={deleteBusy}
        description={
          pendingDeleteSession
            ? `Delete "${pendingDeleteSession.title}" and all its messages? This cannot be undone.`
            : ""
        }
        error={deleteError}
        open={pendingDeleteSession !== null}
        title="Delete chat?"
        onCancel={cancelDeleteSession}
        onConfirm={() => {
          void confirmDeleteSession();
        }}
      />
    </div>
  );
}
