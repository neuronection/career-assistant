import { useTranslation } from "react-i18next";

import { Badge, Table } from "@/components/ui";
import type { KitChecklistItem, PostingKit } from "@/types/wire";

function levelBadge(item: KitChecklistItem, t: (key: string) => string) {
  const variant =
    item.level === "pass"
      ? "success"
      : item.level === "warn"
        ? "warning"
        : item.level === "fail"
          ? "danger"
          : "secondary";
  return (
    <Badge variant={variant} data-testid={`kit-check-${item.id}`}>
      {t(`applications.kit.checklist.level.${item.level}`)}
    </Badge>
  );
}

/** The kit's checklist tab: read-only and sourced — posting state from
 * `expires_at`, the measured page count from the existing lint, and a
 * few static file hints. General guidance only; never a simulation of
 * any ATS product. */
export function KitChecklistTab({ kit }: { kit: PostingKit }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3 py-3" data-testid="kit-checklist-tab">
      <Table
        headers={[
          t("applications.kit.checklist.col.status"),
          t("applications.kit.checklist.col.item"),
          t("applications.kit.checklist.col.source"),
        ]}
        rows={(kit.checklist ?? []).map((item: KitChecklistItem) => [
          levelBadge(item, t),
          <span key="label" className="text-sm text-[var(--as-fg)]">
            {item.label}
          </span>,
          <span
            key="source"
            className="text-xs uppercase tracking-wide text-[var(--as-muted-fg)]"
          >
            {item.source}
          </span>,
        ])}
      />
      <p className="text-xs text-[var(--as-muted-fg)]" data-testid="kit-checklist-note">
        {t("applications.kit.checklist.note")}
      </p>
    </div>
  );
}
