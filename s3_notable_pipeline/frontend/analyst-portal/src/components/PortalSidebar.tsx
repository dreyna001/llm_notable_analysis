import { ChevronDown, MessageSquarePlus, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { EmptyState } from "./EmptyState";
import type { StoredChatSession } from "../utils/chatSessionStore";
import { PortalNavHeader } from "./PortalNavSidebar";

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
  const [chatsExpanded, setChatsExpanded] = useState(true);
  const hasSavedChats = sessions.some(
    (session) =>
      session.turns.length > 0 ||
      session.serverSessionId ||
      session.title !== "New chat",
  );

  return (
    <aside
      aria-label="Portal navigation and chats"
      className="flex h-full w-[260px] shrink-0 flex-col overflow-hidden border-r border-sidebar-border bg-sidebar text-sidebar-foreground"
    >
      <PortalNavHeader />

      <div className="chat-scrollbar min-h-0 flex-1 overflow-y-auto">
        <div className="px-3 pb-3 pt-1">{assistantControls}</div>

        <div className="px-2 py-1">
          <Button
            className="mb-3 w-full justify-start gap-2 border-0 bg-transparent px-2.5 shadow-none hover:bg-sidebar-accent"
            type="button"
            variant="ghost"
            onClick={onNewChat}
          >
            <MessageSquarePlus className="size-4" />
            New chat
          </Button>

          <button
            aria-expanded={chatsExpanded}
            className="flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-xs font-semibold text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
            type="button"
            onClick={() => setChatsExpanded((expanded) => !expanded)}
          >
            <span>Chats</span>
            <ChevronDown
              className={cn(
                "size-3.5 shrink-0 transition-transform",
                !chatsExpanded && "-rotate-90",
              )}
            />
          </button>

          {chatsExpanded ? (
            <div className="mt-1 space-y-0.5">
              {!hasSavedChats ? (
                <div className="px-1 py-1">
                  <EmptyState
                    description="Ask a question to start a new investigation thread."
                    size="sm"
                    title="No saved chats yet"
                  />
                </div>
              ) : null}
              {sessions.map((session) => (
                <div className="group flex items-center gap-0.5" key={session.localId}>
                  <button
                    className={cn(
                      "min-w-0 flex-1 truncate rounded-lg px-2.5 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
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
          ) : null}
        </div>
      </div>

      {meta ? (
        <div className="shrink-0 px-4 py-4 text-xs text-muted-foreground">{meta}</div>
      ) : null}
    </aside>
  );
}
