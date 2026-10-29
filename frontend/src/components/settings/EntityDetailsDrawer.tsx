import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Badge,
  Button,
  ConfirmationModal,
  PanelModal,
  Spinner,
} from "@/components/ui";
import { StatTiles } from "@/components/stats/StatTiles";
import { fetchSkill, fetchSkillHistory } from "@/api/skills";
import type { SkillChange, SkillDetail } from "@/types/wire";
import type { SkillRow, Tag } from "@/api/taxonomy";
import { categoryIcon } from "@/components/settings/taxonomyIcons";

export interface DrawerAction {
  label: string;
  onClick: () => void;
  variant?: "default" | "secondary" | "outline" | "ghost" | "destructive";
  testid?: string;
  disabled?: boolean;
}

interface EntityDetailsDrawerProps {
  testid: string;
  title: ReactNode;
  headerIcon?: ReactNode;
  headerBadge?: string;
  closeLabel?: string;
  /** Footer actions (left group) — the Close button is always appended. */
  actions?: DrawerAction[];
  /** Extra footer content (e.g. the skill page link), right-aligned next to Close. */
  footerExtra?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

/** Generalized details drawer (plan 150): ONE library PanelModal —
 * right-sized sheet on desktop, full-screen on mobile — with a header
 * (icon + title + status badge), a body slot and a footer where the
 * per-kind actions live (rows stay clean; destructive moves are
 * confirmed here). */
export function EntityDetailsDrawer({
  testid,
  title,
  headerIcon,
  headerBadge,
  closeLabel,
  actions = [],
  footerExtra,
  onClose,
  children,
}: EntityDetailsDrawerProps) {
  const { t } = useTranslation();
  return (
    <PanelModal
      open
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      title={
        <span className="flex min-w-0 items-center gap-2">
          {headerIcon}
          <span className="truncate">{title}</span>
          {headerBadge ? (
            <Badge variant="outline" data-testid="drawer-status">
              {headerBadge}
            </Badge>
          ) : null}
        </span>
      }
      closeLabel={closeLabel ?? t("common.close")}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {actions.map((action) => (
              <Button
                key={action.testid ?? action.label}
                variant={action.variant ?? "outline"}
                size="sm"
                disabled={action.disabled}
                onClick={action.onClick}
                data-testid={action.testid}
              >
                {action.label}
              </Button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            {footerExtra}
            <Button variant="outline" size="sm" onClick={onClose}>
              {t("common.close")}
            </Button>
          </div>
        </div>
      }
    >
      <div data-testid={testid} className="space-y-4">
        {children}
      </div>
    </PanelModal>
  );
}

/** The interests adapter: identity + description, in-drawer Edit form,
 * and the Deprecate/Restore + Delete (confirmed) actions the old table
 * rows carried as inline text buttons. */
export function InterestDetailsDrawer({
  tag,
  onClose,
  onToggleDeprecated,
  onDelete,
  onEdit,
}: {
  tag: Tag;
  onClose: () => void;
  onToggleDeprecated: (tag: Tag) => Promise<boolean>;
  onDelete: (tag: Tag) => Promise<boolean>;
  onEdit: (
    tag: Tag,
    patch: { label: string; category: string; description: string },
  ) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({
    label: tag.label,
    category: tag.category,
    description: tag.description,
  });
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const Icon = categoryIcon(tag.category);

  useEffect(() => {
    setEditing(false);
    setDraft({ label: tag.label, category: tag.category, description: tag.description });
  }, [tag.id, tag.label, tag.category, tag.description]);

  const save = async () => {
    setSaving(true);
    const ok = await onEdit(tag, draft);
    setSaving(false);
    if (ok) setEditing(false);
  };

  return (
    <>
      <EntityDetailsDrawer
        testid="interest-details-drawer"
        title={tag.label}
        headerIcon={<Icon className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />}
        headerBadge={tag.deprecated ? t("taxonomy.deprecated") : t("taxonomy.active")}
        onClose={onClose}
        actions={[
          {
            label: t("taxonomy.drawer.edit"),
            variant: "outline",
            testid: "drawer-edit-toggle",
            onClick: () => setEditing((v) => !v),
          },
          {
            label: tag.deprecated ? t("taxonomy.restore") : t("taxonomy.deprecate"),
            variant: "outline",
            testid: "drawer-status-action",
            onClick: () => void onToggleDeprecated(tag),
          },
          {
            label: t("taxonomy.delete"),
            variant: "destructive",
            testid: "drawer-delete",
            onClick: () => setConfirmingDelete(true),
          },
        ]}
      >
        <p className="font-mono text-xs text-[var(--as-muted-fg)]">{tag.key}</p>
        {editing ? (
          <div className="grid gap-2 sm:grid-cols-2" data-testid="drawer-edit-form">
            <input
              value={draft.label}
              onChange={(e) => setDraft({ ...draft, label: e.target.value })}
              placeholder={t("taxonomy.labelPlaceholder")}
              aria-label={t("taxonomy.label")}
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)] outline-none focus:border-[var(--as-focus-ring)]"
              data-testid="drawer-edit-label"
            />
            <input
              value={draft.category}
              onChange={(e) => setDraft({ ...draft, category: e.target.value })}
              placeholder={t("taxonomy.categoryPlaceholder")}
              aria-label={t("taxonomy.category")}
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)] outline-none focus:border-[var(--as-focus-ring)]"
              data-testid="drawer-edit-category"
            />
            <input
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              placeholder={t("taxonomy.descriptionPlaceholder")}
              aria-label={t("taxonomy.drawer.descriptionLabel")}
              className="sm:col-span-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)] outline-none focus:border-[var(--as-focus-ring)]"
              data-testid="drawer-edit-description"
            />
            <div className="flex gap-2 sm:col-span-2">
              <Button
                size="sm"
                disabled={!draft.label || !draft.category || saving}
                onClick={() => void save()}
                data-testid="drawer-edit-save"
              >
                {t("common.save")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setEditing(false);
                  setDraft({
                    label: tag.label,
                    category: tag.category,
                    description: tag.description,
                  });
                }}
                data-testid="drawer-edit-cancel"
              >
                {t("common.cancel")}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-1.5 text-sm">
            <p className="text-[var(--as-muted-fg)]">
              <span className="font-medium text-[var(--as-fg)]">
                {t("taxonomy.category")}:
              </span>{" "}
              {tag.category}
            </p>
            {tag.description ? (
              <p className="text-[var(--as-muted-fg)]">
                <span className="font-medium text-[var(--as-fg)]">
                  {t("taxonomy.drawer.descriptionLabel")}:
                </span>{" "}
                {tag.description}
              </p>
            ) : null}
          </div>
        )}
      </EntityDetailsDrawer>
      <ConfirmationModal
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        onConfirm={() => {
          setConfirmingDelete(false);
          void onDelete(tag);
        }}
        title={t("taxonomy.drawer.deleteTitle", { label: tag.label })}
        description={t("taxonomy.drawer.deleteBody")}
        confirmLabel={t("taxonomy.delete")}
        destructive
      />
    </>
  );
}

/** The skills adapter: the plan-148 preview drawer (stats, aliases, the
 * newest history events, open-page link) plus the admin actions —
 * promote for proposed rows, deprecate/restore, merge (target select
 * lives here now) and a confirmed delete. */
export function SkillDetailsDrawer({
  skillKey,
  mergeTargets,
  onClose,
  onPromote,
  onSetStatus,
  onDelete,
  onMerge,
}: {
  skillKey: string;
  mergeTargets: SkillRow[];
  onClose: () => void;
  onPromote: () => Promise<boolean>;
  onSetStatus: (status: "active" | "deprecated") => Promise<boolean>;
  onDelete: () => Promise<boolean>;
  onMerge: (targetId: string) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [history, setHistory] = useState<SkillChange[] | null>(null);
  const [merging, setMerging] = useState(false);
  const [mergeTarget, setMergeTarget] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  useEffect(() => {
    void fetchSkill(skillKey)
      .then(setDetail)
      .catch(() => setDetail(null));
    void fetchSkillHistory(skillKey, { limit: 5 })
      .then((page) => setHistory(page.items ?? []))
      .catch(() => setHistory([]));
    setMerging(false);
    setMergeTarget("");
  }, [skillKey]);

  const canMerge = detail != null && detail.status !== "active" && mergeTargets.length > 0;

  const actions: DrawerAction[] = [];
  if (detail?.status === "proposed") {
    actions.push({
      label: t("taxonomy.promote"),
      variant: "default",
      testid: "drawer-promote",
      onClick: () => void onPromote(),
    });
  }
  if (detail && detail.status !== "proposed") {
    actions.push({
      label: detail.status === "active" ? t("taxonomy.deprecate") : t("taxonomy.restore"),
      variant: "outline",
      testid: "drawer-status-action",
      onClick: () =>
        void onSetStatus(detail.status === "active" ? "deprecated" : "active"),
    });
  }
  if (canMerge) {
    actions.push({
      label: t("taxonomy.merge"),
      variant: "outline",
      testid: "drawer-merge-toggle",
      onClick: () => setMerging((v) => !v),
    });
  }
  actions.push({
    label: t("taxonomy.delete"),
    variant: "destructive",
    testid: "drawer-delete",
    onClick: () => setConfirmingDelete(true),
  });

  return (
    <>
      <EntityDetailsDrawer
        testid="skill-details-drawer"
        title={detail?.label ?? skillKey}
        headerBadge={detail ? t(`taxonomy.${detail.status}`) : undefined}
        onClose={onClose}
        actions={actions}
        footerExtra={
          detail ? (
            <Link
              to={`/skills/${skillKey}`}
              className="text-sm text-[var(--as-accent)] underline"
              data-testid="drawer-open-page"
              onClick={onClose}
            >
              {t("skillPage.drawerOpen")}
            </Link>
          ) : undefined
        }
      >
        <p className="font-mono text-xs text-[var(--as-muted-fg)]">{skillKey}</p>
        {detail === null ? (
          <div className="flex justify-center py-8">
            <Spinner size="lg" />
          </div>
        ) : (
          <>
            {detail.stats ? (
              <StatTiles
                testId="drawer-stat-tiles"
                columns={3}
                tiles={[
                  {
                    label: t("skillPage.stats.demand"),
                    value: detail.stats.demand_count ?? 0,
                  },
                  {
                    label: t("skillPage.stats.avgLevel"),
                    value:
                      detail.stats.avg_required_level != null
                        ? `${detail.stats.avg_required_level}/10`
                        : "—",
                  },
                  { label: t("skillPage.stats.users"), value: detail.stats.user_count ?? 0 },
                ]}
              />
            ) : null}
            {detail.aliases && detail.aliases.length > 0 ? (
              <p className="text-sm text-[var(--as-muted-fg)]">
                {t("skillPage.aliasesLabel")}: {detail.aliases.join(", ")}
              </p>
            ) : null}
            {merging ? (
              <div
                className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] p-3"
                data-testid="drawer-merge-row"
              >
                <span className="text-xs text-[var(--as-muted-fg)]">
                  {t("taxonomy.mergeInto", { key: skillKey })}
                </span>
                <select
                  value={mergeTarget}
                  onChange={(e) => setMergeTarget(e.target.value)}
                  className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs text-[var(--as-fg)]"
                  data-testid="drawer-merge-target"
                >
                  <option value="">{t("taxonomy.chooseActive")}</option>
                  {mergeTargets.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.key}
                    </option>
                  ))}
                </select>
                <Button
                  size="sm"
                  disabled={!mergeTarget}
                  onClick={() => void onMerge(mergeTarget)}
                  data-testid="drawer-merge-confirm"
                >
                  {t("taxonomy.mergeConfirm")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setMerging(false)}
                  data-testid="drawer-merge-cancel"
                >
                  {t("common.cancel")}
                </Button>
              </div>
            ) : null}
            <div data-testid="drawer-history">
              <h3 className="mb-2 text-sm font-medium text-[var(--as-fg)]">
                {t("skillPage.historyCount", { count: history?.length ?? 0 })}
              </h3>
              {history === null ? (
                <Spinner />
              ) : history.length === 0 ? (
                <p className="text-sm text-[var(--as-muted-fg)]">
                  {t("skillPage.historyEmpty")}
                </p>
              ) : (
                <ul className="space-y-1">
                  {history.map((entry) => (
                    <li key={entry.id} className="text-xs text-[var(--as-muted-fg)]">
                      <span className="font-medium text-[var(--as-fg)]">
                        {t(`skillPage.event.${entry.event}`, { defaultValue: entry.event })}
                      </span>{" "}
                      · {t(`skillPage.actor.${entry.actor_kind}`, { defaultValue: entry.actor_kind })}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </EntityDetailsDrawer>
      <ConfirmationModal
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        onConfirm={() => {
          setConfirmingDelete(false);
          void onDelete();
        }}
        title={t("taxonomy.drawer.deleteTitle", { label: detail?.label ?? skillKey })}
        description={t("taxonomy.drawer.deleteBody")}
        confirmLabel={t("taxonomy.delete")}
        destructive
      />
    </>
  );
}
