import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CasesPage } from "./CasesPage";

const {
  fetchCase,
  fetchCases,
  matchingCaseDetail,
  matchingCaseSummary,
  MockApiError,
} = vi.hoisted(() => {
    class MockApiError extends Error {
      status: number;

      constructor(status: number, message: string) {
        super(message);
        this.status = status;
      }
    }

    const matchingCaseSummary = {
      case_id: "case-123",
      processed_at: "2026-06-04T00:00:00Z",
      expires_at: "2026-07-04T00:00:00Z",
      verdict: "unknown",
      confidence: null,
      search_name: "case-123",
      retrieval_status: "ready",
      source_completeness: "complete",
      archive_notices: [],
    };

    const matchingCaseDetail = {
      case_id: matchingCaseSummary.case_id,
      metadata: {
        processed_at: matchingCaseSummary.processed_at,
        expires_at: matchingCaseSummary.expires_at,
        retrieval_status: matchingCaseSummary.retrieval_status,
        source_completeness: matchingCaseSummary.source_completeness,
        archive_notices: matchingCaseSummary.archive_notices,
      },
      alert_payload: {
        search_name: matchingCaseSummary.search_name,
      },
      analysis: {
        verdict: matchingCaseSummary.verdict,
        confidence: matchingCaseSummary.confidence,
      },
      report_md_path: "/reports/case-123.md",
      report_html_path: null,
      content_bounds: {
        alert_payload_truncated: false,
        analysis_truncated: false,
        alert_payload_total_keys: 1,
        analysis_total_keys: 2,
        raw_sections: ["alert_payload", "analysis"],
      },
    };

    const fetchCases = vi.fn(async () => ({
      items: [],
        limit: 50,
        has_more: false,
        next_cursor: null,
    }));
    const fetchCase = vi.fn(async () => matchingCaseDetail);

    return {
      fetchCase,
      fetchCases,
      matchingCaseDetail,
      matchingCaseSummary,
      MockApiError,
    };
  });

vi.mock("../api/client", () => ({
  ApiError: MockApiError,
  fetchCase: (...args: unknown[]) => fetchCase(...args),
  fetchCases: (...args: unknown[]) => fetchCases(...args),
  isCancelledRequest: () => false,
}));

function renderCasesPage() {
  return render(
    <MemoryRouter>
      <CasesPage />
    </MemoryRouter>,
  );
}

async function flushSearchDebounce() {
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
  });
}

describe("CasesPage", () => {
  beforeEach(() => {
    fetchCase.mockReset();
    fetchCase.mockImplementation(async () => matchingCaseDetail);
    fetchCases.mockReset();
    fetchCases.mockImplementation(async () => ({
      items: [],
        limit: 50,
        has_more: false,
        next_cursor: null,
    }));
  });

  afterEach(() => {
    cleanup();
  });

  it("uses alert-name search without exact case lookup", async () => {
    renderCasesPage();
    await waitFor(() => expect(fetchCases).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Alert name"), {
      target: { value: "case-123" },
    });
    await flushSearchDebounce();

    await waitFor(() =>
      expect(fetchCases).toHaveBeenLastCalledWith(
        expect.objectContaining({ search_name: "case-123" }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
    expect(fetchCase).not.toHaveBeenCalled();
  });

  it("shows filter-specific empty-state guidance when no cases match", async () => {
    renderCasesPage();
    await waitFor(() => expect(fetchCases).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Alert name"), {
      target: { value: "missing-alert" },
    });
    await flushSearchDebounce();
    await waitFor(() => expect(fetchCases).toHaveBeenCalledTimes(2));

    expect(screen.getByText("No cases match these filters")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Clear filters" }),
    ).toBeInTheDocument();
  });

  it("uses the case-id field for exact case lookup", async () => {
    renderCasesPage();
    await waitFor(() => expect(fetchCases).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Case ID"), {
      target: { value: "case-123" },
    });
    await flushSearchDebounce();

    await waitFor(() =>
      expect(fetchCase).toHaveBeenCalledWith(
        "case-123",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
    expect(fetchCases).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByRole("link", { name: matchingCaseSummary.case_id }),
    ).toBeInTheDocument();
  });
});
