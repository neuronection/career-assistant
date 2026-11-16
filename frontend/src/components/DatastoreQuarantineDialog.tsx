import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import {
  Button,
  CopyButton,
  Modal,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import type { DatastoreQuarantine } from "@/api/instance";
import { useDatastoreQuarantineStore } from "@/stores/datastoreQuarantineStore";

/** Boot gate for the deliberate v0.17 datastore break: the notice is the
 * first startup screen and the first-run wizard stays suppressed until it
 * is acknowledged (a quarantined boot has a fresh database, so the wizard
 * would otherwise open too — family datastore-breaks contract). */
export function DatastoreQuarantineGate() {
  const load = useDatastoreQuarantineStore((state) => state.load);
  const notice = useDatastoreQuarantineStore((state) => state.notice);
  const dismiss = useDatastoreQuarantineStore((state) => state.dismiss);

  useEffect(() => {
    void load();
  }, [load]);

  if (!notice) return null;
  return <DatastoreQuarantineDialog notice={notice} onDismiss={dismiss} />;
}

/** One-time notice: what happened, where the old data lives, and how to go
 * back. Dismissal is client-local and keyed by `quarantined_at`. */
export function DatastoreQuarantineDialog({
  notice,
  onDismiss,
}: {
  notice: DatastoreQuarantine;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onDismiss();
      }}
    >
      <ModalContent
        size="md"
        aria-describedby={undefined}
        data-testid="datastore-quarantine"
      >
        <ModalHeader>
          <ModalTitle>{t("datastoreQuarantine.title")}</ModalTitle>
        </ModalHeader>
        <div className="space-y-4">
          <p className="text-sm text-[var(--as-muted-fg)]">
            {notice.reason === "unreadable"
              ? t("datastoreQuarantine.bodyUnreadable")
              : t("datastoreQuarantine.body")}
          </p>
          <div className="space-y-1">
            <p className="text-xs font-medium text-[var(--as-muted-fg)]">
              {t("datastoreQuarantine.pathLabel")}
            </p>
            <div className="flex items-start gap-2">
              <code
                data-testid="datastore-quarantine-path"
                className="min-w-0 flex-1 break-all rounded-[var(--as-radius-sm)] border border-[var(--as-border)] bg-[var(--as-surface)] p-2 font-mono text-xs text-[var(--as-fg)]"
              >
                {notice.path}
              </code>
              <CopyButton value={notice.path} label={t("datastoreQuarantine.copy")} />
            </div>
          </div>
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("datastoreQuarantine.rollback")}
          </p>
        </div>
        <ModalFooter>
          <Button size="sm" autoFocus onClick={onDismiss}>
            {t("datastoreQuarantine.dismiss")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
