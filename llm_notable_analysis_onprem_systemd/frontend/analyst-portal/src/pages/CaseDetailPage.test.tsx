import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CaseDetail } from "../types";
import { CaseDetailPage } from "./CaseDetailPage";

const nullAnalysisCase: CaseDetail = {
  case_id: "case-1",
  metadata: {
    processed_at: "2026-06-04T00:00:00Z",
    expires_at: "2026-07-04T00:00:00Z",
    retrieval_status: "not_indexed",
    source_completeness: "missing_analysis",
    archive_notices: [
      "Structured analysis was not stored in the case archive. Chat can use the alert payload only.",
    ],
  },
  alert_payload: {
    notable_id: "abc-123",
    search_name: "Suspicious PowerShell",
  },
  analysis: null,
  report_md_path: "/reports/case-1.md",
  report_html_path: null,
};

const fetchCase = vi.fn(async () => nullAnalysisCase);

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  fetchCase: (...args: unknown[]) => fetchCase(...args),
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
  beforeEach(() => {
    fetchCase.mockClear();
  });

  it("renders cases without structured analysis", async () => {
    renderCaseDetail();

    expect(await screen.findByText("case-1")).toBeInTheDocument();
    expect(screen.getByText("Suspicious PowerShell")).toBeInTheDocument();
    expect(screen.getByText("Not indexed")).toBeInTheDocument();
    expect(screen.getByText("missing_analysis")).toBeInTheDocument();
    expect(screen.getByText("No hypothesis summary available.")).toBeInTheDocument();
    expect(screen.getByText("Case archive notice")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Structured analysis was not stored in the case archive. Chat can use the alert payload only.",
      ),
    ).toBeInTheDocument();
  });
});
