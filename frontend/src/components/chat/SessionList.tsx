import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Button,
  ConfirmationModal,
  Modal,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import { ChatSessionList } from "@/components/ui/chat";
import { exportChatMarkdown } from "@/components/chat/exportChat";
import { useChatStore } from "@/stores/chatStore";

/**
 * App-side session management on the library `ChatSessionList`
 *: rename dialog, delete confirmation and.md export stay
 * app glue — the list itself (search, date groups, action menu) is the
 * library module. Shared by the `/chat` page, the bubble picker and the
 * header history popover.
 */
export function SessionList({
  searchable = true,
  onPick,
}: {
  searchable?: boolean;
  onPick?: () => void;
}) {
  const sessions = useChatStore((state) => state.sessions);
  const activeSessionId = useChatStore((state) => state.activeSessionId);
  const openSession = useChatStore((state) => state.openSession);
  const newSession = useChatStore((state) => state.newSession);
  const renameSession = useChatStore((state) => state.renameSession);
  const deleteSession = useChatStore((state) => state.deleteSession);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { t } = useTranslation();

  const submitRename = async () => {
    const title = renameDraft.trim();
    if (renameId === null || title === "") {
      return;
    }
    setBusy(true);
    try {
      await renameSession(renameId, title);
      setRenameId(null);
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = () => {
    if (deleteId === null) {
      return;
    }
    void deleteSession(deleteId).then(() => setDeleteId(null));
  };

  return (
    <>
      <ChatSessionList
        sessions={sessions.map((session) => ({
          id: session.id,
          title: session.title,
          updatedAt: session.last_activity_at ?? session.created_at,
        }))}
        activeId={activeSessionId}
        onSelect={(id) => {
          void openSession(id);
          onPick?.();
        }}
        onNew={() => {
          void newSession();
          onPick?.();
        }}
        searchable={searchable}
        onRename={(id) => {
          setRenameId(id);
          setRenameDraft(sessions.find((session) => session.id === id)?.title ?? "");
        }}
        onDelete={(id) => setDeleteId(id)}
        onExport={(id) => {
          const session = sessions.find((candidate) => candidate.id === id);
          void exportChatMarkdown(id, session?.title ?? "Chat");
        }}
      />
      <Modal open={renameId !== null} onOpenChange={(open) => !open && setRenameId(null)}>
        <ModalContent size="sm">
          <ModalHeader>
            <ModalTitle>{t("sessionList.renameChat")}</ModalTitle>
          </ModalHeader>
          <input
            data-testid="session-rename-input"
            aria-label={t("sessionList.chatTitleAria")}
            value={renameDraft}
            maxLength={200}
            autoFocus
            onChange={(event) => setRenameDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void submitRename();
              }
            }}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
          />
          <ModalFooter>
            <Button variant="outline" size="sm" onClick={() => setRenameId(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="default"
              size="sm"
              disabled={busy || renameDraft.trim() === ""}
              onClick={() => void submitRename()}
            >
              {t("common.save")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
      <ConfirmationModal
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title={t("sessionList.deleteTitle")}
        description={t("sessionList.deleteBody")}
        confirmLabel={t("sessionList.deleteConfirm")}
        destructive
        busy={busy}
        onConfirm={confirmDelete}
      />
    </>
  );
}
