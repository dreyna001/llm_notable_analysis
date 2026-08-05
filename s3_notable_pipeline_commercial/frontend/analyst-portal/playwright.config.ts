import { defineConfig, devices } from "@playwright/test";
import { portalEnv } from "./e2e/portal-env";

const env = portalEnv();

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"]],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: env.baseURL,
    ignoreHTTPSErrors: true,
    httpCredentials:
      env.authMode === "basic"
        ? { username: env.user, password: env.password }
        : undefined,
    extraHTTPHeaders:
      env.authMode === "jwt" ? { Authorization: `Bearer ${env.jwt}` } : undefined,
    trace: env.authMode === "jwt" ? "off" : "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
