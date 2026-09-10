import { Maximize2, PanelRight, PictureInPicture2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import { useChatStore } from "@/stores/chatStore";

export type ChatSurfaceShape = "bubble" | "docked" | "page";

/**
 * The one chatbot, three shapes: every chat surface
 * — floating bubble, docked side column, /chat page — shows this
 * switcher, so users can move the conversation between shapes without
 * losing the session. "Page" is route-based; "docked" vs "bubble" is
 * the persisted `chatMode` on the chat store.
 */
export function ChatViewSwitcher({ surface }: { surface: ChatSurfaceShape }) {
  const { t } = useTranslation();
  const setChatMode = useChatStore((state) => state.setChatMode);
  const navigate = useNavigate();

  const leavePage = (mode: "bubble" | "docked") => {
    navigate("/");
    setChatMode(mode);
  };

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-pressed={surface === "docked"}
        data-testid="chat-view-docked"
        title={t("chatView.sidePanel")}
        aria-label={t("chatView.sidePanel")}
        onClick={() => (surface === "page" ? leavePage("docked") : setChatMode("docked"))}
      >
        <PanelRight className="size-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-pressed={surface === "bubble"}
        data-testid="chat-view-popup"
        title={t("chatView.popup")}
        aria-label={t("chatView.popup")}
        onClick={() => (surface === "page" ? leavePage("bubble") : setChatMode("bubble"))}
      >
        <PictureInPicture2 className="size-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-pressed={surface === "page"}
        data-testid="chat-view-page"
        title={t("chatView.openChatPage")}
        aria-label={t("chatView.openChatPage")}
        onClick={() => navigate("/chat")}
      >
        <Maximize2 className="size-4" />
      </Button>
    </>
  );
}
