import { useEffect, useState, type FormEvent } from "react";
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
import { cn } from "@/lib/utils";
import { ApiError, fetchCases } from "../api/client";
import type { CaseSummary } from "../types";

type CaseFilters = {
  start: string;
  end: string;
  verdict: string;
  search_name: string;
};

const EMPTY_FILTERS: CaseFilters = {
  start: "",
  end: "",
  verdict: "",
  search_name: "",
};

function normalizeVerdict(verdict: string | null | undefined): string {
  const text = String(verdict ?? "").toLowerCase().replace(/[\s-]+/g, "_");
  if (text.includes("malicious") || text.includes("true_positive")) {
    return "likely_malicious";
  }
  if (text.includes("benign") || text.includes("false_positive")) {
    return "likely_benign";
  }
  return "unknown";
}

function verdictLabel(verdict: string | null): string {
  const labels: Record<string, string> = {
    likely_malicious: "Likely malicious",
    likely_benign: "Likely benign",
    unknown: "Unknown",
  };
  return labels[normalizeVerdict(verdict)];
}

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

const selectClassName = cn(
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm",
  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
);

export function CasesPage() {
  const [items, setItems] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [draftFilters, setDraftFilters] = useState<CaseFilters>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<CaseFilters>(EMPTY_FILTERS);
  const limit = 50;
  const currentPage = Math.floor(offset / limit) + 1;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchCases({
      limit,
      offset,
      start: filters.start || undefined,
      end: filters.end || undefined,
      verdict: filters.verdict || undefined,
      search_name: filters.search_name || undefined,
    })
      .then((payload) => {
        if (!cancelled) {
          setItems(payload.items);
          setHasMore(payload.has_more);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message =
            err instanceof ApiError
              ? `${err.status}: ${err.message}`
              : err instanceof Error
                ? err.message
                : "Unknown error";
          setItems([]);
          setError(message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [offset, filters]);

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOffset(0);
    setFilters({
      start: draftFilters.start.trim(),
      end: draftFilters.end.trim(),
      verdict: draftFilters.verdict.trim(),
      search_name: draftFilters.search_name.trim(),
    });
  }

  function clearFilters() {
    setDraftFilters(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
    setOffset(0);
  }

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
            className="grid gap-4 border-b border-border/60 pb-4 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5"
            onSubmit={applyFilters}
          >
            <div className="space-y-1.5">
              <Label htmlFor="filter-start">Start</Label>
              <Input
                id="filter-start"
                type="datetime-local"
                value={draftFilters.start}
                onChange={(event) =>
                  setDraftFilters((value) => ({
                    ...value,
                    start: event.target.value,
                  }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="filter-end">End</Label>
              <Input
                id="filter-end"
                type="datetime-local"
                value={draftFilters.end}
                onChange={(event) =>
                  setDraftFilters((value) => ({
                    ...value,
                    end: event.target.value,
                  }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="filter-verdict">Verdict</Label>
              <select
                className={selectClassName}
                id="filter-verdict"
                value={draftFilters.verdict}
                onChange={(event) =>
                  setDraftFilters((value) => ({
                    ...value,
                    verdict: event.target.value,
                  }))
                }
              >
                <option value="">Any verdict</option>
                <option value="likely_malicious">Likely malicious</option>
                <option value="likely_benign">Likely benign</option>
                <option value="unknown">Unknown</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="filter-search">Alert name</Label>
              <Input
                id="filter-search"
                placeholder="Partial alert name"
                type="text"
                value={draftFilters.search_name}
                onChange={(event) =>
                  setDraftFilters((value) => ({
                    ...value,
                    search_name: event.target.value,
                  }))
                }
              />
            </div>
            <div className="flex items-end gap-2">
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
          </form>

          {loading ? (
            <p className="text-sm text-muted-foreground">Loading cases...</p>
          ) : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          {!loading && !error && items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No cases found.</p>
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
                    <th className="pb-3 font-medium">Chatbot Readiness</th>
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
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {item.source_completeness}
                        </div>
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
                      <td className="py-3">
                        <Badge
                          variant={retrievalBadgeVariant(item.retrieval_status)}
                        >
                          {item.retrieval_status}
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
              disabled={offset === 0 || loading}
              type="button"
              variant="outline"
              onClick={() => setOffset((value) => Math.max(0, value - limit))}
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
              onClick={() => setOffset((value) => value + limit)}
            >
              Next page
            </Button>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
