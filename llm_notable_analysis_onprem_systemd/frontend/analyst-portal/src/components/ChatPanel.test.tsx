import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { ChatPanel } from "./ChatPanel";
import * as chatImageAttachment from "../utils/chatImageAttachment";

const postChat = vi.fn();

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    postChat: (...args: unknown[]) => postChat(...args),
  };
});

function mockObjectUrls() {
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview-url");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
}

function pngFile(name = "screenshot.png", size = 128): File {
  return new File([new Uint8Array(size)], name, { type: "image/png" });
}

async function attachImage(file: File) {
  const fileInput = document.querySelector(
    'input[type="file"]',
  ) as HTMLInputElement | null;
  if (!fileInput) {
    throw new Error("File input not found");
  }
  fireEvent.change(fileInput, { target: { files: [file] } });
  await screen.findByText(file.name);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
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
        mode="selected_case" selectedCaseId="case-1"
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
        mode="selected_case" selectedCaseId="case-1"
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
        key="session-a:selected_case:case-1:ready"
        mode="selected_case" selectedCaseId="case-1"
        initialTurns={[firstTurn]}
      />,
    );

    expect(screen.getByText("First question")).toBeInTheDocument();

    rerender(
      <ChatPanel
        key="session-b:selected_case:case-1:ready"
        mode="selected_case" selectedCaseId="case-1"
        initialTurns={[]}
      />,
    );

    expect(screen.queryByText("First question")).not.toBeInTheDocument();
    expect(screen.getByText("Start investigating this case")).toBeInTheDocument();
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

    render(<ChatPanel mode="selected_case" selectedCaseId="case-1" />);

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
        mode="selected_case" selectedCaseId="case-1"
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
        mode="selected_case" selectedCaseId="case-1"
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
        mode="selected_case" selectedCaseId="case-1"
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

describe("ChatPanel image attachments", () => {
  beforeEach(() => {
    postChat.mockReset();
    mockObjectUrls();
  });

  it("hides image controls when chat images are disabled", () => {
    render(
      <ChatPanel mode="selected_case" selectedCaseId="case-1" />,
    );

    expect(screen.queryByLabelText("Attach image")).not.toBeInTheDocument();
  });

  it("sends a valid image payload for the current request only", async () => {
    postChat.mockResolvedValue({
      answer: "Looks like a login page.",
      answer_status: "answered",
      session_id: "session-1",
    });

    render(
      <ChatPanel
        chatImagesEnabled
        maxChatImageBytes={1024 * 1024}
        mode="selected_case"
        selectedCaseId="case-1"
      />,
    );

    await attachImage(pngFile());

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "What is in this screenshot?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => {
      expect(postChat).toHaveBeenCalledTimes(1);
    });

    expect(postChat.mock.calls[0]?.[0]).toMatchObject({
      question: "What is in this screenshot?",
      images: [
        {
          media_type: "image/png",
          data_base64: expect.any(String),
        },
      ],
    });
    expect(await screen.findByText("Looks like a login page.")).toBeInTheDocument();
    expect(screen.queryByText("screenshot.png")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Attach image")).toBeInTheDocument();
  });

  it("rejects unsupported mime types", async () => {
    render(
      <ChatPanel
        chatImagesEnabled
        mode="selected_case"
        selectedCaseId="case-1"
      />,
    );

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["pdf"], "notes.pdf", { type: "application/pdf" })],
      },
    });

    expect(
      await screen.findByText(/Only PNG, JPEG, WebP, and GIF images are supported/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("notes.pdf")).not.toBeInTheDocument();
  });

  it("rejects oversized files using capability limits", async () => {
    render(
      <ChatPanel
        chatImagesEnabled
        maxChatImageBytes={256}
        mode="selected_case"
        selectedCaseId="case-1"
      />,
    );

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [pngFile("large.png", 512)] },
    });

    expect(
      await screen.findByText(/256 B or smaller/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("large.png")).not.toBeInTheDocument();
  });

  it("removes a selected attachment", async () => {
    render(
      <ChatPanel
        chatImagesEnabled
        mode="selected_case"
        selectedCaseId="case-1"
      />,
    );

    await attachImage(pngFile("remove-me.png"));
    fireEvent.click(screen.getByRole("button", { name: /remove attached image/i }));

    expect(screen.queryByText("remove-me.png")).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview-url");
  });

  it("shows a conversion failure and keeps send disabled while converting", async () => {
    vi.spyOn(chatImageAttachment, "fileToChatImagePayload").mockRejectedValue(
      new Error("read failed"),
    );

    render(
      <ChatPanel
        chatImagesEnabled
        mode="selected_case"
        selectedCaseId="case-1"
      />,
    );

    await attachImage(pngFile());
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Analyze this" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(
      await screen.findByText(/Could not read the selected image/i),
    ).toBeInTheDocument();
    expect(postChat).not.toHaveBeenCalled();
  });

  it("reuses the same image payload when retrying a stale session", async () => {
    postChat
      .mockRejectedValueOnce(
        new ApiError(410, "session_id has expired."),
      )
      .mockResolvedValueOnce({
        answer: "Retried with image.",
        answer_status: "answered",
        session_id: "fresh-session",
      });

    render(
      <ChatPanel
        chatImagesEnabled
        initialSessionId="expired-server-id"
        mode="selected_case"
        selectedCaseId="case-1"
      />,
    );

    await attachImage(pngFile());
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Retry with image" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Retried with image.")).toBeInTheDocument();
    expect(postChat.mock.calls[0]?.[0]?.images?.[0]?.data_base64).toBeTruthy();
    expect(postChat.mock.calls[1]?.[0]?.images?.[0]?.data_base64).toBe(
      postChat.mock.calls[0]?.[0]?.images?.[0]?.data_base64,
    );
    expect(screen.queryByText("screenshot.png")).not.toBeInTheDocument();
  });

  it("does not render attached images in historical turns", async () => {
    postChat.mockResolvedValue({
      answer: "Done.",
      answer_status: "answered",
      session_id: "session-1",
    });

    render(
      <ChatPanel
        chatImagesEnabled
        mode="selected_case"
        selectedCaseId="case-1"
      />,
    );

    await attachImage(pngFile("history.png"));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Question with image" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Done.")).toBeInTheDocument();
    expect(screen.getByText("Question with image")).toBeInTheDocument();
    expect(screen.queryByText("history.png")).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
