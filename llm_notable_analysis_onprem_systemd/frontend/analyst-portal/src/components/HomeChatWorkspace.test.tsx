import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
  fetchChatSessionMessages: vi.fn(),
  fetchChatSessions: vi.fn(async () => ({ history_enabled: false, items: [] })),
}));

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
      mode: "global_archive",
      serverSessionId: null,
    });
    expect(stored.sessions[0]).not.toHaveProperty("selectedCaseId");
  });
});
