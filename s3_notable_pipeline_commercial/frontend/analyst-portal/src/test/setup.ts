import "@testing-library/jest-dom/vitest";
import { beforeEach, vi } from "vitest";
import { resetPortalAuthBuildConfigCache } from "../auth/authConfig";

vi.stubEnv("VITE_PORTAL_AUTH_MODE", "manual");

beforeEach(() => {
  resetPortalAuthBuildConfigCache();
});
