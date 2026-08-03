import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  fetchCapabilities,
  fetchCase,
  fetchChatSessionMessages,
  fetchChatSessions,
} from "../api/client";
import type { PortalCapabilities } from "../types";
import { VERDICT_COLOR } from "../utils/verdict";

import { HomeChatWorkspace } from "./HomeChatWorkspace";

const STORAGE_KEY = "portal-chat-sessions-v1";

const capabilities: PortalCapabilities = {
  case_qa_enabled: true,
  chat_history_enabled: false,
  general_knowledge_enabled: true,
  max_question_chars: 2000,
  max_answer_tokens: 800,
  model_context_tokens: 128000,
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
  vi.mocked(fetchCase).mockResolvedValue({
    case_id: "portal-test-1780770539",
    metadata: {
      processed_at: "2026-01-01T00:00:00.000Z",
      retrieval_status: "ready",
      source_completeness: "complete",
    },
    alert_payload: { search_name: "Portal E2E Test" },
    analysis: {},
  });
}

describe("HomeChatWorkspace attached case", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    resetApiMocks();
  });

  it("shows an attached case from workspace props", async () => {
    render(
      <MemoryRouter>
        <HomeChatWorkspace
          sidebarMeta={<div>Case window</div>}
          selectedCaseId="portal-test-1780770539"
          selectedCaseName="Portal E2E Test"
          selectedCaseVerdict="likely_malicious"
        />
      </MemoryRouter>,
    );

    const caseName = await screen.findByText("Portal E2E Test");
    expect(caseName).toBeInTheDocument();
    expect(caseName).toHaveStyle({ color: VERDICT_COLOR.malicious });
    expect(screen.getByText("Case attached")).toBeInTheDocument();
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

  it("does not create a chat session without an attached case", async () => {
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
            mode: "selected_case",
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
        "Attach or open a case to chat.",
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
      chat_dependency_status: {
        embeddings: "ready",
        archive_retrieval: "ready",
        llm_gateway: "unavailable",
      },
    });

    render(
      <MemoryRouter>
        <HomeChatWorkspace sidebarMeta={<div>Case window</div>} />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText("Case chat is unavailable: LLM gateway is down."),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Case ID or alert name"),
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

  it("loads server chat history on the first click of a saved session", async () => {
    vi.mocked(fetchCapabilities).mockResolvedValue({
      ...capabilities,
      chat_history_enabled: true,
    });
    vi.mocked(fetchChatSessions).mockResolvedValue({
      history_enabled: true,
      items: [
        {
          session_id: "srv-1",
          title: "Saved chat",
          updated_at: "2026-01-01T00:00:00.000Z",
          mode: "selected_case",
          selected_case_id: "portal-test-1780770539",
        },
      ],
    });
    vi.mocked(fetchChatSessionMessages).mockResolvedValue({
      session_id: "srv-1",
      mode: "selected_case",
      selected_case_id: "portal-test-1780770539",
      messages: [
        {
          role: "user",
          content: "What happened earlier?",
          created_at: "2026-01-01T00:00:00.000Z",
        },
        {
          role: "assistant",
          content: "Here is the prior summary.",
          created_at: "2026-01-01T00:00:01.000Z",
          answer_status: "answered",
        },
      ],
    });

    render(
      <MemoryRouter>
        <HomeChatWorkspace
          sidebarMeta={<div>Case window</div>}
          selectedCaseId="portal-test-1780770539"
          selectedCaseName="Portal E2E Test"
        />
      </MemoryRouter>,
    );

    const savedChat = await screen.findByRole("button", { name: "Saved chat" });

    fireEvent.click(savedChat);

    await waitFor(() => {
      expect(fetchChatSessionMessages).toHaveBeenCalledTimes(1);
    });
    expect(fetchChatSessionMessages).toHaveBeenCalledWith(
      "srv-1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(
      await screen.findByText("What happened earlier?"),
    ).toBeInTheDocument();
  });
});
