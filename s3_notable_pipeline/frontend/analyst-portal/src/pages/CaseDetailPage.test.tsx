import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CaseDetailPage } from "./CaseDetailPage";

const { fetchCase, MockApiError, nullAnalysisCase } = vi.hoisted(() => {
  class MockApiError extends Error {
    status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }

  const nullAnalysisCase = {
    case_id: "case-1",
    metadata: {
      processed_at: "2026-06-04T00:00:00Z",
      expires_at: "2026-07-04T00:00:00Z",
      retrieval_status: "not_indexed",
      source_completeness: "missing_analysis",
      archive_notices: [
        "Structured analysis was not stored for this case. Chat can use the alert payload only.",
      ],
    },
    alert_payload: {
      notable_id: "abc-123",
      search_name: "Suspicious PowerShell",
    },
    analysis: null,
    report_md_path: "/reports/case-1.md",
    report_html_path: null,
    content_bounds: {
      alert_payload_truncated: false,
      analysis_truncated: false,
      alert_payload_total_keys: 2,
      analysis_total_keys: 0,
      raw_sections: ["alert_payload", "analysis"],
    },
  };

  const fetchCase = vi.fn(async () => nullAnalysisCase);
  return { fetchCase, MockApiError, nullAnalysisCase };
});

vi.mock("../api/client", () => ({
  ApiError: MockApiError,
  fetchCase: (...args: unknown[]) => fetchCase(...args),
  fetchCaseRawSection: vi.fn(),
  isCancelledRequest: () => false,
}));

function renderCaseDetail() {
  return render(
    <MemoryRouter initialEntries={["/cases/case-1"]}>
      <Routes>
        <Route path="/cases/:caseId" element={<CaseDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CaseDetailPage", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    fetchCase.mockReset();
    fetchCase.mockImplementation(async () => nullAnalysisCase);
  });

  it("shows a controlled error when the case payload is invalid", async () => {
    fetchCase.mockRejectedValueOnce(
      new MockApiError(502, "Portal API returned an unexpected response."),
    );

    renderCaseDetail();

    expect(
      await screen.findByText("502: Portal API returned an unexpected response."),
    ).toBeInTheDocument();
  });

  it("renders cases without structured analysis", async () => {
    renderCaseDetail();

    expect(await screen.findByText("case-1")).toBeInTheDocument();
    expect(screen.getByText("Suspicious PowerShell")).toBeInTheDocument();
    expect(screen.getByText("Not indexed")).toBeInTheDocument();
    expect(screen.getByText("Structured analysis missing")).toBeInTheDocument();
    expect(screen.getByText("No hypothesis summary available.")).toBeInTheDocument();
    expect(screen.getByText("Case notice")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Structured analysis was not stored for this case. Chat can use the alert payload only.",
      ),
    ).toBeInTheDocument();
  });
});
