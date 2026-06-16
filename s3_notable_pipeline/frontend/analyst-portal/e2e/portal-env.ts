export type PortalE2EEnv = {
  baseURL: string;
  user: string;
  password: string;
  caseId: string;
  runChat: boolean;
  chatTimeoutMs: number;
};

function readBool(value: string | undefined, defaultValue: boolean): boolean {
  if (value === undefined || value.trim() === "") {
    return defaultValue;
  }
  const normalized = value.trim().toLowerCase();
  return normalized !== "0" && normalized !== "false" && normalized !== "no";
}

export function portalEnv(): PortalE2EEnv {
  return {
    baseURL: process.env.PORTAL_E2E_BASE_URL ?? "https://127.0.0.1:8443",
    user: process.env.PORTAL_E2E_USER ?? "analyst",
    password: process.env.PORTAL_E2E_PASSWORD ?? "analyst-lab-change-me",
    caseId: process.env.PORTAL_E2E_CASE_ID ?? "portal-test-1780770539",
    runChat: readBool(process.env.PORTAL_E2E_CHAT, true),
    chatTimeoutMs: Number(process.env.PORTAL_E2E_CHAT_TIMEOUT_MS ?? "180000"),
  };
}
