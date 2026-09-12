import { useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { CheckIndicator } from "@neuronection/assistant-ui/check-indicator";
import { fetchCvPageImageUrl } from "@/api/cvIntake";
import { EDUCATION_LEVEL_LABEL } from "@/components/profile/sections/options";
import { isStatusSection } from "./CvStatus";
import type {
  CvExtractPayload,
  CvIntakeSection,
  CvSelections,
  FieldEvidence,
} from "@/types/cvIntake";

interface ReviewItem {
  title: string;
  detail?: string;
  evidence: FieldEvidence;
}

interface SectionView {
  key: CvIntakeSection;
  label: string;
  items: ReviewItem[];
}

const SECTION_LABEL_KEYS: Record<CvIntakeSection, string> = {
  basics: "intake.section.basics",
  education: "intake.section.education",
  experience: "intake.section.experience",
  skills: "intake.section.skills",
  languages: "intake.section.languages",
  certifications: "intake.section.certifications",
  awards: "intake.section.awards",
  interests: "intake.section.interests",
};

const MONTH_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function prettyDate(raw: string): string {
  const text = raw.trim();
  let match = text.match(/^(\d{4})[-/.](\d{1,2})/);
  if (match) return `${MONTH_SHORT[Number(match[2]) - 1] ?? text} ${match[1]}`;
  match = text.match(/^(\d{1,2})[-/.](\d{4})$/);
  if (match) return `${MONTH_SHORT[Number(match[1]) - 1] ?? text} ${match[2]}`;
  match = text.match(/^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*(\d{4})$/i);
  if (match)
    return `${match[1].charAt(0).toUpperCase()}${match[1].slice(1, 3)} ${match[2]}`;
  return text;
}

function period(start: string, end: string): string | undefined {
  if (!start && !end) return undefined;
  return [prettyDate(start), prettyDate(end) || i18next.t("intake.now")]
    .filter(Boolean)
    .join(" – ");
}

/** The eight applicable sections of a draft, in review order. */
export function sectionViews(payload: CvExtractPayload): SectionView[] {
  const t = i18next.t;
  const label = (key: CvIntakeSection) => t(SECTION_LABEL_KEYS[key]);
  const views: SectionView[] = [];
  const basics = payload.basics;
  if (basics && (basics.full_name || basics.email || basics.phone || basics.location)) {
    const detail = [basics.email, basics.phone, basics.location]
      .filter(Boolean)
      .join(" · ");
    views.push({
      key: "basics",
      label: label("basics"),
      items: [
        {
          title: basics.full_name || basics.headline || t("intake.contactDetails"),
          detail,
          evidence: basics.evidence,
        },
      ],
    });
  }
  if (payload.education.length) {
    views.push({
      key: "education",
      label: label("education"),
      items: payload.education.map((item) => ({
        title: [item.program, item.institution].filter(Boolean).join(" — "),
        detail: [
          EDUCATION_LEVEL_LABEL[item.level] || item.level,
          period(item.start, item.end),
        ]
          .filter(Boolean)
          .concat(!item.level ? [t("intake.levelUnknownHint")] : [])
          .join(" · "),
        evidence: item.evidence,
      })),
    });
  }
  if (payload.experience.length) {
    views.push({
      key: "experience",
      label: label("experience"),
      items: payload.experience.map((item) => ({
        title: [item.title, item.org].filter(Boolean).join(" — "),
        detail: [item.kind, period(item.start, item.end)]
          .filter(Boolean)
          .join(" · "),
        evidence: item.evidence,
      })),
    });
  }
  if (payload.skills.length) {
    views.push({
      key: "skills",
      label: label("skills"),
      items: payload.skills.map((item) => ({
        title: item.name,
        detail:
          item.level_claim != null
            ? t("intake.claimedLevel", { level: item.level_claim })
            : undefined,
        evidence: item.evidence,
      })),
    });
  }
  if (payload.languages.length) {
    views.push({
      key: "languages",
      label: label("languages"),
      items: payload.languages.map((item) => ({
        title: item.code.toUpperCase(),
        detail: item.level,
        evidence: item.evidence,
      })),
    });
  }
  if (payload.certifications.length) {
    views.push({
      key: "certifications",
      label: label("certifications"),
      items: payload.certifications.map((item) => ({
        title: item.name,
        detail: [item.issuer, item.issued].filter(Boolean).join(" · "),
        evidence: item.evidence,
      })),
    });
  }
  if (payload.awards.length) {
    views.push({
      key: "awards",
      label: label("awards"),
      items: payload.awards.map((item) => ({
        title: item.title,
        detail: [item.kind, item.issuer, item.date].filter(Boolean).join(" · "),
        evidence: item.evidence,
      })),
    });
  }
  if (payload.interests.length) {
    views.push({
      key: "interests",
      label: label("interests"),
      items: payload.interests.map((item) => ({
        title: item.label,
        evidence: item.evidence,
      })),
    });
  }
  return views;
}

function ConfidencePill({ evidence }: { evidence: FieldEvidence }) {
  const { t } = useTranslation();
  const tone =
    evidence.confidence >= 0.8 ? "high" : evidence.confidence >= 0.5 ? "medium" : "low";
  return (
    <span
      className={`cv-intake-pill cv-intake-pill-${tone}`}
      data-testid={`confidence-${tone}`}
      title={t("intake.confidenceTitle", {
        percent: (evidence.confidence * 100).toFixed(0),
      })}
    >
      {t(`intake.confidence.${tone}`)}
    </span>
  );
}

function Evidence({
  evidence,
  documentId,
}: {
  evidence: FieldEvidence;
  documentId?: string;
}) {
  const { t } = useTranslation();
  const [pageUrl, setPageUrl] = useState<string | null>(null);
  const [pageError, setPageError] = useState(false);
  const page = evidence.page;
  const canGround = documentId != null && page != null;
  if (!evidence.quote && page == null) return null;
  return (
    <div className="mt-1">
      {evidence.quote && (
        <p className="border-l-2 border-[var(--as-border)] pl-2 text-xs italic text-[var(--as-muted-fg)]">
          “{evidence.quote}”
          {page != null && <span className="not-italic"> — p.{page + 1}</span>}
        </p>
      )}
      {canGround && (
        <>
          <button
            type="button"
            className="mt-1 text-xs text-[var(--as-accent)] underline-offset-2 hover:underline"
            onClick={() => {
              if (page == null) return;
              if (pageUrl != null) {
                setPageUrl(null);
                return;
              }
              fetchCvPageImageUrl(documentId, page)
                .then(setPageUrl)
                .catch(() => setPageError(true));
            }}
            data-testid={`evidence-toggle-${page}`}
          >
            {pageUrl != null
              ? t("intake.hideSource")
              : t("intake.showSource", { page: page + 1 })}
          </button>
          {pageError && (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("intake.pageUnavailable")}
            </p>
          )}
          {pageUrl != null && (
            <img
              src={pageUrl}
              alt={t("intake.sourcePageAlt", { page: page + 1 })}
              className="mt-2 max-h-72 rounded-lg border border-[var(--as-border)]"
              data-testid={`evidence-page-${page}`}
            />
          )}
        </>
      )}
    </div>
  );
}

function sectionIndices(view: SectionView): number[] {
  return view.items.map((_, i) => i);
}

function isItemSelected(sel: CvSelections, view: SectionView, index: number): boolean {
  const entry = sel[view.key];
  if (entry === true) return true;
  return Array.isArray(entry) && entry.includes(index);
}

function sectionState(sel: CvSelections, view: SectionView) {
  const entry = sel[view.key];
  const count = view.items.length;
  const chosen =
    entry === true ? count : Array.isArray(entry) ? entry.length : 0;
  return { chosen, count, all: chosen === count, some: chosen > 0 && chosen < count };
}

/** Review-first suggestion list: grouped by section, one
 * checkbox per item, confidence pill + evidence quote for grounding.
 * With `documentId`, items can reveal their source page image (tracing).
 * Controlled: `selected`/`onChange` own the selections payload.
 * `readOnly` drops the checkboxes — a browse view of what was
 * extracted (per-CV detail), keeping pills + evidence grounding.
 * Status sections get a per-item Draft/Active chip: `draftAll` is the
 * global footer default, `draftItems` the per-item overrides. */
export function SuggestionReviewList({
  payload,
  selected,
  onChange,
  documentId,
  readOnly = false,
  draftItems,
  onDraftToggle,
  draftAll = false,
}: {
  payload: CvExtractPayload;
  selected: CvSelections;
  onChange: (next: CvSelections) => void;
  documentId?: string;
  readOnly?: boolean;
  draftItems?: Partial<Record<CvIntakeSection, number[]>>;
  onDraftToggle?: (section: CvIntakeSection, index: number) => void;
  draftAll?: boolean;
}) {
  const { t } = useTranslation();
  const views = sectionViews(payload);

  const toggleSection = (view: SectionView) => {
    const state = sectionState(selected, view);
    onChange({
      ...selected,
      [view.key]: state.all ? [] : sectionIndices(view),
    });
  };

  const toggleItem = (view: SectionView, index: number) => {
    if (isItemSelected(selected, view, index)) {
      const entry = selected[view.key];
      const rest =
        entry === true
          ? sectionIndices(view).filter((i) => i !== index)
          : (entry ?? []).filter((i) => i !== index);
      onChange({ ...selected, [view.key]: rest });
    } else {
      const entry = selected[view.key];
      const rest =
        entry === true ? sectionIndices(view) : [...(entry ?? []), index];
      onChange({ ...selected, [view.key]: rest });
    }
  };

  return (
    <div className="space-y-4" data-testid="suggestion-review">
      {views.map((view) => {
        const state = sectionState(selected, view);
        return (
          <section
            key={view.key}
            className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)]"
            data-testid={`intake-section-${view.key}`}
          >
            {readOnly ? (
              <div className="flex items-center gap-2.5 border-b border-[var(--as-border)] px-4 py-2.5">
                <span className="text-sm font-semibold text-[var(--as-fg)]">
                  {view.label}
                </span>
                <span className="text-xs text-[var(--as-muted-fg)]">
                  {state.count}
                </span>
              </div>
            ) : (
              <label className="flex items-center gap-2.5 border-b border-[var(--as-border)] px-4 py-2.5">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[var(--as-accent)]"
                  checked={state.all}
                  ref={(el) => {
                    if (el) el.indeterminate = state.some;
                  }}
                  onChange={() => toggleSection(view)}
                  aria-label={t("intake.importAll", { label: view.label.toLowerCase() })}
                  data-testid={`intake-section-toggle-${view.key}`}
                />
                <span className="text-sm font-semibold text-[var(--as-fg)]">
                  {view.label}
                </span>
                <span className="text-xs text-[var(--as-muted-fg)]">
                  {state.chosen}/{state.count}
                </span>
              </label>
            )}
            <ul>
              {view.items.map((item, index) => {
                const on = isItemSelected(selected, view, index);
                const statusRow =
                  !!onDraftToggle && isStatusSection(view.key) && !readOnly;
                const draftState = draftAll || draftItems?.[view.key]?.includes(index);
                return (
                  <li
                    key={`${view.key}-${index}`}
                    className={`flex items-start gap-2.5 px-4 py-2.5 ${
                      index > 0 ? "border-t border-[var(--as-border)]" : ""
                    } ${on || readOnly ? "" : "opacity-50"}`}
                    data-testid={`intake-item-${view.key}-${index}`}
                  >
                    {!readOnly && (
                      <CheckIndicator
                        checked={on}
                        onToggle={() => toggleItem(view, index)}
                        label={t("intake.importItem", { title: item.title })}
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-medium text-[var(--as-fg)]">
                          {item.title}
                        </p>
                        <ConfidencePill evidence={item.evidence} />
                        {statusRow && (
                          <button
                            type="button"
                            onClick={() => onDraftToggle?.(view.key, index)}
                            title={t("intake.statusToggleAria", { title: item.title })}
                            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                              draftState
                                ? "bg-amber-100 text-amber-700"
                                : "border border-[var(--as-border)] text-[var(--as-muted-fg)]"
                            }`}
                            data-testid={`draft-toggle-${view.key}-${index}`}
                          >
                            {t(
                              draftState
                                ? "intake.statusDraft"
                                : "intake.statusActive"
                            )}
                          </button>
                        )}
                      </div>
                      {item.detail && (
                        <p className="text-xs text-[var(--as-muted-fg)]">
                          {item.detail}
                        </p>
                      )}
                      <Evidence evidence={item.evidence} documentId={documentId} />
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
