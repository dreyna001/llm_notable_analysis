/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PORTAL_API_BASE_URL?: string;
  readonly VITE_PORTAL_AUTH_MODE?: string;
  readonly VITE_PORTAL_ENTRA_TENANT_ID?: string;
  readonly VITE_PORTAL_ENTRA_CLIENT_ID?: string;
  readonly VITE_PORTAL_ENTRA_API_SCOPE?: string;
  readonly VITE_PORTAL_ENTRA_REDIRECT_URI?: string;
  readonly VITE_PORTAL_ENTRA_POST_LOGOUT_URI?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
