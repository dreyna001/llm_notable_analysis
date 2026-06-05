import { ExternalLink, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { ChatMode } from "../types";

const MODE_LABELS: Record<ChatMode, string> = {
  selected_case: "Selected case + knowledge base",
  global_archive: "All cases + knowledge base",
};

const MODE_HELP: Record<ChatMode, string> = {
  selected_case: "Answer using this case and the knowledge base.",
  global_archive: "Search retained cases and the knowledge base.",
};

type ChatAssistantControlsProps = {
  mode: ChatMode;
  modes: ChatMode[];
  onModeChange: (mode: ChatMode) => void;
  selectedCaseId?: string;
  selectedCaseName?: string;
  selectedCaseProcessedAt?: string;
  selectedCaseLoading?: boolean;
  onClearSelectedCase?: () => void;
};

const selectClassName = cn(
  "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm",
  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
);

export function ChatAssistantControls({
  mode,
  modes,
  onModeChange,
  selectedCaseId,
  selectedCaseName,
  selectedCaseProcessedAt,
  selectedCaseLoading = false,
  onClearSelectedCase,
}: ChatAssistantControlsProps) {
  return (
    <div className="space-y-3">
      <div className="px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        AI Case Assistant
      </div>

      {modes.length > 1 ? (
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground" htmlFor="chat-mode">
            Mode
          </Label>
          <select
            className={selectClassName}
            id="chat-mode"
            value={mode}
            onChange={(event) => onModeChange(event.target.value as ChatMode)}
          >
            {modes.map((item) => (
              <option key={item} value={item}>
                {MODE_LABELS[item]}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <div className="rounded-lg border border-border/60 bg-background/50 px-3 py-2">
          <div className="text-xs text-muted-foreground">Mode</div>
          <div className="text-sm font-medium">{MODE_LABELS[mode]}</div>
        </div>
      )}

      <p className="px-1 text-xs leading-relaxed text-muted-foreground">
        {MODE_HELP[mode]}
      </p>

      {selectedCaseId ? (
        <div className="rounded-lg border border-border/60 bg-background/50 p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">Case attached</div>
              <div className="truncate text-sm font-medium">
                {selectedCaseName || selectedCaseId}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {selectedCaseLoading ? (
                  "Loading case details..."
                ) : (
                  <>
                    <Link
                      className="inline-flex items-center gap-1 hover:text-foreground"
                      rel="noreferrer"
                      target="_blank"
                      to={`/cases/${encodeURIComponent(selectedCaseId)}`}
                    >
                      {selectedCaseId}
                      <ExternalLink className="size-3" />
                    </Link>
                    {selectedCaseProcessedAt
                      ? ` · ${selectedCaseProcessedAt}`
                      : null}
                  </>
                )}
              </div>
            </div>
            {onClearSelectedCase ? (
              <Button
                aria-label="Clear attached case"
                className="shrink-0"
                size="icon"
                type="button"
                variant="ghost"
                onClick={onClearSelectedCase}
              >
                <X className="size-4" />
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      <p className="px-1 text-xs text-muted-foreground">
        Read-only. No actions, tickets, or searches run.
      </p>
    </div>
  );
}
