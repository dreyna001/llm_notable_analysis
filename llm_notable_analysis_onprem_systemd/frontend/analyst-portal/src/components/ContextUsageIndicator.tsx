import { useEffect, useId, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import type { ChatContextUsage } from "../types";
import {
  SEGMENT_COLORS,
  adjustContextUsageForDraft,
  formatTokenCount,
} from "../utils/contextUsage";

type ContextUsageIndicatorProps = {
  usage: ChatContextUsage | null;
  draftQuestion?: string;
  disabled?: boolean;
};

const RING_SIZE = 18;
const RING_STROKE = 2;
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

function ringStrokeClass(utilizationPct: number): string {
  if (utilizationPct >= 95) {
    return "stroke-destructive";
  }
  if (utilizationPct >= 80) {
    return "stroke-amber-400";
  }
  return "stroke-primary";
}

export function ContextUsageIndicator({
  usage,
  draftQuestion = "",
  disabled = false,
}: ContextUsageIndicatorProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  const displayUsage =
    usage && draftQuestion.trim()
      ? adjustContextUsageForDraft(usage, draftQuestion)
      : usage;

  useEffect(() => {
    if (!open) {
      return;
    }
    function handlePointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open]);

  if (!displayUsage) {
    return (
      <div
        aria-hidden="true"
        className="size-[18px] shrink-0 rounded-full border border-border/60"
      />
    );
  }

  const utilization = Math.min(
    100,
    Math.max(0, displayUsage.utilization_pct),
  );
  const dashOffset =
    RING_CIRCUMFERENCE - (utilization / 100) * RING_CIRCUMFERENCE;
  const contextLimitTokens = Math.max(displayUsage.context_limit_tokens, 1);

  return (
    <div className="relative shrink-0" ref={rootRef}>
      <button
        aria-controls={panelId}
        aria-expanded={open}
        aria-label={`Context usage ${utilization}% full`}
        className={cn(
          "flex size-[18px] items-center justify-center rounded-full",
          disabled && "cursor-not-allowed opacity-50",
        )}
        disabled={disabled}
        type="button"
        onClick={() => setOpen((value) => !value)}
      >
        <svg
          aria-hidden="true"
          className="size-[18px] -rotate-90"
          viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}
        >
          <circle
            className="stroke-border/80"
            cx={RING_SIZE / 2}
            cy={RING_SIZE / 2}
            fill="none"
            r={RING_RADIUS}
            strokeWidth={RING_STROKE}
          />
          <circle
            className={ringStrokeClass(utilization)}
            cx={RING_SIZE / 2}
            cy={RING_SIZE / 2}
            fill="none"
            r={RING_RADIUS}
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            strokeWidth={RING_STROKE}
          />
        </svg>
      </button>

      {open ? (
        <div
          className="absolute bottom-full right-0 z-50 mb-2 w-72 rounded-lg border border-border bg-popover p-3 text-popover-foreground shadow-lg"
          id={panelId}
          role="dialog"
        >
          <div className="mb-3 flex items-start justify-between gap-3">
            <p className="text-sm font-medium">Context usage</p>
            <button
              className="text-xs text-muted-foreground hover:text-foreground"
              type="button"
              onClick={() => setOpen(false)}
            >
              Close
            </button>
          </div>
          <div className="mb-2 flex items-baseline justify-between gap-3 text-xs">
            <span className="font-medium">{utilization}% full</span>
            <span className="text-muted-foreground">
              ~{formatTokenCount(displayUsage.prompt_tokens)} /{" "}
              {formatTokenCount(displayUsage.context_limit_tokens)} tokens
            </span>
          </div>
          <div className="mb-3 flex h-1.5 overflow-hidden rounded-full bg-muted">
            {displayUsage.segments.map((segment) => {
              const widthPct =
                (segment.tokens / contextLimitTokens) * 100;
              if (widthPct <= 0) {
                return null;
              }
              return (
                <div
                  className={cn(
                    "h-full",
                    SEGMENT_COLORS[segment.id] ?? "bg-muted-foreground/50",
                  )}
                  key={segment.id}
                  style={{ width: `${widthPct}%` }}
                  title={segment.label}
                />
              );
            })}
          </div>
          <ul className="space-y-1.5">
            {displayUsage.segments.map((segment) => (
              <li
                className="flex items-center justify-between gap-3 text-xs"
                key={segment.id}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={cn(
                      "size-2 shrink-0 rounded-sm",
                      SEGMENT_COLORS[segment.id] ?? "bg-muted-foreground/50",
                    )}
                  />
                  <span className="truncate text-muted-foreground">
                    {segment.label}
                  </span>
                </span>
                <span className="shrink-0 tabular-nums">
                  {formatTokenCount(segment.tokens)}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] text-muted-foreground">
            {displayUsage.estimate_method === "tiktoken"
              ? "Estimated with tiktoken for the configured chat model."
              : `Estimated from prompt size (chars / ${displayUsage.chars_per_token_estimate}).`}{" "}
            Actual model usage may differ slightly.
          </p>
        </div>
      ) : null}
    </div>
  );
}
