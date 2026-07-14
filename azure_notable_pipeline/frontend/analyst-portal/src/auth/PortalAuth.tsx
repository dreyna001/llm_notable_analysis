import {
  BrowserCacheLocation,
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
} from "@azure/msal-browser";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  clearPortalAuthToken,
  setPortalTokenProvider,
} from "../api/client";
import { clearChatSessionStore } from "../utils/chatSessionStore";
import { Button } from "../components/ui/button";

type AuthConfig = {
  clientId: string;
  authority: string;
  apiScope: string;
};

type AuthContextValue = {
  account: AccountInfo;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function authConfig(): AuthConfig | null {
  const clientId = String(import.meta.env.VITE_PORTAL_OIDC_CLIENT_ID ?? "").trim();
  const authority = String(import.meta.env.VITE_PORTAL_OIDC_AUTHORITY ?? "").trim();
  const apiScope = String(import.meta.env.VITE_PORTAL_OIDC_API_SCOPE ?? "").trim();
  return clientId && authority && apiScope ? { clientId, authority, apiScope } : null;
}

function clearPortalBrowserState(): void {
  clearPortalAuthToken();
  clearChatSessionStore();
}

export function PortalAuthBoundary({ children }: { children: ReactNode }) {
  const config = useMemo(authConfig, []);
  const [client] = useState(() =>
    config
      ? new PublicClientApplication({
          auth: {
            clientId: config.clientId,
            authority: config.authority,
            redirectUri: window.location.origin,
            postLogoutRedirectUri: window.location.origin,
          },
          cache: {
            cacheLocation: BrowserCacheLocation.SessionStorage,
            storeAuthStateInCookie: false,
          },
        })
      : null,
  );
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client || !config) {
      setReady(true);
      return;
    }
    let cancelled = false;
    void client
      .initialize()
      .then(() => client.handleRedirectPromise())
      .then((result) => {
        const selected = result?.account ?? client.getActiveAccount() ?? client.getAllAccounts()[0] ?? null;
        if (selected) client.setActiveAccount(selected);
        if (!cancelled) setAccount(selected);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Authentication failed.");
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [client, config]);

  useEffect(() => {
    if (!client || !config || !account) {
      setPortalTokenProvider(null);
      return;
    }
    setPortalTokenProvider(async () => {
      try {
        const result = await client.acquireTokenSilent({
          account,
          scopes: [config.apiScope],
        });
        return result.accessToken;
      } catch (reason) {
        if (reason instanceof InteractionRequiredAuthError) {
          await client.acquireTokenRedirect({
            account,
            scopes: [config.apiScope],
          });
        }
        throw reason;
      }
    });
    return () => setPortalTokenProvider(null);
  }, [account, client, config]);

  const login = useCallback(async () => {
    if (!client || !config) return;
    setError(null);
    await client.loginRedirect({ scopes: [config.apiScope] });
  }, [client, config]);

  const logout = useCallback(async () => {
    clearPortalBrowserState();
    setPortalTokenProvider(null);
    if (client) {
      await client.logoutRedirect({ account: account ?? undefined });
    }
  }, [account, client]);

  if (!ready) {
    return <main className="grid min-h-screen place-items-center">Signing you in…</main>;
  }
  if (!config) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <div className="max-w-lg rounded-lg border bg-card p-6">
          <h1 className="text-lg font-semibold">Portal authentication is not configured</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Set the OIDC client ID, authority, and delegated API scope when building this portal.
          </p>
        </div>
      </main>
    );
  }
  if (!account) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <div className="w-full max-w-md rounded-lg border bg-card p-8 text-center shadow-sm">
          <h1 className="text-xl font-semibold">Alert Analysis Portal</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Sign in with your organization account to access analyst cases.
          </p>
          {error ? <p role="alert" className="mt-4 text-sm text-destructive">{error}</p> : null}
          <Button className="mt-6" onClick={() => void login()}>Sign in</Button>
        </div>
      </main>
    );
  }

  return (
    <AuthContext.Provider value={{ account, logout }}>
      <div className="fixed right-4 top-3 z-50 flex items-center gap-2 rounded-md border bg-background/95 px-3 py-2 text-xs shadow-sm">
        <span className="max-w-48 truncate text-muted-foreground">
          {account.name ?? account.username}
        </span>
        <Button size="sm" variant="outline" onClick={() => void logout()}>Sign out</Button>
      </div>
      {children}
    </AuthContext.Provider>
  );
}

export function usePortalAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("usePortalAuth must be used inside PortalAuthBoundary");
  return context;
}
