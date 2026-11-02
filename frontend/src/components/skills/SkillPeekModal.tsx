import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { ReactNode, RefObject } from "react";

import { apiDetail } from "@/api/client";
import { fetchSkill, fetchSkillRelations } from "@/api/skills";
import { buttonVariants, Badge, PanelModal } from "@/components/ui";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import { formatAbsolute } from "@/lib/time";
import type { SkillDetail } from "@/types/wire";

/** One related skill (an approved depth-1 neighbor from the relations
 * endpoint — the detail response carries no relations). */
interface PeekRelated {
  key: string;
  label: string;
}

type PeekEntry =
  | { missing: true }
  | { missing: false; detail: SkillDetail; related: PeekRelated[] };

/** Per-session cache (module lifetime): found and missing entries both
 * cache, so re-opening a chip is instant and a raw label that already
 * 404'd doesn't refetch. */
const cache = new Map<string, PeekEntry>();
const inflight = new Map<string, Promise<PeekEntry>>();

/** Test seam — clears the peek cache between tests/sessions. */
export function clearSkillPeekCache(): void {
  cache.clear();
  inflight.clear();
}

function isNotFound(error: unknown): boolean {
  // same heuristic as the skill page (apiDetail flattens axios errors)
  const message = apiDetail(error);
  return message.includes("404") || message.toLowerCase().includes("not found");
}

function loadPeek(key: string): Promise<PeekEntry> {
  const hit = cache.get(key);
  if (hit) return Promise.resolve(hit);
  const pending = inflight.get(key);
  if (pending) return pending;
  const run: Promise<PeekEntry> = (async () => {
    try {
      const [detail, relations] = await Promise.all([
        fetchSkill(key),
        fetchSkillRelations(key).catch(() => ({ nodes: [], edges: [] })),
      ]);
      const related = (relations.nodes ?? [])
        .filter((node) => node.key !== detail.key)
        .map((node) => ({ key: node.key, label: node.label }));
      const entry: PeekEntry = { missing: false, detail, related };
      cache.set(key, entry);
      return entry;
    } catch (error) {
      if (isNotFound(error)) {
        const entry: PeekEntry = { missing: true };
        cache.set(key, entry);
        return entry;
      }
      throw error;
    } finally {
      inflight.delete(key);
    }
  })();
  inflight.set(key, run);
  return run;
}

export interface SkillPeekController {
  /** The peeked skill's taxonomy address; null = closed. */
  skillKey: string | null;
  /** The chip's required level (anchors highlight it in the peek). */
  highlightLevel: number | null;
  /** Pass to the modal — it refocuses the chip on close, overriding
   * Radix's default restore (deterministic; no trigger context). */
  returnFocusRef: RefObject<HTMLElement | null>;
  open: (key: string, trigger: HTMLElement | null, level?: number | null) => void;
  close: () => void;
}

/** Peek state for one surface: `open` remembers the chip button,
 * `close` clears the state (focus returns via the modal's
 * onCloseAutoFocus). */
export function useSkillPeek(): SkillPeekController {
  const [state, setState] = useState<{ key: string | null; level: number | null }>({
    key: null,
    level: null,
  });
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const open = useCallback(
    (key: string, trigger: HTMLElement | null, level: number | null = null) => {
      returnFocusRef.current = trigger;
      setState({ key, level });
    },
    [],
  );
  const close = useCallback(() => {
    setState({ key: null, level: null });
  }, []);
  return {
    skillKey: state.key,
    highlightLevel: state.level,
    returnFocusRef,
    open,
    close,
  };
}

/** The plan-148 skill page in miniature (plan 149): status/category/
 * aliases header, compact stat tiles, level anchors with the chip's
 * required level highlighted, related skills that switch the peek, and
 * a footer link to the full `/skills/:key` page. 404 → pending-review
 * state (raw labels never entered the taxonomy). */
export function SkillPeekModal({
  skillKey,
  highlightLevel = null,
  onClose,
  returnFocusRef,
}: {
  skillKey: string | null;
  highlightLevel?: number | null;
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
}) {
  const { t } = useTranslation();
  const [activeKey, setActiveKey] = useState<string | null>(skillKey);
  const [entry, setEntry] = useState<PeekEntry | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (skillKey !== null) setActiveKey(skillKey);
  }, [skillKey]);

  useEffect(() => {
    if (!activeKey) return;
    let cancelled = false;
    setEntry(null);
    setFailed(false);
    loadPeek(activeKey)
      .then((loaded) => {
        if (!cancelled) setEntry(loaded);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [activeKey]);

  const open = skillKey !== null && activeKey !== null;

  let body: ReactNode;
  if (!open) {
    body = null;
  } else if (failed) {
    body = (
      <p className="text-sm text-[var(--as-danger)]" data-testid="skill-peek-error">
        {activeKey}
      </p>
    );
  } else if (entry === null) {
    body = (
      <div data-testid="skill-peek-loading" className="space-y-3">
        <div className="cv-shimmer h-6 w-1/3 rounded-[var(--as-radius)]" />
        <div className="cv-shimmer h-16 rounded-[var(--as-radius)]" />
        <div className="cv-shimmer h-24 rounded-[var(--as-radius)]" />
      </div>
    );
  } else if (entry.missing) {
    body = (
      <div data-testid="skill-peek-pending" className="space-y-1.5 py-2">
        <p className="text-sm font-medium text-[var(--as-fg)]">
          {t("skillPage.peek.pendingTitle")}
        </p>
        <p className="text-sm text-[var(--as-muted-fg)]">
          {t("skillPage.peek.pendingBody", { label: activeKey })}
        </p>
      </div>
    );
  } else {
    body = (
      <PeekBody
        detail={entry.detail}
        related={entry.related}
        highlightLevel={highlightLevel}
        onSwitch={(key) => setActiveKey(key)}
      />
    );
  }

  return (
    <span
      onClick={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.stopPropagation()}
    >
      <PanelModal
        open={open}
        onOpenChange={(next) => {
          if (!next) onClose();
        }}
        onCloseAutoFocus={(event) => {
          // deterministic focus return to the chip (no trigger context)
          event.preventDefault();
          returnFocusRef?.current?.focus();
        }}
        title={activeKey ?? ""}
        size="md"
        data-testid="skill-peek"
        data-key={open ? activeKey : undefined}
        footer={
          <div className="flex justify-end">
            <Link
              to={`/skills/${activeKey ?? ""}`}
              className={buttonVariants({ variant: "outline", size: "sm" })}
              data-testid="skill-peek-open-page"
              onClick={onClose}
            >
              {t("skillPage.peek.openPage")}
              <ArrowRight className="ml-1 h-3.5 w-3.5" aria-hidden />
            </Link>
          </div>
        }
      >
        <div className="space-y-4" data-testid="skill-peek-body">
          {body}
        </div>
      </PanelModal>
    </span>
  );
}

function PeekBody({
  detail,
  related,
  highlightLevel,
  onSwitch,
}: {
  detail: SkillDetail;
  related: PeekRelated[];
  highlightLevel: number | null;
  onSwitch: (key: string) => void;
}) {
  const { t } = useTranslation();
  const stats = detail.stats ?? null;
  const tiles: StatTile[] = stats
    ? [
        { label: t("skillPage.stats.demand"), value: stats.demand_count ?? 0 },
        {
          label: t("skillPage.stats.avgLevel"),
          value:
            stats.avg_required_level != null ? `${stats.avg_required_level}/10` : "—",
        },
        { label: t("skillPage.stats.users"), value: stats.user_count ?? 0 },
        {
          label: t("skillPage.stats.firstSeen"),
          value: stats.first_seen ? formatAbsolute(stats.first_seen) : "—",
        },
      ]
    : [];
  const anchors = (detail.level_anchors ?? []).map((anchor) => ({
    level: Number(anchor.level),
    label: String(anchor.label ?? ""),
    description: String(anchor.description ?? ""),
  }));
  const aliases = detail.aliases ?? [];

  return (
    <>
      {detail.merged_into ? (
        <div
          data-testid="skill-peek-merged"
          className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--as-radius)] border border-[var(--as-warning)] bg-[var(--as-muted)] px-3 py-1.5 text-sm"
        >
          <span className="text-[var(--as-fg)]">
            {t("skillPage.mergedInto", { key: detail.merged_into })}
          </span>
          <button
            type="button"
            onClick={() => onSwitch(detail.merged_into as string)}
            className="text-sm font-medium text-[var(--as-accent)] underline"
            data-testid="skill-peek-merged-link"
          >
            {t("skillPage.openSurvivor")}
          </button>
        </div>
      ) : null}

      <header className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant={
              detail.status === "active"
                ? "success"
                : detail.status === "deprecated"
                  ? "warning"
                  : "secondary"
            }
            data-testid="skill-peek-status"
          >
            {t(`taxonomy.${detail.status}`)}
          </Badge>
          <span className="text-sm text-[var(--as-muted-fg)]">{detail.category}</span>
        </div>
        <p className="font-mono text-xs text-[var(--as-muted-fg)]">{detail.key}</p>
        {aliases.length > 0 ? (
          <p className="text-sm text-[var(--as-muted-fg)]" data-testid="skill-peek-aliases">
            {t("skillPage.aliasesLabel")}: {aliases.join(", ")}
          </p>
        ) : null}
        {detail.description ? (
          <p className="max-w-prose text-sm text-[var(--as-fg)]">{detail.description}</p>
        ) : null}
      </header>

      {tiles.length > 0 ? <StatTiles tiles={tiles} columns={4} testId="skill-peek-stats" /> : null}

      {anchors.length > 0 ? (
        <section data-testid="skill-peek-anchors" className="space-y-1.5">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("skillPage.anchorsTitle")}
          </h3>
          <dl className="space-y-1">
            {anchors.map((anchor) => {
              const active = highlightLevel != null && anchor.level === highlightLevel;
              return (
                <div
                  key={anchor.level}
                  data-testid="skill-peek-anchor"
                  data-level={anchor.level}
                  data-active={active ? "true" : undefined}
                  className={
                    active
                      ? "flex gap-2 rounded-[var(--as-radius)] bg-[var(--as-muted)] px-2 py-1 text-sm ring-1 ring-[var(--as-accent)]"
                      : "flex gap-2 text-sm"
                  }
                >
                  <dt className="w-24 shrink-0 font-medium text-[var(--as-fg)]">
                    {t("skillPage.levelN", { level: anchor.level })}
                    <span className="ml-1 font-normal text-[var(--as-muted-fg)]">
                      {anchor.label}
                    </span>
                  </dt>
                  <dd className="text-[var(--as-muted-fg)]">{anchor.description}</dd>
                </div>
              );
            })}
          </dl>
        </section>
      ) : null}

      {related.length > 0 ? (
        <section data-testid="skill-peek-related" className="space-y-1.5">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("skillPage.relatedTitle")}
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {related.map((node) => (
              <button
                key={node.key}
                type="button"
                onClick={() => onSwitch(node.key)}
                className="rounded-md border border-[var(--as-border)] px-2 py-0.5 text-xs text-[var(--as-fg)] hover:border-[var(--as-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--as-focus-ring)]"
                data-testid={`skill-peek-related-${node.key}`}
              >
                {node.label}
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}
