export type PortalAuthMode = "manual" | "entra" | "none";

export type EntraAuthConfig = {
  tenantId: string;
  clientId: string;
  apiScope: string;
  redirectUri: string;
  silentRedirectUri: string;
  postLogoutRedirectUri: string;
  authority: string;
};

export type PortalAuthBuildConfig = {
  mode: PortalAuthMode;
  entra: EntraAuthConfig | null;
};

const PORTAL_AUTH_MODES: PortalAuthMode[] = ["manual", "entra", "none"];
const GUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CLIENT_ID_PATTERN = GUID_PATTERN;
const MAX_SCOPE_LENGTH = 512;

type EnvSource = Record<string, string | boolean | undefined>;

function readEnvString(source: EnvSource, key: string): string {
  const raw = source[key];
  if (typeof raw !== "string") {
    return "";
  }
  return raw.trim();
}

export function parsePortalAuthMode(raw: string | undefined): PortalAuthMode {
  const normalized = (raw?.trim() || "manual").toLowerCase();
  if (!PORTAL_AUTH_MODES.includes(normalized as PortalAuthMode)) {
    throw new Error(
      `VITE_PORTAL_AUTH_MODE must be one of: ${PORTAL_AUTH_MODES.join(", ")}.`,
    );
  }
  return normalized as PortalAuthMode;
}

function assertGuid(value: string, label: string): void {
  if (!GUID_PATTERN.test(value)) {
    throw new Error(`${label} must be a valid GUID.`);
  }
}

function assertClientId(value: string, label: string): void {
  if (!CLIENT_ID_PATTERN.test(value)) {
    throw new Error(`${label} must be a valid application (client) ID GUID.`);
  }
}

function assertTenantId(value: string): void {
  if (!value) {
    throw new Error("VITE_PORTAL_ENTRA_TENANT_ID is required when auth mode is entra.");
  }
  assertGuid(value, "VITE_PORTAL_ENTRA_TENANT_ID");
}

function assertNonEmpty(value: string, label: string): void {
  if (!value) {
    throw new Error(`${label} is required when auth mode is entra.`);
  }
}

function assertRedirectUrl(value: string, label: string, required: boolean): void {
  if (!value && !required) return;
  assertNonEmpty(value, label);
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${label} must be an absolute URL.`);
  }
  const isLoopback =
    parsed.hostname === "localhost" ||
    parsed.hostname === "127.0.0.1" ||
    parsed.hostname === "[::1]";
  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && isLoopback)) {
    throw new Error(`${label} must use HTTPS, except for local development.`);
  }
}

function assertApiScope(value: string): void {
  assertNonEmpty(value, "VITE_PORTAL_ENTRA_API_SCOPE");
  if (value.length > MAX_SCOPE_LENGTH || /\s/.test(value)) {
    throw new Error(
      "VITE_PORTAL_ENTRA_API_SCOPE must be a single scope without whitespace.",
    );
  }
}

function entraAuthority(tenantId: string): string {
  return `https://login.microsoftonline.com/${tenantId}`;
}

export function validatePortalAuthBuildConfig(
  source: EnvSource,
): PortalAuthBuildConfig {
  const mode = parsePortalAuthMode(readEnvString(source, "VITE_PORTAL_AUTH_MODE"));

  if (mode !== "entra") {
    const tenantId = readEnvString(source, "VITE_PORTAL_ENTRA_TENANT_ID");
    const clientId = readEnvString(source, "VITE_PORTAL_ENTRA_CLIENT_ID");
    const apiScope = readEnvString(source, "VITE_PORTAL_ENTRA_API_SCOPE");
    const redirectUri = readEnvString(source, "VITE_PORTAL_ENTRA_REDIRECT_URI");
    const postLogoutUri = readEnvString(
      source,
      "VITE_PORTAL_ENTRA_POST_LOGOUT_URI",
    );
    if (tenantId || clientId || apiScope || redirectUri || postLogoutUri) {
      throw new Error(
        "Entra build variables are only valid when VITE_PORTAL_AUTH_MODE=entra.",
      );
    }
    return { mode, entra: null };
  }

  const tenantId = readEnvString(source, "VITE_PORTAL_ENTRA_TENANT_ID");
  const clientId = readEnvString(source, "VITE_PORTAL_ENTRA_CLIENT_ID");
  const apiScope = readEnvString(source, "VITE_PORTAL_ENTRA_API_SCOPE");
  const redirectUri = readEnvString(source, "VITE_PORTAL_ENTRA_REDIRECT_URI");
  const postLogoutRedirectUri =
    readEnvString(source, "VITE_PORTAL_ENTRA_POST_LOGOUT_URI") ||
    redirectUri;

  assertTenantId(tenantId);
  assertNonEmpty(clientId, "VITE_PORTAL_ENTRA_CLIENT_ID");
  assertClientId(clientId, "VITE_PORTAL_ENTRA_CLIENT_ID");
  assertApiScope(apiScope);
  assertRedirectUrl(
    redirectUri,
    "VITE_PORTAL_ENTRA_REDIRECT_URI",
    true,
  );
  assertRedirectUrl(
    readEnvString(source, "VITE_PORTAL_ENTRA_POST_LOGOUT_URI"),
    "VITE_PORTAL_ENTRA_POST_LOGOUT_URI",
    false,
  );

  return {
    mode,
    entra: {
      tenantId,
      clientId,
      apiScope,
      redirectUri,
      silentRedirectUri: new URL("/auth/silent.html", redirectUri).toString(),
      postLogoutRedirectUri,
      authority: entraAuthority(tenantId),
    },
  };
}

let cachedBuildConfig: PortalAuthBuildConfig | null = null;

export function resetPortalAuthBuildConfigCache(): void {
  cachedBuildConfig = null;
}

export function portalAuthBuildConfig(): PortalAuthBuildConfig {
  if (!cachedBuildConfig) {
    cachedBuildConfig = validatePortalAuthBuildConfig(import.meta.env);
  }
  return cachedBuildConfig;
}

export function portalAuthMode(): PortalAuthMode {
  return portalAuthBuildConfig().mode;
}

export function portalEntraConfig(): EntraAuthConfig | null {
  return portalAuthBuildConfig().entra;
}
