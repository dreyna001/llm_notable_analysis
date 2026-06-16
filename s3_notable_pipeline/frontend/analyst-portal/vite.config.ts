/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const portalTarget = process.env.VITE_PORTAL_API_TARGET ?? "http://127.0.0.1:8765";
const devUser = process.env.VITE_PORTAL_DEV_USER ?? "dev-preview@local";
const devProxySecret = process.env.VITE_PORTAL_DEV_PROXY_SECRET ?? "portal-secret";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["**/node_modules/**", "**/e2e/**"],
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: portalTarget,
        // Keep the browser Host (5173) so portal same-origin checks match Origin.
        changeOrigin: false,
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("X-Forwarded-User", devUser);
            proxyReq.setHeader("X-Notable-Portal-Proxy-Secret", devProxySecret);
          });
        },
      },
      "/health": { target: portalTarget, changeOrigin: true },
      "/ready": { target: portalTarget, changeOrigin: true },
    },
  },
});
