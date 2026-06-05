import { FolderOpen, MessageSquarePlus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { StoredChatSession } from "../utils/chatSessionStore";

type PortalSidebarProps = {
  sessions: StoredChatSession[];
  activeLocalId: string;
  onNewChat: () => void;
  onSelectSession: (localId: string) => void;
  onDeleteSession: (localId: string) => void;
  meta: ReactNode;
  assistantControls: ReactNode;
};

export function PortalSidebar({
  sessions,
  activeLocalId,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  meta,
  assistantControls,
}: PortalSidebarProps) {
  return (
    <aside
      aria-label="Portal navigation and chats"
      className="flex h-full w-[260px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground"
    >
      <div className="px-3 py-3">
        <Link
          className="block px-2 text-sm font-semibold tracking-tight text-sidebar-foreground"
          to="/"
        >
          Alert Analysis Portal
        </Link>
        <nav aria-label="Primary" className="mt-3 grid grid-cols-2 gap-1">
          <NavLink
            className={({ isActive }) =>
              cn(
                "rounded-lg px-2.5 py-1.5 text-center text-xs font-medium text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                isActive &&
                  "bg-sidebar-accent text-sidebar-accent-foreground",
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
                "rounded-lg px-2.5 py-1.5 text-center text-xs font-medium text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
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

      <Separator className="bg-sidebar-border" />

      <div className="px-3 py-3">{assistantControls}</div>

      <Separator className="bg-sidebar-border" />

      <div className="flex min-h-0 flex-1 flex-col px-2 py-2">
        <Button
          className="mb-2 w-full justify-start gap-2 border border-border/60 bg-transparent shadow-none hover:bg-sidebar-accent"
          type="button"
          variant="outline"
          onClick={onNewChat}
        >
          <MessageSquarePlus className="size-4" />
          New chat
        </Button>

        <div className="px-2 pb-1 text-xs font-medium text-muted-foreground">
          Chats
        </div>
        <div className="chat-scrollbar min-h-0 flex-1 space-y-0.5 overflow-y-auto">
          {sessions.map((session) => (
            <div className="group flex items-center gap-0.5" key={session.localId}>
              <button
                className={cn(
                  "min-w-0 flex-1 truncate rounded-lg px-2.5 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                  session.localId === activeLocalId &&
                    "bg-sidebar-accent text-sidebar-accent-foreground",
                )}
                type="button"
                onClick={() => onSelectSession(session.localId)}
              >
                {session.title}
              </button>
              <button
                aria-label={`Delete ${session.title}`}
                className="rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onDeleteSession(session.localId);
                }}
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {meta ? (
        <>
          <Separator className="bg-sidebar-border" />
          <div className="px-4 py-3 text-xs text-muted-foreground">{meta}</div>
        </>
      ) : null}
    </aside>
  );
}
