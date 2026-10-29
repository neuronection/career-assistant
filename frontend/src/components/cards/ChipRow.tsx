import { useLayoutEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui";
import { SkillTag } from "@/components/skills/SkillTag";
import { CHIP_VARIANT, type ChipItem } from "./chipTone";

const GAP = 4;

export function rowsFor(widths: number[], containerWidth: number, gap = GAP): number {
  if (containerWidth <= 0 || widths.length === 0) return 1;
  let rows = 1;
  let x = 0;
  for (const width of widths) {
    const add = x === 0 ? width : gap + width;
    if (x > 0 && x + add > containerWidth) {
      rows += 1;
      x = width;
    } else {
      x += add;
    }
  }
  return rows;
}

export function fitChips(
  widths: number[],
  containerWidth: number,
  gap: number,
  moreWidth: number,
  rows = 2
): number {
  if (widths.length === 0) return 0;
  if (containerWidth <= 0) return widths.length;
  if (rowsFor(widths, containerWidth, gap) <= rows) return widths.length;
  for (let n = widths.length - 1; n >= 1; n -= 1) {
    if (rowsFor([...widths.slice(0, n), moreWidth], containerWidth, gap) <= rows) return n;
  }
  return 0;
}

function Chip({
  item,
  testId,
  variant,
}: {
  item: ChipItem;
  testId?: string;
  variant: "badge" | "skill";
}) {
  if (variant === "skill") {
    return (
      <SkillTag
        label={item.label}
        score={item.score}
        unmapped={item.unmapped}
        title={item.title}
        testId={testId}
        onOpen={item.onOpen}
      />
    );
  }
  const Icon = item.icon;
  return (
    <Badge
      variant={CHIP_VARIANT[item.tone ?? "neutral"]}
      title={item.title}
      data-testid={testId}
    >
      {Icon ? <Icon aria-hidden /> : null}
      {item.label}
    </Badge>
  );
}

export interface ChipMeasure {
  widths: number[];
  containerWidth: number;
  moreWidth: number;
}

export function ChipRow({
  items,
  max,
  clampRows = 0,
  measure,
  moreLabel,
  moreAriaLabel,
  showLessLabel,
  testId,
  itemTestId,
  variant = "badge",
  className = "",
}: {
  items: ChipItem[];
  max?: number;
  clampRows?: 0 | 2;
  /** Test seam: jsdom has no layout, so clamp tests inject measured widths. */
  measure?: ChipMeasure;
  variant?: "badge" | "skill";
  moreLabel?: (count: number) => string;
  moreAriaLabel?: (count: number) => string;
  showLessLabel?: string;
  testId?: string;
  itemTestId?: string;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [measured, setMeasured] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const itemKey = items.map((item) => item.label).join("\u0000");

  useLayoutEffect(() => {
    if (!clampRows || expanded || measure) return;
    const wrap = wrapRef.current;
    const measureRoot = measureRef.current;
    if (!wrap || !measureRoot) return;
    const compute = () => {
      const containerWidth = wrap.clientWidth;
      if (!containerWidth) {
        setMeasured(items.length);
        return;
      }
      const chips = Array.from(
        measureRoot.querySelectorAll<HTMLElement>("[data-measure-chip]")
      );
      const widths = chips.map((chip) => chip.getBoundingClientRect().width);
      const more = measureRoot.querySelector<HTMLElement>("[data-measure-more]");
      const moreWidth = more ? more.getBoundingClientRect().width : 34;
      setMeasured(fitChips(widths, containerWidth, GAP, moreWidth, clampRows));
    };
    compute();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(compute);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [itemKey, items.length, expanded, clampRows, measure]);

  const cap = max == null ? items.length : Math.min(items.length, max);
  const injected =
    clampRows && measure && !expanded
      ? fitChips(measure.widths, measure.containerWidth, GAP, measure.moreWidth, clampRows)
      : null;
  const limit = expanded
    ? items.length
    : clampRows
      ? Math.min(cap, injected ?? measured ?? items.length)
      : cap;
  const shown = items.slice(0, limit);
  const hiddenItems = items.slice(limit);
  const hidden = hiddenItems.length;
  const hiddenLabels = hiddenItems.map((item) => item.label).join(", ");
  const moreText = moreLabel ? moreLabel(hidden) : `+${hidden}`;
  const canCollapse = expanded && (max != null || clampRows > 0);

  return (
    <div className={`relative ${className}`}>
      <div
        ref={wrapRef}
        className="flex flex-wrap items-center gap-1"
        data-testid={testId}
      >
        {shown.map((item) => (
          <Chip
            key={item.key}
            item={item}
            testId={itemTestId}
            variant={variant}
          />
        ))}
        {hidden > 0 && (
          <button
            type="button"
            className="rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--as-focus-ring)]"
            onClick={(event) => {
              event.stopPropagation();
              setExpanded(true);
            }}
            aria-label={moreAriaLabel ? moreAriaLabel(hidden) : moreText}
            title={hiddenLabels}
            data-testid={testId ? `${testId}-more` : "chip-row-more"}
          >
            <Badge variant="outline">{moreText}</Badge>
          </button>
        )}
        {canCollapse && showLessLabel ? (
          <button
            type="button"
            className="rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--as-focus-ring)]"
            onClick={(event) => {
              event.stopPropagation();
              setExpanded(false);
            }}
            data-testid={testId ? `${testId}-less` : "chip-row-less"}
          >
            <Badge variant="outline">{showLessLabel}</Badge>
          </button>
        ) : null}
        {hidden > 0 ? <span className="sr-only">{hiddenLabels}</span> : null}
      </div>
      {clampRows ? (
        <div
          ref={measureRef}
          aria-hidden
          className="invisible pointer-events-none absolute inset-x-0 top-0 flex flex-wrap items-center gap-1"
        >
          {items.map((item) => (
            <span key={`measure-${item.key}`} data-measure-chip>
              <Chip item={item} variant={variant} />
            </span>
          ))}
          <span data-measure-more>
            <Badge variant="outline">
              {moreLabel ? moreLabel(items.length) : `+${items.length}`}
            </Badge>
          </span>
        </div>
      ) : null}
    </div>
  );
}
