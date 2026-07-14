import { describe, expect, it } from "vitest";
import {
  capChatSessionStoreWithMeta,
  createEmptySession,
  detachActiveCase,
  resolveNewChatContext,
  resolveSyncedServerSessionId,
  switchToChatContext,
  loadChatSessionStore,
  saveChatSessionStore,
  clearChatSessionStore,
  type ChatSessionStore,
} from "./chatSessionStore";

function makeStore(count: number): ChatSessionStore {
  const sessions = Array.from({ length: count }, (_, index) => {
    const session = createEmptySession();
    return {
      ...session,
      localId: `session-${index}`,
      updatedAt: new Date(Date.UTC(2026, 0, 1, index)).toISOString(),
    };
  });
  return { activeLocalId: sessions[0].localId, sessions };
}

describe("resolveNewChatContext", () => {
  it("returns null when no case is attached", () => {
    expect(resolveNewChatContext(undefined)).toBeNull();
  });

  it("returns selected-case context when a case is attached", () => {
    expect(resolveNewChatContext("case-123")).toEqual({
      mode: "selected_case",
      selectedCaseId: "case-123",
    });
  });
});

describe("detachActiveCase", () => {
  it("clears the attached case, server linkage, and prior turns from the active session", () => {
    const active = createEmptySession("portal-test-123");
    active.serverSessionId = "server-session-1";
    active.turns = [
      {
        id: "turn-1",
        question: "What is the verdict?",
        response: { answer: "Likely benign.", answer_status: "answered" },
      },
    ];
    const other = createEmptySession("other-case");
    const store: ChatSessionStore = {
      activeLocalId: active.localId,
      sessions: [active, other],
    };

    const next = detachActiveCase(store);
    const updated = next.sessions.find((session) => session.localId === active.localId);

    expect(updated?.mode).toBe("selected_case");
    expect(updated?.selectedCaseId).toBeUndefined();
    expect(updated?.serverSessionId).toBeNull();
    expect(updated?.turns).toHaveLength(0);
    expect(next.sessions.find((session) => session.localId === other.localId)?.selectedCaseId).toBe(
      "other-case",
    );
  });
});

describe("resolveSyncedServerSessionId", () => {
  it("drops the server session link when panel mode no longer matches", () => {
    const session = createEmptySession("case-a");
    session.serverSessionId = "server-1";

    expect(
      resolveSyncedServerSessionId(session, "selected_case", "server-1", "case-b"),
    ).toBeNull();
  });

  it("drops the server session link when the attached case changes", () => {
    const session = createEmptySession("case-a");
    session.serverSessionId = "server-1";

    expect(
      resolveSyncedServerSessionId(
        session,
        "selected_case",
        "server-1",
        "case-b",
      ),
    ).toBeNull();
  });

  it("keeps the server session link when panel context still matches", () => {
    const session = createEmptySession("case-a");
    session.serverSessionId = "server-1";

    expect(
      resolveSyncedServerSessionId(
        session,
        "selected_case",
        "server-1",
        "case-a",
      ),
    ).toBe("server-1");
  });
});

describe("switchToChatContext", () => {
  it("clears server linkage when an unused session changes context", () => {
    const active = createEmptySession("case-a");
    active.serverSessionId = "server-1";
    const store: ChatSessionStore = {
      activeLocalId: active.localId,
      sessions: [active],
    };

    const next = switchToChatContext(store, "case-b");
    const updated = next.sessions.find((session) => session.localId === active.localId);

    expect(updated?.mode).toBe("selected_case");
    expect(updated?.serverSessionId).toBeNull();
  });
});

describe("chatSessionStore cap", () => {
  it("reports evicted sessions when over the limit", () => {
    const { store, evictedCount } = capChatSessionStoreWithMeta(makeStore(4), 2);
    expect(evictedCount).toBe(2);
    expect(store.sessions).toHaveLength(2);
  });

  it("keeps the active session even when it would be trimmed", () => {
    const base = makeStore(4);
    const activeId = base.sessions[3].localId;
    const storeWithActiveOldest = {
      activeLocalId: activeId,
      sessions: base.sessions,
    };
    const { store, evictedCount } = capChatSessionStoreWithMeta(
      storeWithActiveOldest,
      2,
    );
    expect(evictedCount).toBe(2);
    expect(store.activeLocalId).toBe(activeId);
    expect(store.sessions.some((session) => session.localId === activeId)).toBe(
      true,
    );
  });
});

describe("chat session browser retention", () => {
  it("stores chat contents only for the current browser session", () => {
    const store = makeStore(1);
    store.sessions[0].turns = [{
      id: "turn-1",
      question: "confidential question",
      response: { answer: "confidential answer", answer_status: "answered" },
    }];

    saveChatSessionStore(store);

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.getItem("portal-chat-sessions-v1")).toContain(
      "confidential question",
    );
    expect(loadChatSessionStore().sessions[0].turns[0].response?.answer).toBe(
      "confidential answer",
    );
    clearChatSessionStore();
    expect(window.sessionStorage.getItem("portal-chat-sessions-v1")).toBeNull();
  });

  it("deletes legacy persistent chat data", () => {
    window.localStorage.setItem("portal-chat-sessions-v1", "legacy-secret");
    loadChatSessionStore();
    expect(window.localStorage.getItem("portal-chat-sessions-v1")).toBeNull();
  });
});
