/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PORTAL_API_BASE_URL?: string;
  readonly VITE_PORTAL_OIDC_CLIENT_ID?: string;
  readonly VITE_PORTAL_OIDC_AUTHORITY?: string;
  readonly VITE_PORTAL_OIDC_API_SCOPE?: string;
}
