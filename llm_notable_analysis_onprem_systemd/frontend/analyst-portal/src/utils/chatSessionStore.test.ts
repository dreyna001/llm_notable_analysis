import { describe, expect, it } from "vitest";
import {
  capChatSessionStoreWithMeta,
  createEmptySession,
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
