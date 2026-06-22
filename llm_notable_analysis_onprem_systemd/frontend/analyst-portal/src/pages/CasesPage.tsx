import { useEffect, useState, type FormEvent, type MouseEvent } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { EmptyState } from "../components/EmptyState";
import { CasesTableSkeleton } from "../components/LoadingSkeletons";
import { ApiError, fetchCase, fetchCases, isCancelledRequest } from "../api/client";
import type { CaseListCursor, CaseSummary } from "../types";
import { caseDetailToSummary } from "../utils/caseSummary";
import { retrievalStatusLabel } from "../utils/retrievalStatus";
import { sourceCompletenessLabel } from "../utils/sourceCompleteness";
import {
  normalizeUtcFilterDate,
  processedAtMatchesUtcDateRange,
} from "../utils/utcDateFilter";
import { resolveCasesEmptyState } from "../utils/casesEmptyState";
import { normalizeVerdict, verdictLabel } from "../utils/verdict";

type CaseFilters = {
  start_date: string;
  end_date: string;
  verdict: string;
  case_id: string;
  search_name: string;
};

const EMPTY_FILTERS: CaseFilters = {
  start_date: "",
  end_date: "",
  verdict: "",
  case_id: "",
  search_name: "",
};

function verdictBadgeVariant(
  verdict: string | null,
): "destructive" | "success" | "warning" {
  switch (normalizeVerdict(verdict)) {
    case "likely_malicious":
      return "destructive";
    case "likely_benign":
      return "success";
    default:
      return "warning";
  }
}

function retrievalBadgeVariant(
  status: string | null | undefined,
): "success" | "warning" | "destructive" | "muted" {
  switch (status) {
    case "ready":
      return "success";
    case "pending":
      return "warning";
    case "failed":
      return "destructive";
    default:
      return "muted";
  }
}

function exactCaseMatchesFilters(
  item: CaseSummary,
  filters: CaseFilters,
): boolean {
  if (filters.verdict && normalizeVerdict(item.verdict) !== filters.verdict) {
    return false;
  }
  const searchTerm = filters.search_name.trim().toLowerCase();
  if (searchTerm && !item.search_name?.toLowerCase().includes(searchTerm)) {
    return false;
  }
  return processedAtMatchesUtcDateRange(
    item.processed_at,
    filters.start_date,
    filters.end_date,
  );
}

function openNativeDatePicker(event: MouseEvent<HTMLInputElement>) {
  const input = event.currentTarget;
  if (typeof input.showPicker === "function") {
    try {
      input.showPicker();
      return;
    } catch {
      // Fall through to focus when the browser blocks showPicker.
    }
  }
  input.focus();
}

const dateInputClassName = cn(
  "h-10 w-full min-w-[11rem] cursor-pointer bg-background px-3",
  "[color-scheme:dark] appearance-none",
  "[&::-webkit-calendar-picker-indicator]:hidden",
  "[&::-webkit-calendar-picker-indicator]:appearance-none",
);

type DateFilterFieldProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
};

function DateFilterField({ id, label, value, onChange }: DateFilterFieldProps) {
  return (
    <div className="w-full min-w-[11rem] sm:w-44">
      <Label className="mb-1.5 block" htmlFor={id}>
        {label}
      </Label>
      <Input
        className={dateInputClassName}
        id={id}
        type="date"
        value={normalizeUtcFilterDate(value)}
        onChange={(event) => onChange(event.target.value)}
        onClick={openNativeDatePicker}
      />
    </div>
  );
}

const VERDICT_FILTER_ANY = "any";
const SEARCH_DEBOUNCE_MS = 300;

export function CasesPage() {
  const [items, setItems] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageCursors, setPageCursors] = useState<(CaseListCursor | null)[]>([null]);
  const [draftFilters, setDraftFilters] = useState<CaseFilters>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<CaseFilters>(EMPTY_FILTERS);
  const limit = 50;
  const currentPage = pageIndex + 1;
  const activeCursor = pageCursors[pageIndex] ?? null;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const nextSearch = draftFilters.search_name.trim();
      const nextCaseId = draftFilters.case_id.trim();
      setFilters((previous) => {
        if (
          previous.search_name === nextSearch &&
          previous.case_id === nextCaseId
        ) {
          return previous;
        }
        return { ...previous, case_id: nextCaseId, search_name: nextSearch };
      });
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [draftFilters.case_id, draftFilters.search_name]);

  useEffect(() => {
    setPageIndex(0);
    setPageCursors([null]);
  }, [filters.case_id, filters.search_name]);

  useEffect(() => {
    setPageIndex(0);
    setPageCursors([null]);
  }, [
    filters.start_date,
    filters.end_date,
    filters.verdict,
  ]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    const caseId = filters.case_id.trim();
    const searchTerm = filters.search_name.trim();
    const { signal } = controller;

    if (caseId) {
      fetchCase(caseId, { signal })
        .then(caseDetailToSummary)
        .catch((err: unknown) => {
          if (isCancelledRequest(err, signal)) {
            return null;
          }
          if (err instanceof ApiError && err.status === 404) {
            return null;
          }
          throw err;
        })
        .then((exactCase) => {
          if (signal.aborted) {
            return;
          }
          const filteredExactCase =
            exactCase && exactCaseMatchesFilters(exactCase, filters)
              ? exactCase
              : null;
          setItems(filteredExactCase ? [filteredExactCase] : []);
          setHasMore(false);
          setError(null);
        })
        .catch((err: unknown) => {
          if (isCancelledRequest(err, signal)) {
            return;
          }
          const message =
            err instanceof ApiError
              ? `${err.status}: ${err.message}`
              : err instanceof Error
                ? err.message
                : "Unknown error";
          setError(message);
        })
        .finally(() => {
          if (!signal.aborted) {
            setLoading(false);
          }
        });
      return () => {
        controller.abort();
      };
    }

    fetchCases(
      {
        limit,
        cursor: activeCursor,
        start_date: filters.start_date || undefined,
        end_date: filters.end_date || undefined,
        verdict: filters.verdict || undefined,
        search_name: searchTerm || undefined,
      },
      { signal },
    )
      .then((payload) => {
        if (signal.aborted) {
          return;
        }
        setItems(payload.items);
        setHasMore(payload.has_more);
        if (payload.next_cursor) {
          setPageCursors((current) => {
            const next = current.slice(0, pageIndex + 1);
            next[pageIndex + 1] = payload.next_cursor;
            return next;
          });
        }
        setError(null);
      })
      .catch((err: unknown) => {
        if (isCancelledRequest(err, signal)) {
          return;
        }
        const message =
          err instanceof ApiError
            ? `${err.status}: ${err.message}`
            : err instanceof Error
              ? err.message
              : "Unknown error";
        setError(message);
      })
      .finally(() => {
        if (!signal.aborted) {
          setLoading(false);
        }
      });
    return () => {
      controller.abort();
    };
  }, [activeCursor, filters, limit, pageIndex]);

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPageIndex(0);
    setPageCursors([null]);
    setFilters({
      start_date: normalizeUtcFilterDate(draftFilters.start_date),
      end_date: normalizeUtcFilterDate(draftFilters.end_date),
      verdict: draftFilters.verdict.trim(),
      case_id: draftFilters.case_id.trim(),
      search_name: draftFilters.search_name.trim(),
    });
  }

  function clearFilters() {
    setDraftFilters(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
    setPageIndex(0);
    setPageCursors([null]);
  }

  function clearCaseIdFilter() {
    setDraftFilters((current) => ({ ...current, case_id: "" }));
    setFilters((current) => ({ ...current, case_id: "" }));
    setPageIndex(0);
    setPageCursors([null]);
  }

  const casesEmptyState = resolveCasesEmptyState(filters);
  const casesEmptyAction =
    casesEmptyState.action === "clear_filters"
      ? { label: "Clear filters", onClick: clearFilters }
      : casesEmptyState.action === "clear_case_id"
        ? { label: "Clear case ID", onClick: clearCaseIdFilter }
        : undefined;

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Cases</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Open a case to inspect alert analysis
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Case index</CardTitle>
          <CardDescription>
            Filter and browse retained case summaries
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            className="border-b border-border/60 pb-4"
            onSubmit={applyFilters}
          >
            <div className="flex flex-wrap items-start gap-4">
              <DateFilterField
                id="filter-start"
                label="Start (UTC)"
                value={draftFilters.start_date}
                onChange={(start_date) =>
                  setDraftFilters((value) => ({
                    ...value,
                    start_date,
                  }))
                }
              />
              <DateFilterField
                id="filter-end"
                label="End (UTC)"
                value={draftFilters.end_date}
                onChange={(end_date) =>
                  setDraftFilters((value) => ({
                    ...value,
                    end_date,
                  }))
                }
              />
              <div className="w-full min-w-[10rem] sm:w-40">
                <Label className="mb-1.5 block" htmlFor="filter-verdict">
                  Verdict
                </Label>
                <Select
                  value={draftFilters.verdict || VERDICT_FILTER_ANY}
                  onValueChange={(verdict) =>
                    setDraftFilters((value) => ({
                      ...value,
                      verdict: verdict === VERDICT_FILTER_ANY ? "" : verdict,
                    }))
                  }
                >
                  <SelectTrigger className="h-10" id="filter-verdict">
                    <SelectValue placeholder="Any verdict" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={VERDICT_FILTER_ANY}>Any verdict</SelectItem>
                    <SelectItem value="likely_malicious">Likely malicious</SelectItem>
                    <SelectItem value="likely_benign">Likely benign</SelectItem>
                    <SelectItem value="unknown">Unknown</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="min-w-[12rem] flex-1">
                <Label className="mb-1.5 block" htmlFor="filter-case-id">
                  Case ID
                </Label>
                <Input
                  className="h-10 bg-background"
                  id="filter-case-id"
                  placeholder="Exact case ID"
                  type="search"
                  value={draftFilters.case_id}
                  onChange={(event) =>
                    setDraftFilters((value) => ({
                      ...value,
                      case_id: event.target.value,
                    }))
                  }
                />
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Exact lookup for one case ID. Verdict and date filters still
                  apply.
                </p>
              </div>
              <div className="min-w-[12rem] flex-1">
                <Label className="mb-1.5 block" htmlFor="filter-search">
                  Alert name
                </Label>
                <Input
                  className="h-10 bg-background"
                  id="filter-search"
                  placeholder="Partial alert name"
                  type="search"
                  value={draftFilters.search_name}
                  onChange={(event) =>
                    setDraftFilters((value) => ({
                      ...value,
                      search_name: event.target.value,
                    }))
                  }
                />
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Partial name search only. This does not look up cases by ID.
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2 self-end pb-0.5">
                <Button disabled={loading} type="submit">
                  Apply filters
                </Button>
                <Button
                  disabled={loading}
                  type="button"
                  variant="outline"
                  onClick={clearFilters}
                >
                  Clear
                </Button>
              </div>
            </div>
          </form>

          {loading ? <CasesTableSkeleton /> : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          {!loading && !error && items.length === 0 ? (
            <EmptyState
              action={casesEmptyAction}
              description={casesEmptyState.description}
              title={casesEmptyState.title}
            />
          ) : null}

          {!loading && items.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="pb-3 pr-4 font-medium">Case ID</th>
                    <th className="pb-3 pr-4 font-medium">Processed</th>
                    <th className="pb-3 pr-4 font-medium">Verdict</th>
                    <th className="pb-3 pr-4 font-medium">Alert name</th>
                    <th className="pb-3 pr-4 font-medium">Chatbot Readiness</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr
                      className="border-b border-border/60 align-top"
                      key={item.case_id}
                    >
                      <td className="py-3 pr-4">
                        <Link
                          className="font-medium hover:underline"
                          to={`/cases/${encodeURIComponent(item.case_id)}`}
                        >
                          {item.case_id}
                        </Link>
                        {item.archive_notices?.length ? (
                          <div className="mt-0.5 text-xs text-amber-700 dark:text-amber-200">
                            Case issue: open case for details
                          </div>
                        ) : (
                          <div className="mt-0.5 text-xs text-muted-foreground">
                            {sourceCompletenessLabel(item.source_completeness)}
                          </div>
                        )}
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">
                        {item.processed_at ?? "-"}
                      </td>
                      <td className="py-3 pr-4">
                        <Badge variant={verdictBadgeVariant(item.verdict)}>
                          {verdictLabel(item.verdict)}
                        </Badge>
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">
                        {item.search_name ?? "-"}
                      </td>
                      <td className="py-3 pr-4">
                        <Badge
                          variant={retrievalBadgeVariant(item.retrieval_status)}
                        >
                          {retrievalStatusLabel(item.retrieval_status)}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          <div className="flex items-center gap-4 pt-2">
            <Button
              disabled={pageIndex === 0 || loading}
              type="button"
              variant="outline"
              onClick={() => setPageIndex((value) => Math.max(0, value - 1))}
            >
              Previous page
            </Button>
            <span className="text-sm text-muted-foreground">
              Page {currentPage} · {limit} cases per page
            </span>
            <Button
              disabled={!hasMore || loading}
              type="button"
              variant="outline"
              onClick={() => setPageIndex((value) => value + 1)}
            >
              Next page
            </Button>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
