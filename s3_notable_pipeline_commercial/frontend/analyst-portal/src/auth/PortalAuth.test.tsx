import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchCapabilities } from "../api/client";
import { PortalAuthBoundary } from "./PortalAuth";

const mockInitialize = vi.fn(async () => undefined);
const mockHandleRedirectPromise = vi.fn(async () => null);
const mockLoginRedirect = vi.fn(async () => undefined);
const mockLogoutRedirect = vi.fn(async () => undefined);
const mockAcquireTokenSilent = vi.fn(async () => ({ accessToken: "entra-token" }));
const mockAcquireTokenRedirect = vi.fn(async () => undefined);
const mockSetActiveAccount = vi.fn();
const mockGetActiveAccount = vi.fn(() => null);
const mockGetAllAccounts = vi.fn(() => []);

const TENANT_ID = "11111111-1111-1111-1111-111111111111";
const CLIENT_ID = "22222222-2222-2222-2222-222222222222";

function FirstApiRequest() {
  useEffect(() => {
    void fetchCapabilities();
  }, []);
  return <div>Portal content</div>;
}

vi.mock("@azure/msal-browser", () => ({
  BrowserCacheLocation: { SessionStorage: "sessionStorage" },
  InteractionRequiredAuthError: class InteractionRequiredAuthError extends Error {},
  PublicClientApplication: vi.fn(function MockPublicClientApplication() {
    return {
      initialize: mockInitialize,
      handleRedirectPromise: mockHandleRedirectPromise,
      loginRedirect: mockLoginRedirect,
      logoutRedirect: mockLogoutRedirect,
      acquireTokenSilent: mockAcquireTokenSilent,
      acquireTokenRedirect: mockAcquireTokenRedirect,
      setActiveAccount: mockSetActiveAccount,
      getActiveAccount: mockGetActiveAccount,
      getAllAccounts: mockGetAllAccounts,
    };
  }),
}));

vi.mock("./authConfig", async () => {
  const actual = await vi.importActual<typeof import("./authConfig")>("./authConfig");
  return {
    ...actual,
    portalAuthMode: vi.fn(() => "manual" as const),
    portalEntraConfig: vi.fn(() => null),
  };
});

import { portalAuthMode, portalEntraConfig } from "./authConfig";

describe("PortalAuthBoundary", () => {
  beforeEach(() => {
    vi.mocked(portalAuthMode).mockReturnValue("manual");
    vi.mocked(portalEntraConfig).mockReturnValue(null);
    mockInitialize.mockClear();
    mockHandleRedirectPromise.mockClear();
    mockLoginRedirect.mockClear();
    mockLogoutRedirect.mockClear();
    mockAcquireTokenSilent.mockClear();
    mockAcquireTokenRedirect.mockClear();
    mockSetActiveAccount.mockClear();
    mockGetActiveAccount.mockReturnValue(null);
    mockGetAllAccounts.mockReturnValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders children in manual mode", () => {
    render(
      <PortalAuthBoundary>
        <div>Portal content</div>
      </PortalAuthBoundary>,
    );

    expect(screen.getByText("Portal content")).toBeInTheDocument();
  });

  it("shows sign-in UI in entra mode before an account is available", async () => {
    vi.mocked(portalAuthMode).mockReturnValue("entra");
    vi.mocked(portalEntraConfig).mockReturnValue({
      tenantId: TENANT_ID,
      clientId: CLIENT_ID,
      apiScope: "api://app/access",
      redirectUri: "https://portal.example.test/",
      silentRedirectUri: "https://portal.example.test/auth/silent.html",
      postLogoutRedirectUri: "https://portal.example.test/",
      authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    });

    render(
      <PortalAuthBoundary>
        <div>Portal content</div>
      </PortalAuthBoundary>,
    );

    expect(await screen.findByRole("heading", { name: "Alert Analysis Portal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("Portal content")).not.toBeInTheDocument();
  });

  it("starts login redirect from the sign-in screen", async () => {
    vi.mocked(portalAuthMode).mockReturnValue("entra");
    vi.mocked(portalEntraConfig).mockReturnValue({
      tenantId: TENANT_ID,
      clientId: CLIENT_ID,
      apiScope: "api://app/access",
      redirectUri: "https://portal.example.test/",
      silentRedirectUri: "https://portal.example.test/auth/silent.html",
      postLogoutRedirectUri: "https://portal.example.test/",
      authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    });

    const { container } = render(
      <PortalAuthBoundary>
        <div>Portal content</div>
      </PortalAuthBoundary>,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(mockLoginRedirect).toHaveBeenCalledWith({
      scopes: ["api://app/access"],
    });
    expect(container).toBeTruthy();
  });

  it("renders portal content after entra redirect completes", async () => {
    vi.mocked(portalAuthMode).mockReturnValue("entra");
    vi.mocked(portalEntraConfig).mockReturnValue({
      tenantId: TENANT_ID,
      clientId: CLIENT_ID,
      apiScope: "api://app/access",
      redirectUri: "https://portal.example.test/",
      silentRedirectUri: "https://portal.example.test/auth/silent.html",
      postLogoutRedirectUri: "https://portal.example.test/",
      authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    });
    mockHandleRedirectPromise.mockResolvedValue({
      account: {
        homeAccountId: "home-1",
        environment: "login.microsoftonline.com",
        tenantId: TENANT_ID,
        username: "analyst@example.test",
        localAccountId: "local-1",
        name: "Analyst User",
      },
    });

    render(
      <PortalAuthBoundary>
        <div>Portal content</div>
      </PortalAuthBoundary>,
    );

    await waitFor(() => {
      expect(screen.getByText("Portal content")).toBeInTheDocument();
    });
    expect(screen.getByText("Analyst User")).toBeInTheDocument();
    expect(mockSetActiveAccount).toHaveBeenCalled();
  });

  it("registers the entra token provider before child API effects run", async () => {
    vi.mocked(portalAuthMode).mockReturnValue("entra");
    vi.mocked(portalEntraConfig).mockReturnValue({
      tenantId: TENANT_ID,
      clientId: CLIENT_ID,
      apiScope: "api://app/access",
      redirectUri: "https://portal.example.test/",
      silentRedirectUri: "https://portal.example.test/auth/silent.html",
      postLogoutRedirectUri: "https://portal.example.test/",
      authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    });
    mockHandleRedirectPromise.mockResolvedValue({
      account: {
        homeAccountId: "home-1",
        environment: "login.microsoftonline.com",
        tenantId: TENANT_ID,
        username: "analyst@example.test",
        localAccountId: "local-1",
        name: "Analyst User",
      },
    });
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(
        JSON.stringify({
          case_qa_enabled: true,
          case_retention_days: 30,
          chat_history_enabled: true,
          chat_ready: true,
          general_knowledge_enabled: false,
          max_answer_tokens: 1000,
          max_chat_sessions_per_user: 20,
          max_question_chars: 2000,
          model_context_tokens: 32000,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <PortalAuthBoundary>
        <FirstApiRequest />
      </PortalAuthBoundary>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(request.headers).get("Authorization")).toBe(
      "Bearer entra-token",
    );
    expect(mockAcquireTokenSilent).toHaveBeenCalledWith(
      expect.objectContaining({
        redirectUri: "https://portal.example.test/auth/silent.html",
      }),
    );
  });
});
