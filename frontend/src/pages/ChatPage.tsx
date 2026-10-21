import { useEffect } from "react";

import { SessionList } from "@/components/chat/SessionList";
import { useChatStore } from "@/stores/chatStore";
import { ChatSurfacePage } from "@/components/chat/ChatWidget";

export function ChatPage() {
  const loadSessions = useChatStore((state) => state.loadSessions);

  useEffect(() => {
    void loadSessions();
    // The page takes over the open chat surfaces: the bubble collapses
    // (and stays collapsed after leaving) while the dock yields via its
    // own /chat guard. The conversation itself is shared store state.
    useChatStore.getState().setBubbleOpen(false);
  }, [loadSessions]);

  return (
    <div className="flex h-full min-h-0 gap-4">
      <aside className="hidden w-72 shrink-0 border-r border-slate-200 pr-2 lg:block">
        <SessionList />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1">
          <ChatSurfacePage />
        </div>
      </div>
    </div>
  );
}
