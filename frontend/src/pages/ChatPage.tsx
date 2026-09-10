import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { PanelRight } from "lucide-react";

import { SessionList } from "@/components/chat/SessionList";
import { useChatStore } from "@/stores/chatStore";
import { Button } from "@/components/ui";
import { ChatSurfacePage } from "@/components/chat/ChatWidget";

export function ChatPage() {
  const { t } = useTranslation();
  const loadSessions = useChatStore((state) => state.loadSessions);
  const activeSessionId = useChatStore((state) => state.activeSessionId);
  const sessions = useChatStore((state) => state.sessions);
  const navigate = useNavigate();
  const activeSession = sessions.find((session) => session.id === activeSessionId);
  const cvId =
    activeSession?.context?.surface === "cv_builder"
      ? String(activeSession.context.cv_id)
      : null;

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  return (
    <div className="flex h-full min-h-0 gap-4">
      <aside className="hidden w-72 shrink-0 border-r border-slate-200 pr-2 lg:block">
        <SessionList />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {cvId && (
          <div className="flex justify-end px-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              data-testid="open-in-builder"
              onClick={() => navigate(`/cv/${cvId}`)}
              title={t("chatPage.boundToCv")}
            >
              <PanelRight className="mr-1 h-4 w-4" /> {t("chatPage.openInBuilder")}
            </Button>
          </div>
        )}
        <div className="min-h-0 flex-1">
          <ChatSurfacePage />
        </div>
      </div>
    </div>
  );
}
