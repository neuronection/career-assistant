import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { Button } from "@/components/ui";
import { setPostingGateOverride } from "@/api/postings";
import { apiDetail } from "@/api/client";
import type { PostingDetailOut } from "@/types/wire";

type Gate = "visa" | "language" | "grade";

const GATE_LABEL: Record<Gate, string> = {
  visa: "postingDetail.eligibility.gate.visa",
  language: "postingDetail.eligibility.gate.language",
  grade: "postingDetail.eligibility.gate.grade",
};

function statusLabel(t: TFunction, status: string): string {
  return t(`postingDetail.eligibility.workAuthorization.${status}`, { defaultValue: status });
}

export function EligibilityCard({ posting }: { posting: PostingDetailOut }) {
  const { t } = useTranslation();
  const [overrides, setOverrides] = useState<Record<string, boolean>>(
    posting.gate_overrides ?? {},
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  const extract = posting.extract ?? null;
  const work = extract?.work_authorization ?? null;
  const languages = extract?.language_requirements ?? [];
  const grade = extract?.grade_requirement ?? null;
  const present = ((posting.match?.gates ?? []) as string[]).filter(
    (gate): gate is Gate => gate === "visa" || gate === "language" || gate === "grade",
  );
  const gates: Gate[] = (["visa", "language", "grade"] as Gate[]).filter(
    (gate) => present.includes(gate) || overrides[gate] === true,
  );
  const hasFacts =
    work != null ||
    languages.length > 0 ||
    grade != null ||
    posting.opportunity_type != null ||
    posting.application_deadline != null;

  if (!hasFacts && gates.length === 0) return null;

  async function toggle(gate: Gate, allow: boolean) {
    setBusy(gate);
    setError("");
    try {
      const result = await setPostingGateOverride(posting.ref, gate, allow);
      setOverrides(result.gate_overrides ?? {});
    } catch (exc) {
      setError(apiDetail(exc));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4 space-y-3"
      data-testid="eligibility-card"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-[var(--as-fg)]">
          {t("postingDetail.eligibility.heading")}
        </h2>
        <span className="text-[11px] text-[var(--as-muted-fg)]">
          {t("postingDetail.eligibility.honesty")}
        </span>
      </div>

      {error !== "" && (
        <p className="text-xs text-[var(--as-danger)]" role="alert" data-testid="eligibility-error">
          {error}
        </p>
      )}

      {work && (
        <div className="space-y-1" data-testid="eligibility-work-authorization">
          <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--as-fg)]">
            <span className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("postingDetail.eligibility.workAuthorizationLabel")}
            </span>
            <span className="font-medium">{statusLabel(t, work.status)}</span>
          </div>
          {work.evidence_quote && (
            <blockquote className="text-xs text-[var(--as-muted-fg)] border-l-2 border-[var(--as-border)] pl-2">
              “{work.evidence_quote}”
            </blockquote>
          )}
        </div>
      )}

      {languages.length > 0 && (
        <div className="space-y-1" data-testid="eligibility-languages">
          <div className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("postingDetail.eligibility.languagesLabel")}
          </div>
          <ul className="space-y-1">
            {languages.map((row) => (
              <li key={`${row.code}-${row.level}`} className="text-sm text-[var(--as-fg)]">
                <span className="font-medium">{row.code}</span>{" "}
                <span className="text-[var(--as-muted-fg)]">
                  {t(`postingDetail.eligibility.level.${row.level}`, {
                    defaultValue: row.level,
                  })}
                </span>
                {row.evidence_quote && (
                  <span className="block text-xs text-[var(--as-muted-fg)]">“{row.evidence_quote}”</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {grade && (
        <div className="space-y-1" data-testid="eligibility-grade">
          <div className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("postingDetail.eligibility.gradeLabel")}
          </div>
          <div className="text-sm text-[var(--as-fg)]">
            {t(`postingDetail.eligibility.gradeScale.${grade.scale}`, {
              defaultValue: grade.scale,
            })}{" "}
            <span className="font-medium">{grade.value}</span>
          </div>
          {grade.evidence_quote && (
            <blockquote className="text-xs text-[var(--as-muted-fg)] border-l-2 border-[var(--as-border)] pl-2">
              “{grade.evidence_quote}”
            </blockquote>
          )}
        </div>
      )}

      {(posting.opportunity_type != null || posting.application_deadline != null) && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-[var(--as-fg)]">
          {posting.opportunity_type && (
            <span data-testid="eligibility-opportunity-type">
              <span className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)] mr-1">
                {t("postingDetail.eligibility.opportunityTypeLabel")}
              </span>
              {t(`postingDetail.eligibility.opportunityType.${posting.opportunity_type}`, {
                defaultValue: posting.opportunity_type,
              })}
            </span>
          )}
          {posting.application_deadline != null && (
            <span data-testid="eligibility-deadline">
              <span className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)] mr-1">
                {t("postingDetail.eligibility.deadlineLabel")}
              </span>
              {posting.application_deadline}
            </span>
          )}
        </div>
      )}

      {gates.length > 0 && (
        <div className="space-y-2 border-t border-[var(--as-border)] pt-3">
          <div className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("postingDetail.eligibility.gatesLabel")}
          </div>
          {gates.map((gate) => {
            const overridden = overrides[gate] === true;
            return (
              <div
                key={gate}
                className="flex flex-wrap items-center justify-between gap-2 text-sm"
                data-testid={`eligibility-gate-${gate}`}
              >
                <span className="text-[var(--as-fg)]">{t(GATE_LABEL[gate])}</span>
                {overridden ? (
                  <span className="flex items-center gap-2">
                    <span className="text-xs text-emerald-700">
                      {t("postingDetail.eligibility.overridden")}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy === gate}
                      data-testid={`eligibility-undo-${gate}`}
                      onClick={() => void toggle(gate, false)}
                    >
                      {t("postingDetail.eligibility.undo")}
                    </Button>
                  </span>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy === gate}
                    data-testid={`eligibility-override-${gate}`}
                    onClick={() => void toggle(gate, true)}
                  >
                    {t("postingDetail.eligibility.applyAnyway")}
                  </Button>
                )}
              </div>
            );
          })}
          <p className="text-[11px] text-[var(--as-muted-fg)]">
            {t("postingDetail.eligibility.gateHint")}
          </p>
        </div>
      )}
    </section>
  );
}
