import { Outlet } from "react-router-dom";
import { PortalNavSidebar } from "./PortalNavSidebar";

/**
 * Cases-route shell: nav sidebar aligned with Home, scrollable main pane.
 */
export function AppLayout() {
  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <PortalNavSidebar />
      <main className="chat-scrollbar min-h-0 min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-6xl px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
