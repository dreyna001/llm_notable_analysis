import { Link, NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";

export function AppLayout() {
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 border-b border-border/60 bg-background/80 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-4">
          <Link
            className="text-sm font-semibold tracking-tight text-foreground"
            to="/"
          >
            Alert Analysis Portal
          </Link>
          <nav className="flex items-center gap-1">
            <NavLink
              className={({ isActive }) =>
                cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                  isActive && "bg-accent text-foreground",
                )
              }
              end
              to="/"
            >
              Home
            </NavLink>
            <NavLink
              className={({ isActive }) =>
                cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                  isActive && "bg-accent text-foreground",
                )
              }
              to="/cases"
            >
              Cases
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
