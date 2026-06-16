import { ExternalLink, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import type { CaseSummary } from "../types";
import { CaseAttachMetaSkeleton } from "./LoadingSkeletons";
import { CaseAttachPicker } from "./CaseAttachPicker";

type ChatAssistantControlsProps = {
  selectedCaseId?: string;
  selectedCaseName?: string;
  selectedCaseProcessedAt?: string;
  selectedCaseLoading?: boolean;
  caseAttachEnabled?: boolean;
  onAttachCase?: (caseSummary: CaseSummary) => void;
  onClearSelectedCase?: () => void;
};

export function ChatAssistantControls({
  selectedCaseId,
  selectedCaseName,
  selectedCaseProcessedAt,
  selectedCaseLoading = false,
  caseAttachEnabled = true,
  onAttachCase,
  onClearSelectedCase,
}: ChatAssistantControlsProps) {
  return (
    <div className="space-y-4">
      <div className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        AI Case Assistant
      </div>

      <div className="px-1">
        <div className="text-xs text-muted-foreground">Mode</div>
        <div className="mt-0.5 text-sm font-medium text-sidebar-foreground">
          Selected case + knowledge base
        </div>
      </div>

      {selectedCaseId ? (
        <div className="px-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">Case attached</div>
              <div className="mt-0.5 truncate text-sm font-medium text-sidebar-foreground">
                {selectedCaseName || selectedCaseId}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {selectedCaseLoading ? (
                  <CaseAttachMetaSkeleton />
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
                className="h-7 w-7 shrink-0"
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

      {caseAttachEnabled && onAttachCase ? (
        <CaseAttachPicker
          attachedCaseId={selectedCaseId}
          label={selectedCaseId ? "Change case" : "Attach case"}
          onAttachCase={onAttachCase}
        />
      ) : null}
    </div>
  );
}
