import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { BLOCK_TYPES, type BlockTypeSpec } from "@/components/cv/blockTypes";
import { type CvArea, type CvAreaId } from "@/components/cv/areas";
import { SegmentedRow } from "@/components/cv/formPrimitives";

const bar = "block h-1 rounded-full bg-[var(--as-border)]";
const dot = "block h-1.5 w-1.5 rounded-full bg-[var(--as-accent)]";

function TypePreview({ value }: { value: string }) {
  return (
    <div
      aria-hidden
      className="flex h-9 w-16 shrink-0 flex-col justify-center gap-1 overflow-hidden rounded-md border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-1.5"
      data-testid={`block-preview-${value}`}
    >
      {value === "summary" && (
        <>
          <span className={bar} style={{ width: "100%" }} />
          <span className={bar} style={{ width: "80%" }} />
          <span className={bar} style={{ width: "60%" }} />
        </>
      )}
      {value === "header" && (
        <>
          <span className="block h-2 w-1/2 rounded-sm bg-[var(--as-accent)] opacity-70" />
          <span className={bar} style={{ width: "85%" }} />
        </>
      )}
      {value === "items" && (
        <>
          <span className="flex items-center gap-1">
            <span className={dot} />
            <span className={`${bar} flex-1`} />
          </span>
          <span className={`${bar} ml-2.5`} style={{ width: "70%" }} />
          <span className="flex items-center gap-1">
            <span className={dot} />
            <span className={`${bar} flex-1`} />
          </span>
        </>
      )}
      {value === "skills" && (
        <span className="flex flex-wrap gap-1">
          {[10, 8, 12].map((w, i) => (
            <span
              key={i}
              className="rounded-full border border-[var(--as-border)]"
              style={{ width: w * 2, height: 6 }}
            />
          ))}
        </span>
      )}
      {value === "languages" && (
        <>
          <span className="flex items-center gap-1">
            <span className={dot} />
            <span className={`${bar} flex-1`} />
          </span>
          <span className="flex items-center gap-1">
            <span className="block h-1.5 w-1.5 rounded-full bg-[var(--as-border)]" />
            <span className={`${bar} flex-1`} />
          </span>
        </>
      )}
      {value === "achievements" && (
        <>
          <span className="flex items-center gap-1">
            <span className={dot} />
            <span className={`${bar} flex-1`} />
          </span>
          <span className={`${bar}`} style={{ width: "75%" }} />
        </>
      )}
      {value === "interests" && (
        <span className="flex flex-wrap gap-1">
          {[9, 12, 7].map((w, i) => (
            <span
              key={i}
              className="rounded-full border border-[var(--as-border)]"
              style={{ width: w * 2, height: 6 }}
            />
          ))}
        </span>
      )}
      {value === "custom_text" && (
        <>
          <span className={bar} style={{ width: "90%" }} />
          <span className={bar} style={{ width: "65%" }} />
          <span className="block h-1 w-6 rounded-full bg-[var(--as-accent)] opacity-60" />
        </>
      )}
      {value === "spacer" && (
        <span className="block h-2 w-full rounded-sm border border-dashed border-[var(--as-border)]" />
      )}
      {value === "synth_items" && (
        <>
          <span className="flex items-center gap-1">
            <span className={dot} />
            <span className={`${bar} flex-1`} />
          </span>
          <span className={`${bar} ml-2.5`} style={{ width: "65%" }} />
          <span className="flex gap-1">
            {[8, 6, 7].map((w, i) => (
              <span
                key={i}
                className="rounded-full border border-[var(--as-border)]"
                style={{ width: w * 2, height: 6 }}
              />
            ))}
          </span>
        </>
      )}
    </div>
  );
}

function TypeCard({ spec, onAdd }: { spec: BlockTypeSpec; onAdd: (kind: string) => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={() => onAdd(spec.value)}
      data-testid={`add-block-${spec.value}`}
      className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-left transition-colors duration-150 hover:border-[var(--as-accent)] hover:bg-[var(--as-surface-raised)]"
    >
      <TypePreview value={spec.value} />
      <span className="flex min-w-0 flex-col">
        <span className="flex items-center gap-1.5 text-sm font-medium text-[var(--as-fg)]">
          <spec.icon className="h-3.5 w-3.5 text-[var(--as-accent)]" aria-hidden />
          {t(spec.label, { defaultValue: spec.label })}
        </span>
        <span className="text-xs leading-snug text-[var(--as-muted-fg)]">
          {t(spec.description, { defaultValue: spec.description })}
        </span>
      </span>
    </button>
  );
}

export function BlockTypePicker({
  onAdd,
  extraTypes = [],
  areas,
  presetArea,
  testId = "add-section-button",
}: {
  onAdd: (kind: string, area?: CvAreaId) => void;
  extraTypes?: BlockTypeSpec[];
  areas?: CvArea[];
  presetArea?: CvAreaId;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [targetArea, setTargetArea] = useState<CvAreaId>("main");
  const types = [...BLOCK_TYPES, ...extraTypes];
  const grouped = Boolean(areas && areas.length > 1);
  const effectiveArea = presetArea
    ? presetArea
    : grouped
      ? areas!.some((area) => area.id === targetArea)
        ? targetArea
        : areas![0].id
      : undefined;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid={testId}
          aria-expanded={open}
          className="inline-flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-xs font-medium text-[var(--as-muted-fg)] transition-colors duration-150 hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Add section
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-80 space-y-1.5"
        data-testid="add-section-menu"
      >
        <p className="px-0.5 pb-0.5 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
          Section type
        </p>
        <div className="grid max-h-72 grid-cols-1 gap-1.5 overflow-y-auto">
          {types.map((spec) => (
            <TypeCard
              key={spec.value}
              spec={spec}
              onAdd={(kind) => {
                onAdd(kind, effectiveArea);
                setOpen(false);
              }}
            />
          ))}
        </div>
        {grouped && !presetArea && (
          <div className="border-t border-[var(--as-border)] pt-1.5">
            <SegmentedRow
              label="Add to"
              value={effectiveArea!}
              options={areas!.map((area) => ({ value: area.id, label: area.label }))}
              onChange={(area) => setTargetArea(area as CvAreaId)}
            />
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
