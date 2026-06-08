import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchCase, isCancelledRequest } from "../api/client";
import { HomeChatWorkspace } from "../components/HomeChatWorkspace";
import type { CaseDetail, PortalCapabilities } from "../types";

function asText(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "";
}

function alertName(detail: CaseDetail | null): string | undefined {
  if (!detail) return undefined;
  const payload = detail.alert_payload;
  return (
    asText(payload.search_name) ||
    asText(payload.searchName) ||
    asText(payload.rule_name) ||
    asText(payload.rule) ||
    asText(payload.signature) ||
    asText(payload.title) ||
    undefined
  );
}

export function HomePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [caseRetentionDays, setCaseRetentionDays] = useState<number>(30);
  const [selectedCase, setSelectedCase] = useState<CaseDetail | null>(null);
  const [selectedCaseLoading, setSelectedCaseLoading] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const selectedCaseId = searchParams.get("case_id")?.trim() || undefined;

  const handleAttachCase = useCallback(
    (caseId: string) => {
      setAttachError(null);
      setSearchParams({ case_id: caseId });
    },
    [setSearchParams],
  );

  const handleClearSelectedCase = useCallback(() => {
    setAttachError(null);
    setSelectedCase(null);
    setSelectedCaseLoading(false);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("case_id");
        return next;
      },
      { replace: true },
    );
  }, [setSearchParams]);

  const handleCapabilitiesLoaded = useCallback((payload: PortalCapabilities) => {
    if (
      typeof payload.case_retention_days === "number" &&
      payload.case_retention_days > 0
    ) {
      setCaseRetentionDays(payload.case_retention_days);
    }
  }, []);

  useEffect(() => {
    if (!selectedCaseId) {
      setSelectedCase(null);
      setSelectedCaseLoading(false);
      setAttachError(null);
      return;
    }
    const controller = new AbortController();
    const { signal } = controller;
    setSelectedCaseLoading(true);
    setAttachError(null);
    fetchCase(selectedCaseId, { signal })
      .then((payload) => {
        if (signal.aborted) {
          return;
        }
        setSelectedCase(payload);
      })
      .catch((err: unknown) => {
        if (isCancelledRequest(err, signal)) {
          return;
        }
        setSelectedCase(null);
        setAttachError("Case not found or unavailable.");
      })
      .finally(() => {
        if (!signal.aborted) {
          setSelectedCaseLoading(false);
        }
      });
    return () => {
      controller.abort();
    };
  }, [selectedCaseId]);

  const sidebarMeta = (
    <div>
      <div className="text-muted-foreground">Case window</div>
      <div className="mt-0.5 text-sm font-medium text-foreground">
        {caseRetentionDays}d
      </div>
      <div className="mt-0.5 text-muted-foreground">Operator configurable</div>
    </div>
  );

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <HomeChatWorkspace
        sidebarMeta={sidebarMeta}
        selectedCaseId={selectedCaseId}
        selectedCaseName={alertName(selectedCase)}
        selectedCaseProcessedAt={selectedCase?.metadata.processed_at ?? undefined}
        selectedCaseLoading={selectedCaseLoading}
        attachError={attachError}
        archiveNotices={selectedCase?.metadata.archive_notices}
        onAttachCase={handleAttachCase}
        onClearSelectedCase={handleClearSelectedCase}
        onCapabilitiesLoaded={handleCapabilitiesLoaded}
      />
    </div>
  );
}
