import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Modal, ModalContent, ModalFooter, ModalHeader, ModalTitle } from "@/components/ui";
import { fetchAdminSources } from "@/api/sources";
import type { PostingSource } from "@/api/sources";
import { QueryPlanPanel } from "@/components/settings/QueryPlanPanel";

/**
 * Query plan for one posting source (plan 133), fetched live on open so a
 * long-lived page never shows a stale plan. The panel itself is shared
 * with the source management page (plan 134).
 */

export function QueryPlanDialog({
  sourceId,
  onClose,
}: {
  sourceId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [source, setSource] = useState<PostingSource | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchAdminSources()
      .then((rows) => {
        if (!cancelled) {
          setSource(rows.find((row) => row.id === sourceId) ?? null);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  return (
    <Modal open onOpenChange={onClose}>
      <ModalContent size="md" closeLabel={t("toolsSettings.connectors.sources.planClose")}>
        <ModalHeader>
          <ModalTitle>
            {t("toolsSettings.connectors.sources.planTitle", {
              key: source?.key ?? sourceId,
            })}
          </ModalTitle>
        </ModalHeader>
        <div>
          {loading ? (
            <p className="text-sm text-[var(--as-muted-fg)]" role="status">
              {t("toolsSettings.connectors.sources.planLoading")}
            </p>
          ) : source ? (
            <QueryPlanPanel source={source} />
          ) : (
            <p className="text-sm text-[var(--as-muted-fg)]">
              {t("toolsSettings.connectors.sources.planNotFound")}
            </p>
          )}
        </div>
        <ModalFooter>
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("toolsSettings.connectors.sources.planClose")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
