import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatPanel } from "./ChatPanel";

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
