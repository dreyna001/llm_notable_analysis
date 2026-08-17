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
  setPortalAuthErrorHandler,
  setPortalTokenProvider,
  type PortalAuthErrorKind,
} from "../api/client";
import { Button } from "../components/ui/button";
import { clearChatSessionStore } from "../utils/chatSessionStore";
import { portalAuthMode, portalEntraConfig } from "./authConfig";

type AuthContextValue = {
  account: AccountInfo;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function clearPortalBrowserState(): void {
  clearPortalAuthToken();
  clearChatSessionStore();
}

function AuthLoadingScreen() {
  return (
    <main className="grid min-h-screen place-items-center bg-background">
      <p className="text-sm text-muted-foreground">Signing you in...</p>
    </main>
  );
}

function AuthSignInScreen({
  error,
  onSignIn,
}: {
  error: string | null;
  onSignIn: () => void;
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <div className="w-full max-w-md rounded-lg border bg-card p-8 text-center shadow-sm">
        <h1 className="text-xl font-semibold tracking-tight">
          Alert Analysis Portal
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Sign in with your organization account to access analyst cases.
        </p>
        {error ? (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <Button className="mt-6" onClick={onSignIn}>
          Sign in
        </Button>
      </div>
    </main>
  );
}

function AuthForbiddenScreen({ onSignOut }: { onSignOut?: () => void }) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <div className="w-full max-w-lg rounded-lg border bg-card p-8 text-center shadow-sm">
        <h1 className="text-xl font-semibold tracking-tight">Access denied</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Your account is signed in but does not have analyst portal access.
          Contact your operator to request the required role.
        </p>
        {onSignOut ? (
          <Button className="mt-6" variant="outline" onClick={onSignOut}>
            Sign out
          </Button>
        ) : null}
      </div>
    </main>
  );
}

function AuthUnauthorizedScreen({
  message,
  onSignIn,
  onSignOut,
}: {
  message: string;
  onSignIn?: () => void;
  onSignOut?: () => void;
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <div className="w-full max-w-lg rounded-lg border bg-card p-8 text-center shadow-sm">
        <h1 className="text-xl font-semibold tracking-tight">
          Authentication required
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">{message}</p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
          {onSignIn ? (
            <Button onClick={onSignIn}>Sign in again</Button>
          ) : null}
          {onSignOut ? (
            <Button variant="outline" onClick={onSignOut}>
              Sign out
            </Button>
          ) : null}
        </div>
      </div>
    </main>
  );
}

function EntraAuthBoundary({ children }: { children: ReactNode }) {
  const entraConfig = portalEntraConfig();
  const [client] = useState(
    () =>
      entraConfig
        ? new PublicClientApplication({
            auth: {
              clientId: entraConfig.clientId,
              authority: entraConfig.authority,
              redirectUri: entraConfig.redirectUri,
              postLogoutRedirectUri: entraConfig.postLogoutRedirectUri,
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
  const [tokenProviderReady, setTokenProviderReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authError, setAuthError] = useState<PortalAuthErrorKind | null>(null);

  useEffect(() => {
    if (!client || !entraConfig) {
      setReady(true);
      return;
    }
    let cancelled = false;
    void client
      .initialize()
      .then(() => client.handleRedirectPromise())
      .then((result) => {
        const selected =
          result?.account ??
          client.getActiveAccount() ??
          client.getAllAccounts()[0] ??
          null;
        if (selected) {
          client.setActiveAccount(selected);
        }
        if (!cancelled) {
          setAccount(selected);
          setAuthError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error ? reason.message : "Authentication failed.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client, entraConfig]);

  useEffect(() => {
    setPortalAuthErrorHandler((kind) => {
      setAuthError(kind);
    });
    return () => setPortalAuthErrorHandler(null);
  }, []);

  useEffect(() => {
    if (!client || !entraConfig || !account) {
      setPortalTokenProvider(null);
      setTokenProviderReady(false);
      return;
    }
    setPortalTokenProvider(async () => {
      try {
        const result = await client.acquireTokenSilent({
          account,
          scopes: [entraConfig.apiScope],
          redirectUri: entraConfig.silentRedirectUri,
        });
        return result.accessToken;
      } catch (reason) {
        if (reason instanceof InteractionRequiredAuthError) {
          await client.acquireTokenRedirect({
            account,
            scopes: [entraConfig.apiScope],
          });
        }
        throw reason;
      }
    });
    setTokenProviderReady(true);
    return () => setPortalTokenProvider(null);
  }, [account, client, entraConfig]);

  const login = useCallback(async () => {
    if (!client || !entraConfig) {
      return;
    }
    setError(null);
    setAuthError(null);
    await client.loginRedirect({ scopes: [entraConfig.apiScope] });
  }, [client, entraConfig]);

  const logout = useCallback(async () => {
    clearPortalBrowserState();
    setPortalTokenProvider(null);
    setAuthError(null);
    setAccount(null);
    if (client) {
      await client.logoutRedirect({ account: account ?? undefined });
    }
  }, [account, client]);

  if (!entraConfig) {
    return (
      <main className="grid min-h-screen place-items-center bg-background p-6">
        <div className="max-w-lg rounded-lg border bg-card p-6">
          <h1 className="text-lg font-semibold tracking-tight">
            Portal authentication is not configured
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Entra build settings are missing. Rebuild the portal with tenant ID,
            SPA client ID, and API scope.
          </p>
        </div>
      </main>
    );
  }

  if (!ready || (account && !tokenProviderReady)) {
    return <AuthLoadingScreen />;
  }

  if (authError === "forbidden") {
    return <AuthForbiddenScreen onSignOut={() => void logout()} />;
  }

  if (authError === "unauthorized") {
    return (
      <AuthUnauthorizedScreen
        message="Your session expired or is no longer valid. Sign in again to continue."
        onSignIn={() => void login()}
        onSignOut={() => void logout()}
      />
    );
  }

  if (!account) {
    return <AuthSignInScreen error={error} onSignIn={() => void login()} />;
  }

  return (
    <AuthContext.Provider value={{ account, logout }}>
      <div className="fixed right-4 top-3 z-50 flex items-center gap-2 rounded-md border bg-background/95 px-3 py-2 text-xs shadow-sm">
        <span className="max-w-48 truncate text-muted-foreground">
          {account.name ?? account.username}
        </span>
        <Button size="sm" variant="outline" onClick={() => void logout()}>
          Sign out
        </Button>
      </div>
      {children}
    </AuthContext.Provider>
  );
}

function ManualAuthBoundary({ children }: { children: ReactNode }) {
  const [authError, setAuthError] = useState<PortalAuthErrorKind | null>(null);

  useEffect(() => {
    setPortalAuthErrorHandler((kind) => {
      setAuthError(kind);
    });
    return () => setPortalAuthErrorHandler(null);
  }, []);

  if (authError === "forbidden") {
    return <AuthForbiddenScreen />;
  }

  if (authError === "unauthorized") {
    return (
      <AuthUnauthorizedScreen message="Provide a valid analyst portal bearer token, then reload the page." />
    );
  }

  return children;
}

function NoneAuthBoundary({ children }: { children: ReactNode }) {
  const [authError, setAuthError] = useState<PortalAuthErrorKind | null>(null);

  useEffect(() => {
    setPortalAuthErrorHandler((kind) => {
      setAuthError(kind);
    });
    return () => setPortalAuthErrorHandler(null);
  }, []);

  if (authError === "forbidden") {
    return <AuthForbiddenScreen />;
  }

  if (authError === "unauthorized") {
    return (
      <AuthUnauthorizedScreen message="This portal requires authentication before API access." />
    );
  }

  return children;
}

export function PortalAuthBoundary({ children }: { children: ReactNode }) {
  const mode = useMemo(() => portalAuthMode(), []);

  if (mode === "entra") {
    return <EntraAuthBoundary>{children}</EntraAuthBoundary>;
  }
  if (mode === "none") {
    return <NoneAuthBoundary>{children}</NoneAuthBoundary>;
  }
  return <ManualAuthBoundary>{children}</ManualAuthBoundary>;
}

export function usePortalAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("usePortalAuth must be used inside an Entra auth session.");
  }
  return context;
}
