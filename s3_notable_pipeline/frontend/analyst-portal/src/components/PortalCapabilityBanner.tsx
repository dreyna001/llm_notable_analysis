import type { PortalCapabilities } from "../types";
import { resolveChatUnavailableReason } from "../utils/chatDependencyStatus";

type PortalCapabilityBannerProps = {
  capabilities: PortalCapabilities | null;
  capabilitiesLoaded: boolean;
  capabilitiesLoadError?: string | null;
  attachError?: string | null;
  historyLoadError?: string | null;
  sessionCapNotice?: string | null;
  chatDisabledReason?: string;
};

function buildNotices(
  capabilities: PortalCapabilities | null,
  capabilitiesLoaded: boolean,
  capabilitiesLoadError: string | null | undefined,
  attachError: string | null | undefined,
  historyLoadError: string | null | undefined,
  sessionCapNotice: string | null | undefined,
  chatDisabledReason?: string,
): string[] {
  const notices: string[] = [];

  if (!capabilitiesLoaded && !capabilitiesLoadError) {
    notices.push("Checking portal capabilities…");
    return notices;
  }

  if (capabilitiesLoadError) {
    notices.push(capabilitiesLoadError);
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
  } else if (
    capabilities?.case_qa_enabled &&
    !capabilities.chat_ready
  ) {
    notices.push(resolveChatUnavailableReason(capabilities));
  } else if (chatDisabledReason) {
    notices.push(chatDisabledReason);
  }

  if (capabilities && !capabilities.chat_history_enabled) {
    notices.push(
      "Chat history is not saved on the server or in this browser. Conversations are kept only for this page session.",
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
  capabilitiesLoadError = null,
  attachError,
  historyLoadError,
  sessionCapNotice,
  chatDisabledReason,
}: PortalCapabilityBannerProps) {
  const notices = buildNotices(
    capabilities,
    capabilitiesLoaded,
    capabilitiesLoadError,
    attachError,
    historyLoadError,
    sessionCapNotice,
    chatDisabledReason,
  );
  if (!notices.length) {
    return null;
  }

  const isBlocking = Boolean(
    capabilitiesLoadError ||
      !capabilitiesLoaded ||
      (capabilities && !capabilities.case_qa_enabled) ||
      (capabilities?.case_qa_enabled && !capabilities.chat_ready) ||
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
