import { FolderOpen, MessageSquare } from "lucide-react";
import { type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";

export function PortalNavHeader() {
  return (
    <div className="shrink-0 px-3 py-3">
      <Link
        className="block px-2 text-sm font-semibold tracking-tight text-sidebar-foreground"
        to="/"
      >
        Alert Analysis Portal
      </Link>
      <nav aria-label="Primary" className="mt-3 flex flex-col gap-1">
        <NavLink
          className={({ isActive }) =>
            cn(
              "rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
              isActive &&
                "bg-sidebar-accent text-sidebar-accent-foreground",
            )
          }
          end
          to="/"
        >
          <span className="inline-flex items-center gap-1">
            <MessageSquare className="size-3" />
            AI Case Assistant
          </span>
        </NavLink>
        <NavLink
          className={({ isActive }) =>
            cn(
              "rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
              isActive &&
                "bg-sidebar-accent text-sidebar-accent-foreground",
            )
          }
          to="/cases"
        >
          <span className="inline-flex items-center gap-1">
            <FolderOpen className="size-3" />
            Cases
          </span>
        </NavLink>
      </nav>
    </div>
  );
}

type PortalNavSidebarProps = {
  footer?: ReactNode;
};

export function PortalNavSidebar({ footer }: PortalNavSidebarProps) {
  return (
    <aside
      aria-label="Portal navigation"
      className="flex h-full w-[260px] shrink-0 flex-col overflow-hidden border-r border-sidebar-border bg-sidebar text-sidebar-foreground"
    >
      <PortalNavHeader />
      {footer ? (
        <>
          <div className="min-h-0 flex-1" />
          <div className="shrink-0 px-4 py-3 text-xs text-muted-foreground">
            {footer}
          </div>
        </>
      ) : null}
    </aside>
  );
}
