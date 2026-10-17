import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Modal,
  ModalContent,
  ModalHeader,
  ModalTitle,
  Spinner,
  SwitchRow,
} from "@/components/ui";
import { ChatToolsCatalog } from "@/components/ui/chat";
import {
  fetchAiTools,
  grantAiTool,
  revokeAiToolGrant,
  type AiToolInfo,
} from "@/api/ai";
import { toolCatalogEntry } from "@/components/chat/toolsCatalog";

/**
 * "Available tools" dialog for the chat header (study's ToolsDialog on
 * career's tool registry): the modal + fetch stay app glue, the catalog
 * itself is the library `ChatToolsCatalog`. The grant section is the D20
 * consent surface: state-changing tools run only while enabled here
 * (per-grant law); destructive tools never appear (they confirm every
 * call through a proposal card and are not grantable).
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
    fetchAiTools({ includeCapabilities: true, bindableOnly: true })
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

  const grantable = (tools ?? []).filter(
    (tool) => tool.kind !== "capability" && tool.risk_class === "state-changing",
  );

  const toggleGrant = async (tool: AiToolInfo, checked: boolean) => {
    // Optimistic flip; the backend is the law (a rejected grant — e.g. a
    // stale dialog racing a registry change — snaps back on refetch).
    const flip = (rows: AiToolInfo[], granted: boolean) =>
      rows.map((row) =>
        row.key === tool.key ? { ...row, granted } : row,
      );
    setTools((rows) => (rows ? flip(rows, checked) : rows));
    try {
      if (checked) {
        await grantAiTool(tool.key);
      } else {
        await revokeAiToolGrant(tool.key);
      }
    } catch {
      setTools((rows) => (rows ? flip(rows, !checked) : rows));
    }
  };

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
          <div className="flex flex-col gap-3">
            <ChatToolsCatalog
              tools={tools.map((tool) =>
                toolCatalogEntry(tool, {
                  hitlAction: t("toolsDialog.hitlAction"),
                  riskLabels: {
                    "state-changing": t("toolsDialog.riskStateChanging"),
                    destructive: t("toolsDialog.riskDestructive"),
                  },
                }),
              )}
            />
            {grantable.length > 0 ? (
              <section
                className="flex flex-col gap-1 rounded-[var(--as-radius)] border border-[var(--as-border)] p-2.5"
                data-testid="chat-tools-grants"
              >
                <p className="text-xs font-medium uppercase tracking-wide text-[var(--as-muted-fg)]">
                  {t("toolsDialog.grantsTitle")}
                </p>
                <p className="text-xs text-[var(--as-muted-fg)]">
                  {t("toolsDialog.grantsHint")}
                </p>
                {grantable.map((tool) => (
                  <SwitchRow
                    key={tool.key}
                    label={tool.title || tool.key}
                    checked={tool.granted === true}
                    onCheckedChange={(checked) => void toggleGrant(tool, checked)}
                    currentValue={t("toolsDialog.grantHintLine")}
                    data-testid={`tool-grant-${tool.key}`}
                  />
                ))}
              </section>
            ) : null}
          </div>
        )}
      </ModalContent>
    </Modal>
  );
}
