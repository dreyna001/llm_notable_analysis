import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { flushSync } from "react-dom";
import {
  ApiError,
  deleteChatSession,
  deleteLastChatTurn,
  fetchCapabilities,
  fetchCase,
  fetchChatSessionMessages,
  fetchChatSessions,
  isCancelledRequest,
} from "../api/client";
import type {
  CaseSummary,
  ChatMode,
  ChatSessionMessage,
  PortalCapabilities,
} from "../types";
import { resolveChatUnavailableReason } from "../utils/chatDependencyStatus";
import { ChatAssistantControls } from "./ChatAssistantControls";
import { ConfirmDialog } from "./ConfirmDialog";
import {
  ChatPanel,
  type ChatPanelState,
  type ChatTurn,
  type OrphanedChatResponse,
} from "./ChatPanel";
import { CaseArchiveNoticeBanner } from "./CaseArchiveNoticeBanner";
import { PortalWorkspaceSkeleton } from "./LoadingSkeletons";
import { PortalCapabilityBanner } from "./PortalCapabilityBanner";
import { PortalLoadFailure } from "./PortalLoadFailure";
import { PortalSidebar } from "./PortalSidebar";
import { caseDetailToSummary } from "../utils/caseSummary";
import { formatApiError, formatChatApiError } from "../utils/formatApiError";
import { sanitizeChatAnswer } from "../utils/sanitizeChatAnswer";
import {
  capChatSessionStore,
  capChatSessionStoreWithMeta,
  clearChatSessionStore,
  createEmptySession,
  DEFAULT_MAX_CHAT_SESSIONS,
  ensureChatSessionStore,
  findUnusedSession,
  isUnusedSession,
  loadChatSessionStore,
  resolveNewChatContext,
  resolveSyncedServerSessionId,
  saveChatSessionStore,
  sessionMatchesContext,
  sessionTitleFromQuestion,
  detachActiveCase,
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
  archiveNotices?: string[];
  onAttachCase?: (caseId: string) => void;
  onClearSelectedCase?: () => void;
  onCapabilitiesLoaded?: (capabilities: PortalCapabilities) => void;
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

function formatWorkspaceError(
  err: unknown,
  fallback: string,
  options?: { chatContext?: boolean },
): string {
  if (options?.chatContext) {
    return formatChatApiError(err, fallback);
  }
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

function createInitialStore(): ChatSessionStore {
  const session = createEmptySession();
  return {
    activeLocalId: session.localId,
    sessions: [session],
  };
}

export function HomeChatWorkspace({
  sidebarMeta,
  selectedCaseId,
  selectedCaseName,
  selectedCaseProcessedAt,
  selectedCaseLoading,
  attachError,
  archiveNotices,
  onAttachCase,
  onClearSelectedCase,
  onCapabilitiesLoaded,
}: HomeChatWorkspaceProps) {
  const [store, setStore] = useState<ChatSessionStore>(() =>
    createInitialStore(),
  );
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<PortalCapabilities | null>(null);
  const [capabilitiesLoaded, setCapabilitiesLoaded] = useState(false);
  const [capabilitiesLoadError, setCapabilitiesLoadError] = useState<string | null>(
    null,
  );
  const [historyLoadError, setHistoryLoadError] = useState<string | null>(null);
  const [sessionCapNotice, setSessionCapNotice] = useState<string | null>(null);
  const maxChatSessions =
    capabilities?.max_chat_sessions_per_user ?? DEFAULT_MAX_CHAT_SESSIONS;
  const serverHistoryEnabled = capabilities?.chat_history_enabled === true;
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
  const loadedPersistentStoreRef = useRef(false);

  const persistChatSessionStore = useCallback(
    (nextStore: ChatSessionStore) => {
      if (serverHistoryEnabled) {
        saveChatSessionStore(nextStore, maxChatSessions);
        return;
      }
      clearChatSessionStore();
    },
    [maxChatSessions, serverHistoryEnabled],
  );

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

  const chatContextCaseId = selectedCaseId ?? activeSession?.selectedCaseId;

  const capabilitiesReady =
    capabilitiesLoaded && !capabilitiesLoadError && capabilities !== null;

  const blockingLoadError = useMemo(() => {
    if (capabilitiesLoadError) {
      return capabilitiesLoadError;
    }
    if (capabilities?.chat_history_enabled && historyLoadError) {
      return historyLoadError;
    }
    return null;
  }, [
    capabilities?.chat_history_enabled,
    capabilitiesLoadError,
    historyLoadError,
  ]);

  const chatDisabledReason = useMemo(() => {
    if (!capabilitiesLoaded) {
      return "Checking portal capabilities…";
    }
    if (capabilitiesLoadError) {
      return capabilitiesLoadError;
    }
    if (capabilities && !capabilities.case_qa_enabled) {
      return "Case Q&A is disabled on this portal. Chat is unavailable.";
    }
    if (capabilities?.case_qa_enabled && !capabilities.chat_ready) {
      return resolveChatUnavailableReason(capabilities);
    }
    if (!chatContextCaseId) {
      return "Attach or open a case to chat.";
    }
    return undefined;
  }, [
    chatContextCaseId,
    capabilities,
    capabilitiesLoadError,
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

  const effectiveSelectedCaseId = chatContextCaseId;

  const resolvedCaseSummary = effectiveSelectedCaseId
    ? resolvedCaseById[effectiveSelectedCaseId]
    : undefined;

  const effectiveSelectedCaseName =
    effectiveSelectedCaseId === selectedCaseId
      ? selectedCaseName
      : attachedCasePreview &&
          attachedCasePreview.case_id === effectiveSelectedCaseId
        ? attachedCasePreview.search_name ?? undefined
        : resolvedCaseSummary?.search_name ?? undefined;

  const effectiveSelectedCaseProcessedAt =
    effectiveSelectedCaseId === selectedCaseId
      ? selectedCaseProcessedAt
      : attachedCasePreview &&
          attachedCasePreview.case_id === effectiveSelectedCaseId
        ? attachedCasePreview.processed_at ?? undefined
        : resolvedCaseSummary?.processed_at ?? undefined;

  const effectiveSelectedCaseLoading =
    effectiveSelectedCaseId === selectedCaseId
      ? selectedCaseLoading
      : resolvingCaseId === effectiveSelectedCaseId;

  const effectiveArchiveNotices = useMemo(() => {
    if (archiveNotices?.length) {
      return archiveNotices;
    }
    if (resolvedCaseSummary?.archive_notices?.length) {
      return resolvedCaseSummary.archive_notices;
    }
    if (attachedCasePreview?.archive_notices?.length) {
      return attachedCasePreview.archive_notices;
    }
    return [];
  }, [archiveNotices, attachedCasePreview?.archive_notices, resolvedCaseSummary?.archive_notices]);

  const initialPanelTurns = useMemo(
    () => storedTurnsToPanelTurns(activeSession?.turns ?? []),
    [activeSession?.turns],
  );

  const panelInstanceKey = [
    activeSession?.localId ?? "",
    "selected_case",
    effectiveSelectedCaseId ?? "none",
    loadingSessionId === activeSession?.localId ? "loading" : "ready",
  ].join(":");

  const normalizePersistedStore = useCallback(
    (current: ChatSessionStore): ChatSessionStore =>
      ensureChatSessionStore(
        applySessionCap(current, maxChatSessions, noteSessionEviction),
      ),
    [maxChatSessions, noteSessionEviction],
  );

  useEffect(() => {
    const normalized = normalizePersistedStore(store);
    if (
      normalized.activeLocalId !== store.activeLocalId ||
      normalized.sessions !== store.sessions
    ) {
      setStore(normalized);
      return;
    }
    persistChatSessionStore(store);
  }, [normalizePersistedStore, persistChatSessionStore, store]);

  useEffect(() => {
    if (!capabilitiesLoaded) {
      return;
    }
    if (!serverHistoryEnabled) {
      loadedPersistentStoreRef.current = false;
      clearChatSessionStore();
      return;
    }
    if (loadedPersistentStoreRef.current) {
      return;
    }
    loadedPersistentStoreRef.current = true;
    setStore(() => {
      const loaded = loadChatSessionStore(maxChatSessions);
      const contextualized = selectedCaseId
        ? switchToChatContext(loaded, selectedCaseId)
        : loaded;
      return ensureChatSessionStore(
        capChatSessionStore(contextualized, maxChatSessions),
      );
    });
  }, [
    capabilitiesLoaded,
    maxChatSessions,
    selectedCaseId,
    serverHistoryEnabled,
  ]);

  useEffect(() => {
    if (!capabilitiesLoaded) {
      return;
    }
    if (!serverHistoryEnabled) {
      setHistoryLoadError(null);
      return;
    }
    let cancelled = false;
    fetchChatSessions()
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setHistoryLoadError(null);
        if (!payload.history_enabled || !payload.items.length) {
          return;
        }
        setStore((current) => {
          const merged = applySessionCap(
            mergeServerSessions(current, payload.items),
            maxChatSessions,
            noteSessionEviction,
          );
          return merged;
        });
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setHistoryLoadError(
          `Could not load server chat sessions. ${formatWorkspaceError(err, "Unknown error")}. Showing local chats only.`,
        );
      });
    return () => {
      cancelled = true;
    };
  }, [
    capabilitiesLoaded,
    maxChatSessions,
    noteSessionEviction,
    serverHistoryEnabled,
  ]);

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

    const controller = new AbortController();
    const { signal } = controller;
    setResolvingCaseId(caseId);
    fetchCase(caseId, { signal })
      .then((detail) => {
        if (signal.aborted) {
          return;
        }
        const summary = caseDetailToSummary(detail);
        setResolvedCaseById((current) => ({
          ...current,
          [caseId]: summary,
        }));
      })
      .catch((err: unknown) => {
        if (isCancelledRequest(err, signal)) {
          return;
        }
        // Keep the case id visible when metadata cannot be loaded.
      })
      .finally(() => {
        if (!signal.aborted) {
          setResolvingCaseId((current) => (current === caseId ? null : current));
        }
      });

    return () => {
      controller.abort();
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
        switchToChatContext(current, selectedCaseId),
        maxChatSessions,
      );
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
          setCapabilitiesLoadError(null);
          onCapabilitiesLoaded?.(payload);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setCapabilities(null);
          setCapabilitiesLoadError(
            formatWorkspaceError(err, "Could not load portal capabilities."),
          );
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
  }, [onCapabilitiesLoaded]);

  const handleNewChat = useCallback(() => {
    const context = resolveNewChatContext(selectedCaseId);
    if (!context) {
      return;
    }

    setStore((current) => {
      const active = current.sessions.find(
        (item) => item.localId === current.activeLocalId,
      );
      if (active && isUnusedSession(active)) {
        if (
          sessionMatchesContext(
            active,
            context.mode,
            context.selectedCaseId,
          )
        ) {
          return current;
        }
        const next = switchToChatContext(current, context.selectedCaseId);
        const capped = ensureChatSessionStore(
          capChatSessionStore(next, maxChatSessions),
        );
        return capped;
      }

      const existingUnused = findUnusedSession(current.sessions);
      if (existingUnused) {
        const next = switchToChatContext(
          { ...current, activeLocalId: existingUnused.localId },
          context.selectedCaseId,
        );
        const capped = ensureChatSessionStore(
          capChatSessionStore(next, maxChatSessions),
        );
        return capped;
      }

      const session = createEmptySession(context.selectedCaseId);
      const next = {
        activeLocalId: session.localId,
        sessions: [session, ...current.sessions],
      };
      const capped = ensureChatSessionStore(
        capChatSessionStore(next, maxChatSessions),
      );
      return capped;
    });
  }, [maxChatSessions, selectedCaseId]);

  const handleSelectSession = useCallback(
    async (localId: string) => {
      setHistoryLoadError(null);

      // Resolve the target session from current state synchronously. Reading
      // values assigned inside a setStore updater is unreliable: React runs the
      // updater during render, so those reads are still null on the first click
      // and the history load would only fire on a later interaction.
      const session = store.sessions.find((item) => item.localId === localId);
      if (!session || session.localId === store.activeLocalId) {
        return;
      }
      const shouldLoadHistory = Boolean(
        session.serverSessionId && session.turns.length === 0,
      );

      setStore((current) => {
        if (!current.sessions.some((item) => item.localId === localId)) {
          return current;
        }
        const next = { ...current, activeLocalId: localId };
        const capped = capChatSessionStore(next, maxChatSessions);
        return capped;
      });

      sessionHistoryAbortRef.current?.abort();
      const abortController = new AbortController();
      sessionHistoryAbortRef.current = abortController;

      if (session.selectedCaseId) {
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
          return capped;
        });

        if (abortController.signal.aborted) {
          return;
        }

        if (payload.selected_case_id) {
          onAttachCase?.(payload.selected_case_id);
        } else {
          onClearSelectedCase?.();
        }
      } catch (err: unknown) {
        if (abortController.signal.aborted) {
          return;
        }
        setHistoryLoadError(
          `Could not load chat history. ${formatWorkspaceError(err, "Unknown error", { chatContext: true })}`,
        );
      } finally {
        setLoadingSessionId((current) => (current === localId ? null : current));
      }
    },
    [maxChatSessions, onAttachCase, onClearSelectedCase, store],
  );

  const handleAttachCase = useCallback(
    (caseSummary: CaseSummary) => {
      setAttachedCasePreview(caseSummary);
      setStore((current) => {
        const next = capChatSessionStore(
          switchToChatContext(current, caseSummary.case_id),
          maxChatSessions,
        );
        return next;
      });
      onAttachCase?.(caseSummary.case_id);
    },
    [maxChatSessions, onAttachCase],
  );

  const handleClearSelectedCase = useCallback(() => {
    setAttachedCasePreview(null);
    flushSync(() => {
      setStore((current) =>
        capChatSessionStore(detachActiveCase(current), maxChatSessions),
      );
    });
    onClearSelectedCase?.();
  }, [maxChatSessions, onClearSelectedCase]);

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
          const context = resolveNewChatContext(selectedCaseId);
          const replacement = createEmptySession(context?.selectedCaseId);
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
        return capped;
      });
      setPendingDeleteSession(null);
    } catch (err: unknown) {
      const message = formatWorkspaceError(err, "Unknown error");
      setDeleteError(message);
    } finally {
      setDeleteBusy(false);
    }
  }, [deleteBusy, maxChatSessions, pendingDeleteSession, selectedCaseId]);

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
            return capped;
          }
        }

        const firstQuestion = storedTurns[0]?.question ?? "";
        const title = isEmpty
          ? "New chat"
          : active.title === "New chat" && firstQuestion
            ? sessionTitleFromQuestion(firstQuestion)
            : active.title;
        const selectedCaseForPanel =
          state.mode === "selected_case" ? effectiveSelectedCaseId : undefined;
        const serverSessionId = resolveSyncedServerSessionId(
          active,
          state.mode,
          state.sessionId,
          selectedCaseForPanel,
        );
        const next: ChatSessionStore = {
          ...current,
          sessions: current.sessions.map((session) =>
            session.localId === active.localId
              ? {
                  ...session,
                  title,
                  updatedAt: new Date().toISOString(),
                  mode: state.mode,
                  selectedCaseId: selectedCaseForPanel,
                  serverSessionId,
                  turns: storedTurns,
                }
              : session,
          ),
        };
        const capped = capChatSessionStore(next, maxChatSessions);
        return capped;
      });
    },
    [effectiveSelectedCaseId, maxChatSessions],
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

  const mainContent = !capabilitiesLoaded ? (
    <PortalWorkspaceSkeleton />
  ) : blockingLoadError ? (
    <PortalLoadFailure message={blockingLoadError} />
  ) : (
      <>
        <PortalCapabilityBanner
          capabilities={capabilities}
          capabilitiesLoaded={capabilitiesLoaded}
          capabilitiesLoadError={capabilitiesLoadError}
          attachError={attachError}
          historyLoadError={
            capabilities?.chat_history_enabled ? historyLoadError : null
          }
          sessionCapNotice={sessionCapNotice}
          chatDisabledReason={chatDisabledReason}
        />
        {effectiveSelectedCaseId && effectiveArchiveNotices.length ? (
          <CaseArchiveNoticeBanner
            notices={effectiveArchiveNotices}
            title="Attached case notice"
          />
        ) : null}
        <ChatPanel
          key={panelInstanceKey}
          initialSessionId={activeSession.serverSessionId}
          initialTurns={initialPanelTurns}
          loadingHistory={loadingSessionId === activeSession.localId}
          maxQuestionChars={capabilities?.max_question_chars}
          mode="selected_case"
          selectedCaseId={effectiveSelectedCaseId}
          disabledReason={chatDisabledReason}
          composerDisabled={
            !capabilitiesLoaded ||
            Boolean(capabilitiesLoadError) ||
            Boolean(chatDisabledReason)
          }
          serverSyncError={orphanCleanupError}
          onStateChange={handlePanelStateChange}
          onChatCancelled={handleChatCancelled}
          onOrphanedChatResponse={handleOrphanedChatResponse}
        />
      </>
    );

  return (
    <div className="flex h-full min-h-0 w-full">
      <PortalSidebar
        activeLocalId={store.activeLocalId}
        assistantControls={
          <ChatAssistantControls
            selectedCaseId={effectiveSelectedCaseId}
            selectedCaseLoading={effectiveSelectedCaseLoading}
            selectedCaseName={effectiveSelectedCaseName}
            selectedCaseProcessedAt={effectiveSelectedCaseProcessedAt}
            caseAttachEnabled={
              !blockingLoadError &&
              capabilitiesReady &&
              capabilities.case_qa_enabled
            }
            onAttachCase={handleAttachCase}
            onClearSelectedCase={handleClearSelectedCase}
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
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">{mainContent}</div>
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
