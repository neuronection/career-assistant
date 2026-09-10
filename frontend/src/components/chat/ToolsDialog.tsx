import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Modal,
  ModalContent,
  ModalHeader,
  ModalTitle,
  Spinner,
} from "@/components/ui";
import { ChatToolsCatalog } from "@/components/ui/chat";
import { fetchAiTools, type AiToolInfo } from "@/api/ai";
import { toolCatalogEntry } from "@/components/chat/toolsCatalog";

/**
 * "Available tools" dialog for the chat header (study's ToolsDialog on
 * career's tool registry): the modal + fetch stay app glue, the catalog
 * itself is the library `ChatToolsCatalog`.
 */
export function ToolsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [tools, setTools] = useState<AiToolInfo[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    let cancelled = false;
    setTools(null);
    setError(false);
    fetchAiTools()
      .then((rows) => {
        if (!cancelled) {
          setTools(rows);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <ModalContent size="lg" className="max-h-[85vh] overflow-y-auto" data-testid="chat-tools-dialog">
        <ModalHeader>
          <ModalTitle>{t("toolsDialog.title")}</ModalTitle>
        </ModalHeader>
        {error ? (
          <p className="px-1 py-3 text-sm text-red-600" role="alert" data-testid="chat-tools-error">
            {t("toolsDialog.loadError")}
          </p>
        ) : tools === null ? (
          <div className="flex justify-center py-6" data-testid="chat-tools-loading">
            <Spinner />
          </div>
        ) : (
          <ChatToolsCatalog tools={tools.map(toolCatalogEntry)} />
        )}
      </ModalContent>
    </Modal>
  );
}
