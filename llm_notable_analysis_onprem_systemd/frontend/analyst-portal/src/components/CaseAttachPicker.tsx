import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { CaseAttachListSkeleton } from "./LoadingSkeletons";
import { EmptyState } from "./EmptyState";
import { ApiError, fetchCase, fetchCases, isCancelledRequest } from "../api/client";
import { resolveCaseAttachEmptyState } from "../utils/caseAttachEmptyState";
import type { CaseListCursor, CaseSummary } from "../types";
import { caseDetailToSummary } from "../utils/caseSummary";

const SEARCH_DEBOUNCE_MS = 300;
const PAGE_SIZE = 50;

type CaseOptionsPage = {
  items: CaseSummary[];
  hasMore: boolean;
  nextCursor: CaseListCursor | null;
};

type CaseAttachPickerProps = {
  onAttachCase: (caseSummary: CaseSummary) => void;
  attachedCaseId?: string;
  disabled?: boolean;
  label?: string;
};

function matchesQuery(item: CaseSummary, query: string): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  if (item.case_id.toLowerCase().includes(normalized)) {
    return true;
  }
  return item.search_name?.toLowerCase().includes(normalized) ?? false;
}

async function loadCaseOptions(
  searchTerm: string,
  cursor: CaseListCursor | null,
  signal?: AbortSignal,
): Promise<CaseOptionsPage> {
  const trimmed = searchTerm.trim();
  const [listResult, exactDetail] = await Promise.all([
    fetchCases(
      {
        limit: PAGE_SIZE,
        cursor,
        search_name: trimmed || undefined,
      },
      { signal },
    ),
    cursor === null && trimmed
      ? fetchCase(trimmed, { signal }).catch((error: unknown) => {
          if (isCancelledRequest(error, signal)) {
            throw error;
          }
          if (error instanceof ApiError && error.status === 404) {
            return null;
          }
          throw error;
        })
      : Promise.resolve(null),
  ]);

  let items = listResult.items;
  if (exactDetail) {
    const exactSummary = caseDetailToSummary(exactDetail);
    if (!items.some((item) => item.case_id === exactSummary.case_id)) {
      items = [exactSummary, ...items];
    }
  }

  if (trimmed) {
    items = items.filter((item) => matchesQuery(item, trimmed));
  }

  return {
    items,
    hasMore: listResult.has_more,
    nextCursor: listResult.next_cursor,
  };
}

function mergeCaseItems(
  existing: CaseSummary[],
  incoming: CaseSummary[],
): CaseSummary[] {
  if (!incoming.length) {
    return existing;
  }
  const seen = new Set(existing.map((item) => item.case_id));
  const merged = [...existing];
  for (const item of incoming) {
    if (!seen.has(item.case_id)) {
      seen.add(item.case_id);
      merged.push(item);
    }
  }
  return merged;
}

export function CaseAttachPicker({
  onAttachCase,
  attachedCaseId,
  disabled = false,
  label = "Attach case",
}: CaseAttachPickerProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [items, setItems] = useState<CaseSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<CaseListCursor | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedQuery(query),
      SEARCH_DEBOUNCE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setLoading(true);
    setError(null);
    setNextCursor(null);

    loadCaseOptions(debouncedQuery, null, signal)
      .then((page) => {
        if (signal.aborted) {
          return;
        }
        setItems(page.items);
        setHasMore(page.hasMore);
        setNextCursor(page.nextCursor);
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
        setItems([]);
        setHasMore(false);
      })
      .finally(() => {
        if (!signal.aborted) {
          setLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [debouncedQuery]);

  const handleLoadMore = useCallback(async () => {
    if (loading || loadingMore || !hasMore || !nextCursor) {
      return;
    }
    setLoadingMore(true);
    setError(null);
    try {
      const page = await loadCaseOptions(debouncedQuery, nextCursor);
      setItems((current) => mergeCaseItems(current, page.items));
      setNextCursor(page.nextCursor);
      setHasMore(page.hasMore);
    } catch (err: unknown) {
      const message =
        err instanceof ApiError
          ? `${err.status}: ${err.message}`
          : err instanceof Error
            ? err.message
            : "Unknown error";
      setError(message);
    } finally {
      setLoadingMore(false);
    }
  }, [debouncedQuery, hasMore, loading, loadingMore, nextCursor]);

  const attachEmptyState = resolveCaseAttachEmptyState(query);

  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground" htmlFor="attach-case-search">
        {label}
      </Label>
      <Input
        className="h-9 bg-background/70"
        disabled={disabled}
        id="attach-case-search"
        placeholder="Case ID or alert name"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <div className="chat-scrollbar max-h-44 space-y-0.5 overflow-y-auto rounded-md bg-transparent py-1">
        {loading ? <CaseAttachListSkeleton /> : null}
        {error ? (
          <p className="px-2 py-2 text-xs text-destructive">{error}</p>
        ) : null}
        {!loading && !error && items.length === 0 ? (
          <div className="px-1 py-1">
            <EmptyState
              action={{ label: "Browse all cases", to: "/cases" }}
              description={attachEmptyState.description}
              size="sm"
              title={attachEmptyState.title}
            />
          </div>
        ) : null}
        {!loading && !error
          ? items.map((item) => (
              <button
                key={item.case_id}
                className={cn(
                  "w-full rounded-md px-2 py-1.5 text-left transition-colors",
                  "hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
                  "disabled:cursor-not-allowed disabled:opacity-50",
                  attachedCaseId === item.case_id && "bg-sidebar-accent",
                )}
                disabled={disabled}
                type="button"
                onClick={() => onAttachCase(item)}
              >
                <div className="truncate text-sm font-medium">
                  {item.search_name || item.case_id}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {item.case_id}
                  {item.processed_at ? ` · ${item.processed_at}` : ""}
                </div>
              </button>
            ))
          : null}
        {!loading && !error && hasMore ? (
          <Button
            className="mt-1 h-8 w-full text-xs"
            disabled={disabled || loadingMore}
            type="button"
            variant="ghost"
            onClick={() => {
              void handleLoadMore();
            }}
          >
            {loadingMore ? "Loading more..." : "Load more cases"}
          </Button>
        ) : null}
      </div>
      {!loading && !error && items.length > 0 ? (
        <p className="px-1 text-xs text-muted-foreground">
          Showing {items.length} case{items.length === 1 ? "" : "s"}
          {hasMore ? ". More available." : "."}
        </p>
      ) : null}
    </div>
  );
}
