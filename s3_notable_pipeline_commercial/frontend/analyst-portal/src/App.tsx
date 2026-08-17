import { BrowserRouter, Route, Routes } from "react-router-dom";
import { PortalAuthBoundary } from "./auth/PortalAuth";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import { AppLayout } from "./components/Layout";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { CasesPage } from "./pages/CasesPage";
import { HomePage } from "./pages/HomePage";

export function App() {
  return (
    <AppErrorBoundary>
      <PortalAuthBoundary>
        <BrowserRouter>
          <Routes>
            <Route index element={<HomePage />} />
            <Route element={<AppLayout />}>
              <Route path="cases" element={<CasesPage />} />
              <Route path="cases/:caseId" element={<CaseDetailPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PortalAuthBoundary>
    </AppErrorBoundary>
  );
}
