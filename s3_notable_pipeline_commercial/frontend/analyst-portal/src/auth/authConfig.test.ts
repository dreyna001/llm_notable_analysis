import { afterEach, describe, expect, it } from "vitest";
import {
  parsePortalAuthMode,
  resetPortalAuthBuildConfigCache,
  validatePortalAuthBuildConfig,
} from "./authConfig";

const TENANT_ID = "11111111-1111-1111-1111-111111111111";
const CLIENT_ID = "22222222-2222-2222-2222-222222222222";

describe("parsePortalAuthMode", () => {
  it("defaults to manual", () => {
    expect(parsePortalAuthMode(undefined)).toBe("manual");
    expect(parsePortalAuthMode("")).toBe("manual");
  });

  it("accepts supported auth modes", () => {
    expect(parsePortalAuthMode("manual")).toBe("manual");
    expect(parsePortalAuthMode("entra")).toBe("entra");
    expect(parsePortalAuthMode("none")).toBe("none");
  });

  it("rejects unsupported auth modes", () => {
    expect(() => parsePortalAuthMode("iam")).toThrow(
      "VITE_PORTAL_AUTH_MODE must be one of",
    );
  });
});

describe("validatePortalAuthBuildConfig", () => {
  afterEach(() => {
    resetPortalAuthBuildConfigCache();
  });

  it("accepts manual mode without entra variables", () => {
    expect(
      validatePortalAuthBuildConfig({
        VITE_PORTAL_AUTH_MODE: "manual",
      }),
    ).toEqual({ mode: "manual", entra: null });
  });

  it("accepts none mode without entra variables", () => {
    expect(
      validatePortalAuthBuildConfig({
        VITE_PORTAL_AUTH_MODE: "none",
      }),
    ).toEqual({ mode: "none", entra: null });
  });

  it("rejects entra variables outside entra mode", () => {
    expect(() =>
      validatePortalAuthBuildConfig({
        VITE_PORTAL_AUTH_MODE: "manual",
        VITE_PORTAL_ENTRA_TENANT_ID: TENANT_ID,
      }),
    ).toThrow("only valid when VITE_PORTAL_AUTH_MODE=entra");

    expect(() =>
      validatePortalAuthBuildConfig({
        VITE_PORTAL_AUTH_MODE: "none",
        VITE_PORTAL_ENTRA_REDIRECT_URI: "https://portal.example.test/",
      }),
    ).toThrow("only valid when VITE_PORTAL_AUTH_MODE=entra");
  });

  it("requires entra settings in entra mode", () => {
    expect(() =>
      validatePortalAuthBuildConfig({
        VITE_PORTAL_AUTH_MODE: "entra",
      }),
    ).toThrow("VITE_PORTAL_ENTRA_TENANT_ID is required");
  });

  it("builds entra config with dedicated silent redirect URI", () => {
    const config = validatePortalAuthBuildConfig({
      VITE_PORTAL_AUTH_MODE: "entra",
      VITE_PORTAL_ENTRA_TENANT_ID: TENANT_ID,
      VITE_PORTAL_ENTRA_CLIENT_ID: CLIENT_ID,
      VITE_PORTAL_ENTRA_API_SCOPE: "api://app/access",
      VITE_PORTAL_ENTRA_REDIRECT_URI: "https://portal.example.test/",
      VITE_PORTAL_ENTRA_POST_LOGOUT_URI: "https://portal.example.test/signed-out",
    });

    expect(config.mode).toBe("entra");
    expect(config.entra).toEqual({
      tenantId: TENANT_ID,
      clientId: CLIENT_ID,
      apiScope: "api://app/access",
      redirectUri: "https://portal.example.test/",
      silentRedirectUri: "https://portal.example.test/auth/silent.html",
      postLogoutRedirectUri: "https://portal.example.test/signed-out",
      authority: `https://login.microsoftonline.com/${TENANT_ID}`,
    });
  });

  it("rejects multitenant aliases for a customer-specific deployment", () => {
    expect(() =>
      validatePortalAuthBuildConfig({
        VITE_PORTAL_AUTH_MODE: "entra",
        VITE_PORTAL_ENTRA_TENANT_ID: "organizations",
        VITE_PORTAL_ENTRA_CLIENT_ID: CLIENT_ID,
        VITE_PORTAL_ENTRA_API_SCOPE: "api://app/access",
        VITE_PORTAL_ENTRA_REDIRECT_URI: "https://portal.example.test/",
      }),
    ).toThrow("VITE_PORTAL_ENTRA_TENANT_ID must be a valid GUID");
  });

  it("requires an explicit redirect URI for entra builds", () => {
    expect(() =>
      validatePortalAuthBuildConfig({
        VITE_PORTAL_AUTH_MODE: "entra",
        VITE_PORTAL_ENTRA_TENANT_ID: TENANT_ID,
        VITE_PORTAL_ENTRA_CLIENT_ID: CLIENT_ID,
        VITE_PORTAL_ENTRA_API_SCOPE: "api://app/access",
      }),
    ).toThrow("VITE_PORTAL_ENTRA_REDIRECT_URI is required");
  });

  it("rejects insecure production redirects and malformed scopes", () => {
    expect(() =>
      validatePortalAuthBuildConfig({
        VITE_PORTAL_AUTH_MODE: "entra",
        VITE_PORTAL_ENTRA_TENANT_ID: TENANT_ID,
        VITE_PORTAL_ENTRA_CLIENT_ID: CLIENT_ID,
        VITE_PORTAL_ENTRA_API_SCOPE: "api://app/access extra",
        VITE_PORTAL_ENTRA_REDIRECT_URI: "https://portal.example.test/",
      }),
    ).toThrow("must be a single scope");

    expect(() =>
      validatePortalAuthBuildConfig({
        VITE_PORTAL_AUTH_MODE: "entra",
        VITE_PORTAL_ENTRA_TENANT_ID: TENANT_ID,
        VITE_PORTAL_ENTRA_CLIENT_ID: CLIENT_ID,
        VITE_PORTAL_ENTRA_API_SCOPE: "api://app/access",
        VITE_PORTAL_ENTRA_REDIRECT_URI: "http://portal.example.test/",
      }),
    ).toThrow("must use HTTPS");
  });
});
