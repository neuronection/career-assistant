import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SegmentedTabs } from "@/components/ui";
import { RetrievalOverviewSection } from "@/components/audit/retrieval/RetrievalOverviewSection";
import { RetrievalSpacesSection } from "@/components/audit/retrieval/RetrievalSpacesSection";
import { RetrievalRunsSection } from "@/components/audit/retrieval/RetrievalRunsSection";
import { RetrievalQualitySection } from "@/components/audit/retrieval/RetrievalQualitySection";
import { RetrievalQueryHealthSection } from "@/components/audit/retrieval/RetrievalQueryHealthSection";
import { RetrievalFailuresSection } from "@/components/audit/retrieval/RetrievalFailuresSection";
import { RetrievalUsageSection } from "@/components/audit/retrieval/RetrievalUsageSection";
import { RetrievalChangesSection } from "@/components/audit/retrieval/RetrievalChangesSection";
import {
  parseRetrievalSection,
  RETRIEVAL_SECTIONS,
  sectionLabelKey,
  TOOLS_RETRIEVAL_URL,
  type RetrievalSection,
} from "@/components/audit/retrieval/retrievalHelpers";
import type { RetrievalWindow } from "@/api/retrieval";

const DETAIL_SECTIONS: readonly RetrievalSection[] = [
  "spaces",
  "runs",
  "quality",
  "query-health",
  "failures",
];

/** Audit → Retrieval (plan 51 Q2b): the read-only observation tab.
 * Sections are URL-synced via `?section=` and one `?detail=<id>` drives the
 * active run/space/quality/failure drawer. No writes live here — every
 * action deep-links to Tools → Retrieval. */
export function RetrievalTab({ window }: { window: RetrievalWindow }) {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const rawSection = searchParams.get("section");
  const section = parseRetrievalSection(rawSection);
  const detail = searchParams.get("detail");
  const detailSupported = DETAIL_SECTIONS.includes(section);
  const sectionsRef = useRef<HTMLDivElement | null>(null);
  const detailTriggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const expectedSection = section === "overview" ? null : section;
    const shouldDropDetail = !!detail && !detailSupported;
    if (rawSection === expectedSection && !shouldDropDetail) return;
    const next = new URLSearchParams(searchParams);
    if (expectedSection) next.set("section", expectedSection);
    else next.delete("section");
    if (shouldDropDetail) next.delete("detail");
    setSearchParams(next, { replace: true });
  }, [rawSection, section, detail, detailSupported, searchParams, setSearchParams]);

  const setSection = (nextSection: RetrievalSection) => {
    const next = new URLSearchParams(searchParams);
    if (nextSection === "overview") next.delete("section");
    else next.set("section", nextSection);
    next.delete("detail");
    setSearchParams(next, { replace: true });
  };

  const openDetail = (id: string) => {
    detailTriggerRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const next = new URLSearchParams(searchParams);
    next.set("detail", id);
    setSearchParams(next);
  };

  const closeDetail = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("detail");
    setSearchParams(next, { replace: true });
    const trigger = detailTriggerRef.current;
    detailTriggerRef.current = null;
    // Let the dialog finish its own close/focus cycle first.
    setTimeout(() => {
      if (trigger?.isConnected) {
        trigger.focus();
        return;
      }
      sectionsRef.current
        ?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
        ?.focus();
    }, 50);
  };

  // The section strip overflows a phone width; keep the deep-linked section
  // visible instead of leaving it off-screen at the end of the strip. Scroll
  // the strip itself — `scrollIntoView` would also move ancestor containers.
  useEffect(() => {
    const container = sectionsRef.current;
    const selected = container?.querySelector<HTMLElement>(
      '[role="tab"][aria-selected="true"]',
    );
    if (!container || !selected) return;
    const view = container.getBoundingClientRect();
    const tab = selected.getBoundingClientRect();
    if (tab.left >= view.left && tab.right <= view.right) return;
    container.scrollLeft +=
      tab.left - view.left - (view.width - tab.width) / 2;
  }, [section]);

  return (
    <div className="space-y-3" data-testid="audit-retrieval-tab">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div ref={sectionsRef} className="min-w-0 max-w-full overflow-x-auto">
          <SegmentedTabs
            ariaLabel={t("audit.retrieval.sectionsAria")}
            className="min-w-max max-sm:[&>button]:min-h-9"
            items={RETRIEVAL_SECTIONS.map((item) => ({
              value: item,
              label: t(sectionLabelKey(item)),
            }))}
            value={section}
            onValueChange={(next) => setSection(next as RetrievalSection)}
          />
        </div>
        <span className="text-xs text-[var(--as-muted-fg)]">
          {t("audit.retrieval.readOnly")}{" "}
          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="font-semibold text-[var(--as-primary)] hover:underline"
            data-testid="retrieval-tools-link"
          >
            {t("audit.retrieval.openTools")} →
          </Link>
        </span>
      </div>

      {section === "overview" && <RetrievalOverviewSection window={window} />}
      {section === "spaces" && (
        <RetrievalSpacesSection
          detailId={detail}
          onOpenDetail={openDetail}
          onCloseDetail={closeDetail}
        />
      )}
      {section === "runs" && (
        <RetrievalRunsSection
          window={window}
          detailId={detail}
          onOpenDetail={openDetail}
          onCloseDetail={closeDetail}
        />
      )}
      {section === "quality" && (
        <RetrievalQualitySection
          window={window}
          detailId={detail}
          onOpenDetail={openDetail}
          onCloseDetail={closeDetail}
        />
      )}
      {section === "query-health" && (
        <RetrievalQueryHealthSection
          window={window}
          detailId={detail}
          onOpenDetail={openDetail}
          onCloseDetail={closeDetail}
        />
      )}
      {section === "failures" && (
        <RetrievalFailuresSection
          window={window}
          detailId={detail}
          onOpenDetail={openDetail}
          onCloseDetail={closeDetail}
        />
      )}
      {section === "usage" && <RetrievalUsageSection window={window} />}
      {section === "changes" && <RetrievalChangesSection window={window} />}
    </div>
  );
}
