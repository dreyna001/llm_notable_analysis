import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { validatePortalAuthBuildConfig } from "./auth/authConfig";
import "./index.css";

validatePortalAuthBuildConfig(import.meta.env);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
