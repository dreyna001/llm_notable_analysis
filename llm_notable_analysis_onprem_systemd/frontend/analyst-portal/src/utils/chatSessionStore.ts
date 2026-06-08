import type { ChatMode } from "../types";

export type StoredChatTurn = {
  id: string;
  question: string;
  response?: {
    answer: string;
    answer_status: string;
  };
};

export type StoredChatSession = {
  localId: string;
  serverSessionId: string | null;
  title: string;
  updatedAt: string;
  mode: ChatMode;
  selectedCaseId?: string;
  turns: StoredChatTurn[];
};

export type ChatSessionStore = {
  activeLocalId: string;
  sessions: StoredChatSession[];
};

export type CappedChatSessionStore = {
  store: ChatSessionStore;
  evictedCount: number;
};

const STORAGE_KEY = "portal-chat-sessions-v1";

export const DEFAULT_MAX_CHAT_SESSIONS = 10;

function newLocalId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function sessionTitleFromQuestion(question: string, fallback = "New chat"): string {
  const trimmed = question.trim();
  if (!trimmed) {
    return fallback;
  }
  if (trimmed.length <= 48) {
    return trimmed;
  }
  return `${trimmed.slice(0, 47).trim()}…`;
}

export function createEmptySession(
  mode: ChatMode = "global_archive",
  selectedCaseId?: string,
): StoredChatSession {
  const now = new Date().toISOString();
  return {
    localId: newLocalId(),
    serverSessionId: null,
    title: "New chat",
    updatedAt: now,
    mode,
    selectedCaseId,
    turns: [],
  };
}

function isChatMode(value: unknown): value is ChatMode {
  return value === "selected_case" || value === "global_archive";
}

function isStoredTurn(value: unknown): value is StoredChatTurn {
  if (!value || typeof value !== "object") {
    return false;
  }
  const turn = value as Partial<StoredChatTurn>;
  if (typeof turn.id !== "string" || typeof turn.question !== "string") {
    return false;
  }
  if (turn.response == null) {
    return true;
  }
  return (
    typeof turn.response === "object" &&
    typeof turn.response.answer === "string" &&
    typeof turn.response.answer_status === "string"
  );
}

function normalizeSession(value: unknown): StoredChatSession | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const session = value as Partial<StoredChatSession>;
  if (
    typeof session.localId !== "string" ||
    typeof session.title !== "string" ||
    typeof session.updatedAt !== "string" ||
    !isChatMode(session.mode) ||
    !Array.isArray(session.turns)
  ) {
    return null;
  }
  const turns = session.turns.filter(isStoredTurn);
  return {
    localId: session.localId,
    serverSessionId:
      typeof session.serverSessionId === "string" ? session.serverSessionId : null,
    title: session.title || "New chat",
    updatedAt: session.updatedAt,
    mode: session.mode,
    selectedCaseId:
      typeof session.selectedCaseId === "string" ? session.selectedCaseId : undefined,
    turns,
  };
}

function emptyStore(): ChatSessionStore {
  const session = createEmptySession();
  return { activeLocalId: session.localId, sessions: [session] };
}

/** Guarantee at least one session and a valid activeLocalId for UI rendering. */
export function ensureChatSessionStore(store: ChatSessionStore): ChatSessionStore {
  if (!store.sessions.length) {
    return emptyStore();
  }
  const activeExists = store.sessions.some(
    (session) => session.localId === store.activeLocalId,
  );
  if (activeExists) {
    return store;
  }
  return {
    activeLocalId: store.sessions[0].localId,
    sessions: store.sessions,
  };
}

export function capChatSessionStore(
  store: ChatSessionStore,
  maxSessions: number = DEFAULT_MAX_CHAT_SESSIONS,
): ChatSessionStore {
  return capChatSessionStoreWithMeta(store, maxSessions).store;
}

export function capChatSessionStoreWithMeta(
  store: ChatSessionStore,
  maxSessions: number = DEFAULT_MAX_CHAT_SESSIONS,
): CappedChatSessionStore {
  const limit = Math.max(1, maxSessions);
  if (store.sessions.length <= limit) {
    return { store: ensureChatSessionStore(store), evictedCount: 0 };
  }

  const activeId = store.activeLocalId;
  const byRecency = [...store.sessions].sort((left, right) =>
    right.updatedAt.localeCompare(left.updatedAt),
  );
  const kept = byRecency.slice(0, limit);
  if (!kept.some((session) => session.localId === activeId)) {
    const active = store.sessions.find((session) => session.localId === activeId);
    if (active) {
      kept[limit - 1] = active;
    }
  }

  const keptIds = new Set(kept.map((session) => session.localId));
  const evictedCount = store.sessions.filter(
    (session) => !keptIds.has(session.localId),
  ).length;

  const activeLocalId = kept.some((session) => session.localId === activeId)
    ? activeId
    : (kept[0]?.localId ?? activeId);
  return {
    store: ensureChatSessionStore({ activeLocalId, sessions: kept }),
    evictedCount,
  };
}

function normalizeStore(
  value: unknown,
  maxSessions: number = DEFAULT_MAX_CHAT_SESSIONS,
): ChatSessionStore {
  if (!value || typeof value !== "object") {
    return emptyStore();
  }
  const store = value as Partial<ChatSessionStore>;
  if (!Array.isArray(store.sessions) || typeof store.activeLocalId !== "string") {
    return emptyStore();
  }
  const sessions = store.sessions
    .map(normalizeSession)
    .filter((session): session is StoredChatSession => session !== null);
  if (!sessions.length) {
    return emptyStore();
  }
  return capChatSessionStore(
    {
      activeLocalId: store.activeLocalId,
      sessions,
    },
    maxSessions,
  );
}

export function isUnusedSession(session: StoredChatSession): boolean {
  return session.turns.length === 0;
}

export function findUnusedSession(
  sessions: StoredChatSession[],
): StoredChatSession | undefined {
  return sessions.find(isUnusedSession);
}

export function resolveNewChatContext(
  availableModes: ChatMode[],
  capabilitiesReady: boolean,
  selectedCaseId?: string,
): { mode: ChatMode; selectedCaseId?: string } | null {
  if (selectedCaseId && availableModes.includes("selected_case")) {
    return { mode: "selected_case", selectedCaseId };
  }
  if (availableModes.includes("global_archive")) {
    return { mode: "global_archive" };
  }
  if (!capabilitiesReady) {
    return null;
  }
  return { mode: "selected_case" };
}

export function sessionMatchesContext(
  session: StoredChatSession,
  mode: ChatMode,
  selectedCaseId?: string,
): boolean {
  if (session.mode !== mode) {
    return false;
  }
  if (mode === "selected_case") {
    return session.selectedCaseId === selectedCaseId;
  }
  return session.selectedCaseId == null;
}

/** Keep the server session link only when panel context still matches the stored session. */
export function resolveSyncedServerSessionId(
  session: StoredChatSession,
  panelMode: ChatMode,
  panelSessionId: string | null,
  selectedCaseId?: string,
): string | null {
  const contextCaseId = panelMode === "selected_case" ? selectedCaseId : undefined;
  if (!sessionMatchesContext(session, panelMode, contextCaseId)) {
    return null;
  }
  return panelSessionId ?? session.serverSessionId;
}

function applyContextToSession(
  session: StoredChatSession,
  mode: ChatMode,
  selectedCaseId?: string,
): StoredChatSession {
  return {
    ...session,
    mode,
    selectedCaseId: mode === "selected_case" ? selectedCaseId : undefined,
    updatedAt: new Date().toISOString(),
  };
}

/** Drop the attached case from the active chat and clear case-specific history. */
export function detachActiveCase(store: ChatSessionStore): ChatSessionStore {
  const active =
    store.sessions.find((session) => session.localId === store.activeLocalId) ??
    store.sessions[0];
  if (!active?.selectedCaseId && active?.mode === "global_archive") {
    return store;
  }
  if (!active) {
    return store;
  }
  return {
    ...store,
    sessions: store.sessions.map((session) =>
      session.localId === active.localId
        ? {
            ...session,
            mode: "global_archive",
            selectedCaseId: undefined,
            serverSessionId: null,
            turns: [],
            updatedAt: new Date().toISOString(),
          }
        : session,
    ),
  };
}

/** Keep the active chat when context changes; start a fresh session if it already has turns. */
export function switchToChatContext(
  store: ChatSessionStore,
  mode: ChatMode,
  selectedCaseId?: string,
): ChatSessionStore {
  const active =
    store.sessions.find((session) => session.localId === store.activeLocalId) ??
    store.sessions[0];
  if (!active) {
    const session = createEmptySession(mode, selectedCaseId);
    return { activeLocalId: session.localId, sessions: [session] };
  }

  if (sessionMatchesContext(active, mode, selectedCaseId)) {
    return store;
  }

  if (isUnusedSession(active)) {
    return {
      ...store,
      sessions: store.sessions.map((session) =>
        session.localId === active.localId
          ? {
              ...applyContextToSession(session, mode, selectedCaseId),
              serverSessionId: null,
            }
          : session,
      ),
    };
  }

  const reusable = findUnusedSession(
    store.sessions.filter((session) => session.localId !== active.localId),
  );
  if (reusable) {
    return {
      ...store,
      activeLocalId: reusable.localId,
      sessions: store.sessions.map((session) =>
        session.localId === reusable.localId
          ? {
              ...applyContextToSession(session, mode, selectedCaseId),
              serverSessionId: null,
            }
          : session,
      ),
    };
  }

  const session = createEmptySession(mode, selectedCaseId);
  return {
    activeLocalId: session.localId,
    sessions: [session, ...store.sessions],
  };
}

export function loadChatSessionStore(
  maxSessions: number = DEFAULT_MAX_CHAT_SESSIONS,
): ChatSessionStore {
  if (typeof window === "undefined") {
    return emptyStore();
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return emptyStore();
    }
    return normalizeStore(JSON.parse(raw), maxSessions);
  } catch {
    return emptyStore();
  }
}

export function saveChatSessionStore(
  store: ChatSessionStore,
  maxSessions: number = DEFAULT_MAX_CHAT_SESSIONS,
): void {
  if (typeof window === "undefined") {
    return;
  }
  const normalized = normalizeStore(store, maxSessions);
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // Storage can be unavailable or full; chat still works without local persistence.
  }
}

export function clearChatSessionStore(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable; clearing is best-effort.
  }
}
