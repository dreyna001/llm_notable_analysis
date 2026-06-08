import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

describe("ChatPanel session scope recovery", () => {
  beforeEach(() => {
    postChat.mockReset();
  });

  it("shows recovery guidance when the server rejects a stale session id", async () => {
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

    expect(
      await screen.findByText(
        "This chat no longer matches the selected case or mode. Your next message will start a fresh server session.",
      ),
    ).toBeInTheDocument();

    expect(postChat.mock.calls[0]?.[0]).toMatchObject({
      session_id: "stale-server-id",
    });

    fireEvent.change(composer, {
      target: { value: "Try again" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => {
      expect(postChat.mock.calls[1]?.[0]).toMatchObject({
        session_id: null,
      });
    });
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
