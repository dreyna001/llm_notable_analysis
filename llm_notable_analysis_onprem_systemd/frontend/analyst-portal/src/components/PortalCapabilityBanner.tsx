import type { PortalCapabilities } from "../types";

type PortalCapabilityBannerProps = {
  capabilities: PortalCapabilities | null;
  capabilitiesLoaded: boolean;
  capabilitiesError: boolean;
  attachError?: string | null;
  historyLoadError?: string | null;
  sessionCapNotice?: string | null;
  chatDisabledReason?: string;
};

function buildNotices(
  capabilities: PortalCapabilities | null,
  capabilitiesLoaded: boolean,
  capabilitiesError: boolean,
  attachError: string | null | undefined,
  historyLoadError: string | null | undefined,
  sessionCapNotice: string | null | undefined,
  chatDisabledReason?: string,
): string[] {
  const notices: string[] = [];

  if (!capabilitiesLoaded && !capabilitiesError) {
    notices.push("Checking portal capabilities…");
    return notices;
  }

  if (capabilitiesError) {
    notices.push("Could not load portal capabilities.");
    return notices;
  }

  if (attachError) {
    notices.push(attachError);
  }

  if (historyLoadError) {
    notices.push(historyLoadError);
  }

  if (sessionCapNotice) {
    notices.push(sessionCapNotice);
  }

  if (capabilities && !capabilities.case_qa_enabled) {
    notices.push("Case Q&A is disabled on this portal. Chat is unavailable.");
  } else if (chatDisabledReason) {
    notices.push(chatDisabledReason);
  }

  if (
    capabilities &&
    !capabilities.global_retrieval_enabled &&
    !chatDisabledReason
  ) {
    notices.push(
      "Cross-case archive chat is off. Attach a specific case to ask questions.",
    );
  }

  if (capabilities && !capabilities.chat_history_enabled) {
    notices.push(
      "Chat history is not saved on the server. Conversations stay in this browser only.",
    );
  }

  if (capabilities && !capabilities.general_knowledge_enabled) {
    notices.push(
      "General technology fallback is off. Answers use archived case context only.",
    );
  }

  return notices;
}

export function PortalCapabilityBanner({
  capabilities,
  capabilitiesLoaded,
  capabilitiesError,
  attachError,
  historyLoadError,
  sessionCapNotice,
  chatDisabledReason,
}: PortalCapabilityBannerProps) {
  const notices = buildNotices(
    capabilities,
    capabilitiesLoaded,
    capabilitiesError,
    attachError,
    historyLoadError,
    sessionCapNotice,
    chatDisabledReason,
  );
  if (!notices.length) {
    return null;
  }

  const isBlocking = Boolean(
    capabilitiesError ||
      !capabilitiesLoaded ||
      (capabilities && !capabilities.case_qa_enabled) ||
      chatDisabledReason,
  );

  return (
    <div
      className={
        isBlocking
          ? "border-b border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-950 dark:text-amber-50"
          : "border-b border-border/60 bg-muted/40 px-4 py-2.5 text-sm text-muted-foreground"
      }
      role="status"
    >
      <ul className="mx-auto flex w-full max-w-3xl list-disc flex-col gap-1 pl-5">
        {notices.map((notice) => (
          <li key={notice}>{notice}</li>
        ))}
      </ul>
    </div>
  );
}
