import { Bookmark, Briefcase, CalendarClock, Compass, GraduationCap, Plane } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui";
import { CardMeta, type MetaItem } from "@/components/cards/CardMeta";
import { CardSpec } from "@/components/cards/CardSpec";
import { ChipRow } from "@/components/cards/ChipRow";
import { ItemCardShell, type CardDensity } from "@/components/cards/ItemCardShell";
import { SeenMark } from "@/components/cards/CardState";
import type { SpecItem } from "@/components/cards/specOrder";
import { SkillPeekModal, useSkillPeek } from "@/components/skills/SkillPeekModal";
import { DemandBadge } from "@/features/postings/components/DemandBadge";
import type { Job } from "@/types/wire";

export const EDUCATION_CHIP: Record<string, string> = {
  no_formal: "education.chip.no_formal",
  middle_school: "education.chip.middle_school",
  high_school: "education.chip.high_school",
  vocational: "education.chip.vocational",
  bachelor: "education.chip.bachelor",
  master: "education.chip.master",
  doctorate: "education.chip.doctorate",
};

export function educationChipLabel(
  t: (key: string, opts?: Record<string, unknown>) => string,
  level: string
): string {
  return t(EDUCATION_CHIP[level] ?? level, { defaultValue: level });
}

function compactAmount(value: number): string {
  return Math.abs(value) >= 10000
    ? `${Math.round(value / 1000)}k`
    : new Intl.NumberFormat().format(value);
}

function salaryBand(job: Job): string | null {
  const salary = job.attributes?.salary;
  const range = salary?.median ?? salary?.entry ?? salary?.senior;
  if (!salary || !range) return null;
  const [low, high] = range;
  const amount = low === high ? compactAmount(low) : `${compactAmount(low)}–${compactAmount(high)}`;
  return salary.currency ? `${salary.currency} ${amount}` : amount;
}

export function JobCard({
  job,
  onSelect,
  seen = false,
  saved = false,
  notes,
  exploration = false,
  density = "full",
}: {
  job: Job;
  onSelect?: (job: Job) => void;
  seen?: boolean;
  saved?: boolean;
  notes?: string;
  exploration?: boolean;
  density?: CardDensity;
}) {
  const { t } = useTranslation();
  const peek = useSkillPeek();
  const compact = density === "compact";
  const attributes = job.attributes;
  const education = attributes?.education?.level;
  const salary = salaryBand(job);
  const openRoles = job.open_roles ?? null;
  const familyRef = job.family_label || job.family_key;

  const workStyle = attributes?.work_style;
  const physical = attributes?.physical?.activity ?? workStyle?.physical_activity;
  const experience = attributes?.experience_typical_years;
  const contract = attributes?.contract_type;
  const travel = attributes?.travel_required?.level;
  const schedule = (attributes?.schedule_cues ?? []).map((cue) =>
    t(`catalog.facetValue.${cue}`, { defaultValue: cue.replace(/_/g, " ") })
  );
  const hours = attributes?.work_hours;
  const hoursText = hours
    ? [
        t(`jobCard.pattern.${hours.pattern}`, { defaultValue: hours.pattern.replace(/_/g, " ") }),
        hours.hours_per_week_min != null && hours.hours_per_week_max != null
          ? t("jobCard.hoursRange", {
              min: hours.hours_per_week_min,
              max: hours.hours_per_week_max,
            })
          : hours.hours_per_week_min != null
            ? t("jobCard.hoursSingle", { hours: hours.hours_per_week_min })
            : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : null;

  const meta: MetaItem[] = [];
  if (education) {
    meta.push({
      key: "education",
      icon: GraduationCap,
      text: educationChipLabel(t, education),
      testId: "education-chip",
    });
  }
  if (experience) {
    meta.push({
      key: "experience",
      icon: Briefcase,
      text:
        experience[0] === experience[1]
          ? t("jobCard.experienceSingle", { years: experience[0] })
          : t("jobCard.experienceRange", { min: experience[0], max: experience[1] }),
      testId: "job-experience",
    });
  }
  if (contract) {
    meta.push({
      key: "contract",
      icon: Briefcase,
      text: t(`catalog.facetValue.${contract}`, { defaultValue: contract }),
      testId: "job-contract",
    });
  }
  if (travel) {
    meta.push({
      key: "travel",
      icon: Plane,
      text: t(`catalog.facetValue.${travel}`, { defaultValue: travel }),
      testId: "job-travel",
    });
  }
  if (schedule.length > 0) {
    meta.push({
      key: "schedule",
      icon: CalendarClock,
      text: schedule.join(", "),
      testId: "job-schedule",
    });
  }
  if (hoursText) {
    meta.push({
      key: "hours",
      icon: CalendarClock,
      text: hoursText,
      testId: "job-hours",
    });
  }

  const spec: SpecItem[] = [];
  if (physical) {
    spec.push({
      key: "physical",
      label: t("jobCard.physical"),
      value: t(`jobCard.activity.${physical}`, { defaultValue: physical.replace(/_/g, " ") }),
    });
  }
  if (workStyle?.teamwork != null) {
    spec.push({ key: "teamwork", label: t("jobCard.teamwork"), value: `${workStyle.teamwork}/5` });
  }
  if (workStyle?.structure != null) {
    spec.push({
      key: "structure",
      label: t("jobCard.structure"),
      value: `${workStyle.structure}/5`,
    });
  }

  return (
    <ItemCardShell
      testId="job-card"
      density={density}
      onOpen={onSelect ? () => onSelect(job) : undefined}
      seen={seen}
      className="w-full text-left"
    >
      {!compact && (openRoles != null || salary) ? (
        <div
          className="flex w-20 shrink-0 flex-col items-center gap-1.5 border-r border-[var(--as-border)] pr-3 text-center"
          data-testid="job-metric-rail"
        >
          {openRoles != null ? (
            <div data-testid="job-open-roles">
              <span className="block text-xl font-semibold tabular-nums text-[var(--as-fg)]">
                {openRoles}
              </span>
              <span className="block text-[9px] font-semibold uppercase tracking-[0.07em] text-[var(--as-muted-fg)]">
                {t("jobCard.openRolesShort")}
              </span>
            </div>
          ) : null}
          {salary ? (
            <span
              className="text-[11px] font-medium text-[var(--as-muted-fg)]"
              data-testid="job-salary-band"
            >
              {salary}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <button
            type="button"
            data-testid="job-title"
            className="min-w-0 truncate text-left font-medium text-[var(--as-fg)] hover:text-[var(--as-accent)]"
          >
            {job.title}
          </button>
          <div className="flex shrink-0 items-center gap-1.5">
            {compact && (openRoles != null || salary) ? (
              <div
                className="flex items-center gap-2 text-[11px] text-[var(--as-muted-fg)]"
                data-testid="job-metric-rail"
              >
                {openRoles != null ? (
                  <span
                    className="inline-flex items-baseline gap-1 font-semibold tabular-nums text-[var(--as-fg)]"
                    data-testid="job-open-roles"
                  >
                    {openRoles}
                    <span className="text-[9px] font-semibold uppercase tracking-[0.07em]">
                      {t("jobCard.openRolesShort")}
                    </span>
                  </span>
                ) : null}
                {salary ? (
                  <span className="font-medium" data-testid="job-salary-band">
                    {salary}
                  </span>
                ) : null}
              </div>
            ) : null}
            {seen ? <SeenMark label={t("jobCard.seen")} testId="job-seen" /> : null}
            {saved ? (
              <Bookmark
                aria-hidden
                className="h-3.5 w-3.5 fill-current text-[var(--as-accent)]"
              />
            ) : null}
            <DemandBadge outlook={attributes?.demand?.outlook} />
            {exploration ? (
              <Badge variant="ai">
                <Compass aria-hidden /> {t("jobCard.explore")}
              </Badge>
            ) : null}
          </div>
        </div>
        {familyRef ? (
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="job-family">
            {familyRef}
          </p>
        ) : null}

        {!compact ? (
          <p className="mt-1 line-clamp-2 text-sm text-[var(--as-muted-fg)]">
            {job.short_description}
          </p>
        ) : null}
        {notes ? (
          <p
            className="mt-1 line-clamp-1 text-xs italic text-[var(--as-muted-fg)]"
            data-testid="job-card-notes"
          >
            {notes}
          </p>
        ) : null}

        <CardMeta className="mt-1" items={meta} testId="job-meta" />
        {!compact ? <CardSpec className="mt-1.5" items={spec} testId="job-spec" /> : null}

        {(job.skills ?? []).length > 0 ? (
          <div className="mt-2">
            <p className="mb-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
              {t("card.skills")}
            </p>
            <ChipRow
              variant="skill"
              clampRows={2}
              testId="job-skills"
              itemTestId="skill-tag"
              items={(job.skills ?? []).map((skill) => ({
                key: skill.key,
                label: skill.label,
                score: skill.required_level,
                title:
                  skill.required_level != null
                    ? t("card.skillRequires", { level: skill.required_level })
                    : undefined,
                onOpen: (trigger) =>
                  peek.open(skill.key, trigger, skill.required_level ?? null),
              }))}
              moreLabel={(count) => t("card.more", { count })}
              moreAriaLabel={(count) => t("card.moreAria", { count })}
              showLessLabel={t("card.showLess")}
            />
          </div>
        ) : null}

        {!compact && (job.interests ?? []).length > 0 ? (
          <div className="mt-1.5">
            <ChipRow
              testId="job-interests"
              clampRows={2}
              max={3}
              moreLabel={(count) => t("card.more", { count })}
              moreAriaLabel={(count) => t("card.moreAria", { count })}
              showLessLabel={t("card.showLess")}
              items={(job.interests ?? []).map((interest) => ({
                key: interest.key,
                label: interest.label,
              }))}
            />
          </div>
        ) : null}

        <div
          className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-[var(--as-muted-fg)]"
          data-testid="job-footer"
        >
          {familyRef ? <span>{familyRef}</span> : null}
          {job.source ? (
            <>
              <span className="text-[var(--as-border)]">|</span>
              <span data-testid="job-source">
                {t(`jobCard.source.${job.source}`, { defaultValue: job.source })}
              </span>
            </>
          ) : null}
          {openRoles != null ? (
            <>
              <span className="text-[var(--as-border)]">|</span>
              <Link
                to={`/postings?job=${encodeURIComponent(job.code)}`}
                onClick={(event) => event.stopPropagation()}
                className="text-[var(--as-accent)] hover:underline"
                data-testid="job-open-roles-link"
              >
                {t("jobCard.openRolesLink", { count: openRoles })}
              </Link>
            </>
          ) : null}
        </div>
      </div>

      <SkillPeekModal
        skillKey={peek.skillKey}
        highlightLevel={peek.highlightLevel}
        onClose={peek.close}
        returnFocusRef={peek.returnFocusRef}
      />
    </ItemCardShell>
  );
}
