import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Quote } from "lucide-react";

import { ContextMenu, type ContextMenuItem } from "@neuronection/assistant-ui";
import { copyText } from "@/lib/clipboard";
import { useCareerChatContext } from "@/components/chat/useCareerChat";

/**
 * Right-click menu over selected transcript text: Copy (desktop-safe
 * clipboard) and Quote in chat (markdown blockquote into the composer,
 * focused for an immediate follow-up question). Webview shells
 * (pywebview) ship no native selection menu — this is it.
 */
export function ChatSelectionMenu({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const chat = useCareerChatContext();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; text: string } | null>(
    null,
  );

  const quoteSelection = (text: string) => {
    const quote = text
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n");
    const current = chat.draft;
    const next = current.trim() === "" ? quote : `${current}\n\n${quote}`;
    chat.setDraft(`${next}\n\n`);
    const composer = document.querySelector<HTMLTextAreaElement>(
      '[data-as="chat-composer"] textarea',
    );
    composer?.focus();
  };

  const items: ContextMenuItem[] =
    menu === null
      ? []
      : [
          {
            key: "copy",
            label: t("chat.selectionMenu.copy"),
            icon: Copy,
            onSelect: () => {
              void copyText(menu.text);
            },
          },
          {
            key: "quote",
            label: t("chat.selectionMenu.quote"),
            icon: Quote,
            onSelect: () => quoteSelection(menu.text),
          },
        ];

  const onContextMenu = (event: React.MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current;
    const selection = window.getSelection();
    if (container === null || selection === null || selection.isCollapsed) {
      return;
    }
    if (!container.contains(selection.anchorNode)) {
      return;
    }
    const text = selection.toString().trim();
    if (text === "") {
      return;
    }
    event.preventDefault();
    setMenu({ x: event.clientX, y: event.clientY, text });
  };

  return (
    <div ref={containerRef} className="contents" onContextMenu={onContextMenu}>
      {children}
      <ContextMenu
        x={menu?.x ?? 0}
        y={menu?.y ?? 0}
        items={items}
        onClose={() => setMenu(null)}
      />
    </div>
  );
}
