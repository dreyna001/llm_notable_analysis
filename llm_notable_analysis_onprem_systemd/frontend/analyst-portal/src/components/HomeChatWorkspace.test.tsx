import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchCapabilities, fetchChatSessions } from "../api/client";
import type { PortalCapabilities } from "../types";
import { HomeChatWorkspace } from "./HomeChatWorkspace";

const STORAGE_KEY = "portal-chat-sessions-v1";

const capabilities: PortalCapabilities = {
  case_qa_enabled: true,
  global_retrieval_enabled: false,
  chat_history_enabled: false,
  general_knowledge_enabled: true,
  max_question_chars: 2000,
  max_answer_tokens: 800,
  chat_ready: true,
};

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  deleteChatSession: vi.fn(),
  deleteLastChatTurn: vi.fn(),
  fetchCapabilities: vi.fn(async () => capabilities),
  fetchCase: vi.fn(),
  fetchCases: vi.fn(async () => ({ items: [], total: 0 })),
  fetchChatSessionMessages: vi.fn(),
  fetchChatSessions: vi.fn(async () => ({ history_enabled: false, items: [] })),
}));

afterEach(() => {
  cleanup();
});

function resetApiMocks() {
  vi.mocked(fetchCapabilities).mockResolvedValue(capabilities);
  vi.mocked(fetchChatSessions).mockResolvedValue({
    history_enabled: false,
    items: [],
  });
}

function seedSelectedCaseSession() {
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      activeLocalId: "local-selected",
      sessions: [
        {
          localId: "local-selected",
          serverSessionId: "server-selected",
          title: "Portal E2E Test",
          updatedAt: "2026-01-01T00:00:00.000Z",
          mode: "selected_case",
          selectedCaseId: "portal-test-1780770539",
          turns: [],
        },
      ],
    }),
  );
}

function ClearableWorkspace() {
  const [caseId, setCaseId] = useState<string | undefined>(
    "portal-test-1780770539",
  );
  return (
    <MemoryRouter>
      <HomeChatWorkspace
        sidebarMeta={<div>Case window</div>}
        selectedCaseId={caseId}
        selectedCaseName={caseId ? "Portal E2E Test" : undefined}
        onAttachCase={(nextCaseId) => setCaseId(nextCaseId)}
        onClearSelectedCase={() => setCaseId(undefined)}
      />
    </MemoryRouter>
  );
}

describe("HomeChatWorkspace attached case", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    resetApiMocks();
    vi.mocked(fetchCapabilities).mockResolvedValue({
      ...capabilities,
      chat_history_enabled: true,
    });
  });

  it("removes a stale selected-case session from the active view when the URL case is cleared", async () => {
    seedSelectedCaseSession();

    render(<ClearableWorkspace />);

    expect(await screen.findByText("Portal E2E Test")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /clear attached case/i }),
    );

    await waitFor(() => {
      expect(screen.queryByText("Case attached")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Portal E2E Test")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Select a case to chat. Cross-case archive chat is disabled for this portal.",
      ),
    ).toBeInTheDocument();

    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(stored.sessions[0]).toMatchObject({
      mode: "selected_case",
      serverSessionId: null,
    });
    expect(stored.sessions[0]).not.toHaveProperty("selectedCaseId");
  });
});

describe("HomeChatWorkspace new chat", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    resetApiMocks();
    vi.mocked(fetchCapabilities).mockResolvedValue({
      ...capabilities,
      chat_history_enabled: true,
    });
  });

  it("does not create a global-mode session when cross-case chat is disabled", async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        activeLocalId: "local-old",
        sessions: [
          {
            localId: "local-old",
            serverSessionId: null,
            title: "Old chat",
            updatedAt: "2026-01-01T00:00:00.000Z",
            mode: "global_archive",
            turns: [
              {
                id: "turn-1",
                question: "What happened?",
                response: {
                  answer: "Unknown.",
                  answer_status: "answered",
                },
              },
            ],
          },
        ],
      }),
    );

    render(
      <MemoryRouter>
        <HomeChatWorkspace sidebarMeta={<div>Case window</div>} />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(
        "Select a case to chat. Cross-case archive chat is disabled for this portal.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("All cases + knowledge base")).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: /^new chat$/i })[0]);

    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    const active = stored.sessions.find(
      (session: { localId: string }) => session.localId === stored.activeLocalId,
    );
    expect(active?.mode).toBe("selected_case");
    expect(active).not.toHaveProperty("selectedCaseId");
  });
});

describe("HomeChatWorkspace startup failures", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    resetApiMocks();
  });

  it("blocks chat when portal capabilities cannot be loaded", async () => {
    vi.mocked(fetchCapabilities).mockRejectedValue(
      new ApiError(503, "Portal API unavailable."),
    );

    render(
      <MemoryRouter>
        <HomeChatWorkspace sidebarMeta={<div>Case window</div>} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Portal chat unavailable")).toBeInTheDocument();
    expect(screen.getByText("503: Portal API unavailable.")).toBeInTheDocument();
    expect(screen.queryByText("How can I help?")).not.toBeInTheDocument();
  });

  it("blocks chat when case chat dependencies are not ready", async () => {
    vi.mocked(fetchCapabilities).mockResolvedValue({
      ...capabilities,
      chat_ready: false,
      chat_degraded_reason:
        "Case chat is temporarily unavailable. Embeddings, archive retrieval, or the LLM may be down.",
    });

    render(
      <MemoryRouter>
        <HomeChatWorkspace sidebarMeta={<div>Case window</div>} />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(
        "Case chat is temporarily unavailable. Embeddings, archive retrieval, or the LLM may be down.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/ask/i)).not.toBeInTheDocument();
  });

  it("blocks chat when server sessions cannot be loaded and history is enabled", async () => {
    vi.mocked(fetchCapabilities).mockResolvedValue({
      ...capabilities,
      chat_history_enabled: true,
    });
    vi.mocked(fetchChatSessions).mockRejectedValue(
      new ApiError(503, "unavailable"),
    );

    render(
      <MemoryRouter>
        <HomeChatWorkspace sidebarMeta={<div>Case window</div>} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Portal chat unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Could not load server chat sessions. 503: unavailable. Showing local chats only.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("How can I help?")).not.toBeInTheDocument();
  });
});

describe("HomeChatWorkspace server chat sessions", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    resetApiMocks();
  });

  it("clears durable browser storage when server chat history is disabled", async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        activeLocalId: "local-old",
        sessions: [
          {
            localId: "local-old",
            serverSessionId: null,
            title: "Stale chat",
            updatedAt: "2026-01-01T00:00:00.000Z",
            mode: "selected_case",
            selectedCaseId: "portal-test-1780770539",
            turns: [
              {
                id: "turn-1",
                question: "What happened?",
                response: {
                  answer: "Sensitive case detail.",
                  answer_status: "answered",
                },
              },
            ],
          },
        ],
      }),
    );

    render(
      <MemoryRouter>
        <HomeChatWorkspace
          sidebarMeta={<div>Case window</div>}
          selectedCaseId="portal-test-1780770539"
          selectedCaseName="Portal E2E Test"
        />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText("Start investigating this case"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Stale chat")).not.toBeInTheDocument();
    expect(screen.queryByText("What happened?")).not.toBeInTheDocument();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();

    fireEvent.click(screen.getAllByRole("button", { name: /^new chat$/i })[0]);

    await waitFor(() => {
      expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });

  it("shows a banner when the initial server session list cannot be loaded", async () => {
    vi.mocked(fetchCapabilities).mockResolvedValue({
      ...capabilities,
      chat_history_enabled: true,
    });
    vi.mocked(fetchChatSessions).mockRejectedValueOnce(
      new ApiError(503, "unavailable"),
    );

    render(
      <MemoryRouter>
        <HomeChatWorkspace
          sidebarMeta={<div>Case window</div>}
          selectedCaseId="portal-test-1780770539"
          selectedCaseName="Portal E2E Test"
        />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(
        "Could not load server chat sessions. 503: unavailable. Showing local chats only.",
      ),
    ).toBeInTheDocument();
  });
});
