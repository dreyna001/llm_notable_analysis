import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PortalCapabilityBanner } from "./PortalCapabilityBanner";

const enabledCapabilities = {
  case_qa_enabled: true,
  global_retrieval_enabled: true,
  chat_history_enabled: true,
  general_knowledge_enabled: true,
  max_question_chars: 2000,
  max_answer_tokens: 800,
  chat_ready: true,
};

describe("PortalCapabilityBanner", () => {
  it("shows a loading notice while capabilities are unresolved", () => {
    render(
      <PortalCapabilityBanner
        capabilities={null}
        capabilitiesLoaded={false}
        capabilitiesLoadError={null}
      />,
    );
    expect(screen.getByText("Checking portal capabilities…")).toBeInTheDocument();
  });

  it("fails closed when capabilities cannot be loaded", () => {
    render(
      <PortalCapabilityBanner
        capabilities={null}
        capabilitiesLoaded={true}
        capabilitiesLoadError="503: Portal API unavailable."
      />,
    );
    expect(
      screen.getByText("503: Portal API unavailable."),
    ).toBeInTheDocument();
  });

  it("shows chat degradation when runtime dependencies are unavailable", () => {
    render(
      <PortalCapabilityBanner
        capabilities={{
          ...enabledCapabilities,
          chat_ready: false,
          chat_degraded_reason:
            "Case chat is temporarily unavailable. Embeddings, archive retrieval, or the LLM may be down.",
        }}
        capabilitiesLoaded={true}
        capabilitiesLoadError={null}
      />,
    );
    expect(
      screen.getByText(
        "Case chat is temporarily unavailable. Embeddings, archive retrieval, or the LLM may be down.",
      ),
    ).toBeInTheDocument();
  });

  it("shows attach and history errors without enabling chat", () => {
    render(
      <PortalCapabilityBanner
        capabilities={enabledCapabilities}
        capabilitiesLoaded={true}
        capabilitiesLoadError={null}
        attachError="Case not found or unavailable."
        historyLoadError="Could not load chat history. 503: unavailable"
      />,
    );
    expect(
      screen.getByText("Case not found or unavailable."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Could not load chat history. 503: unavailable"),
    ).toBeInTheDocument();
  });
});
