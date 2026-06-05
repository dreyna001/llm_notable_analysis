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

const STORAGE_KEY = "portal-chat-sessions-v1";

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

export function isUnusedSession(session: StoredChatSession): boolean {
  return session.turns.length === 0;
}

export function findUnusedSession(
  sessions: StoredChatSession[],
): StoredChatSession | undefined {
  return sessions.find(isUnusedSession);
}

export function loadChatSessionStore(): ChatSessionStore {
  if (typeof window === "undefined") {
    const session = createEmptySession();
    return { activeLocalId: session.localId, sessions: [session] };
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      const session = createEmptySession();
      return { activeLocalId: session.localId, sessions: [session] };
    }
    const parsed = JSON.parse(raw) as ChatSessionStore;
    if (!parsed?.sessions?.length || !parsed.activeLocalId) {
      const session = createEmptySession();
      return { activeLocalId: session.localId, sessions: [session] };
    }
    return parsed;
  } catch {
    const session = createEmptySession();
    return { activeLocalId: session.localId, sessions: [session] };
  }
}

export function saveChatSessionStore(store: ChatSessionStore): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}
