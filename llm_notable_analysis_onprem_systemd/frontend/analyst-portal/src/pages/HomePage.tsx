import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchCase, fetchHealth } from "../api/client";
import { HomeChatWorkspace } from "../components/HomeChatWorkspace";
import type { CaseDetail } from "../types";

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
  const selectedCaseId = searchParams.get("case_id")?.trim() || undefined;

  useEffect(() => {
    let cancelled = false;
    fetchHealth()
      .then((payload) => {
        if (
          !cancelled &&
          typeof payload.case_retention_days === "number" &&
          payload.case_retention_days > 0
        ) {
          setCaseRetentionDays(payload.case_retention_days);
        }
      })
      .catch(() => {
        // Keep the default case window when health is unavailable.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedCaseId) {
      setSelectedCase(null);
      setSelectedCaseLoading(false);
      return;
    }
    let cancelled = false;
    setSelectedCaseLoading(true);
    fetchCase(selectedCaseId)
      .then((payload) => {
        if (!cancelled) {
          setSelectedCase(payload);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSelectedCase(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setSelectedCaseLoading(false);
        }
      });
    return () => {
      cancelled = true;
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
        onClearSelectedCase={() => setSearchParams({})}
      />
    </div>
  );
}
