import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { ChatPanel } from "./ChatPanel";

const postChat = vi.fn();

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    postChat: (...args: unknown[]) => postChat(...args),
  };
});

afterEach(() => {
  cleanup();
});

describe("ChatPanel session scope recovery", () => {
  beforeEach(() => {
    postChat.mockReset();
  });

  it("clears stale server session ids and retries as a new session", async () => {
    postChat
      .mockRejectedValueOnce(
        new ApiError(400, "session_id scope does not match the chat request."),
      )
      .mockResolvedValueOnce({
        answer: "Recovered.",
        answer_status: "answered",
        session_id: "fresh-session",
      });

    render(
      <ChatPanel
        mode="global_archive"
        initialSessionId="stale-server-id"
      />,
    );

    const composer = screen.getByRole("textbox");

    fireEvent.change(composer, {
      target: { value: "What happened?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Recovered.")).toBeInTheDocument();
    expect(
      screen.queryByText(/This server chat session is no longer available/),
    ).not.toBeInTheDocument();

    expect(postChat.mock.calls[0]?.[0]).toMatchObject({
      session_id: "stale-server-id",
    });
    expect(postChat.mock.calls[1]?.[0]).toMatchObject({
      session_id: null,
    });
  });

  it("retries after an expired server session response", async () => {
    postChat
      .mockRejectedValueOnce(
        new ApiError(410, "session_id has expired."),
      )
      .mockResolvedValueOnce({
        answer: "Fresh session answer.",
        answer_status: "answered",
        session_id: "fresh-session",
      });

    render(
      <ChatPanel
        mode="global_archive"
        initialSessionId="expired-server-id"
      />,
    );

    const composer = screen.getByRole("textbox");
    fireEvent.change(composer, {
      target: { value: "Try again" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Fresh session answer.")).toBeInTheDocument();
    expect(postChat.mock.calls[1]?.[0]).toMatchObject({
      session_id: null,
    });
  });
});

describe("ChatPanel session instance key", () => {
  it("remounts when the parent changes its React key", () => {
    const firstTurn = {
      id: "turn-1",
      question: "First question",
      response: {
        answer: "First answer",
        answer_status: "answered",
      },
      awaitingResponse: false,
    };

    const { rerender } = render(
      <ChatPanel
        key="session-a:global_archive:none:ready"
        mode="global_archive"
        initialTurns={[firstTurn]}
      />,
    );

    expect(screen.getByText("First question")).toBeInTheDocument();

    rerender(
      <ChatPanel
        key="session-b:global_archive:none:ready"
        mode="global_archive"
        initialTurns={[]}
      />,
    );

    expect(screen.queryByText("First question")).not.toBeInTheDocument();
    expect(screen.getByText("How can I help?")).toBeInTheDocument();
  });
});

describe("ChatPanel error guidance", () => {
  beforeEach(() => {
    postChat.mockReset();
  });

  it("shows recovery guidance for chat timeouts", async () => {
    postChat.mockRejectedValueOnce(
      new ApiError(0, "Request timed out.", "timeout"),
    );

    render(<ChatPanel mode="global_archive" />);

    const composer = screen.getByRole("textbox");
    fireEvent.change(composer, {
      target: { value: "What happened?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(
      await screen.findByText(/The chat request timed out/i),
    ).toBeInTheDocument();
  });

  it("shows stale-session guidance when retry also fails", async () => {
    postChat
      .mockRejectedValueOnce(new ApiError(404, "session_id was not found."))
      .mockRejectedValueOnce(new ApiError(503, "LLM service unavailable."));

    render(
      <ChatPanel
        mode="global_archive"
        initialSessionId="missing-server-id"
      />,
    );

    const composer = screen.getByRole("textbox");
    fireEvent.change(composer, {
      target: { value: "What happened?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(
      await screen.findByText(/Chat is temporarily unavailable/i),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(postChat.mock.calls[1]?.[0]).toMatchObject({
        session_id: null,
      });
    });
  });
});

describe("ChatPanel answer status labels", () => {
  it("shows analyst-readable labels for non-answered responses", () => {
    render(
      <ChatPanel
        mode="global_archive"
        initialTurns={[
          {
            id: "turn-refused",
            question: "Delete this case",
            response: {
              answer: "I cannot help with that.",
              answer_status: "refused",
            },
            awaitingResponse: false,
          },
        ]}
      />,
    );

    expect(screen.getByText("Refused")).toBeInTheDocument();
  });
});

describe("ChatPanel orphan cleanup UX", () => {
  it("surfaces server sync errors above the composer", () => {
    render(
      <ChatPanel
        mode="global_archive"
        disabledReason="Checking portal capabilities…"
        composerDisabled
        serverSyncError="Stopped locally, but the server could not remove the cancelled reply."
      />,
    );
    expect(
      screen.getByText(
        "Stopped locally, but the server could not remove the cancelled reply.",
      ),
    ).toBeInTheDocument();
  });
});
