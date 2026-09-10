import { useCallback, useEffect, useRef, useState } from "react";
import { Maximize, Minus, Plus } from "lucide-react";
import { Card } from "@/components/ui";

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const PAGE_WIDTHS_PX = { a4: 794, letter: 816 } as const;

type PageSize = keyof typeof PAGE_WIDTHS_PX;
type ZoomMode = "fit" | "manual";

function stepAbove(value: number): number {
  return (
    ZOOM_STEPS.find((step) => step > value + 1e-9) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1]
  );
}

function stepBelow(value: number): number {
  return (
    [...ZOOM_STEPS].reverse().find((step) => step < value - 1e-9) ?? ZOOM_STEPS[0]
  );
}

export function PreviewCanvas({
  html,
  loading,
  pageSize = "a4",
}: {
  html: string;
  loading: boolean;
  pageSize?: PageSize;
}) {
  const pageWidthPx = PAGE_WIDTHS_PX[pageSize] ?? PAGE_WIDTHS_PX.a4;
  const [zoom, setZoom] = useState(1);
  const [mode, setMode] = useState<ZoomMode>("fit");
  const frameHostRef = useRef<HTMLDivElement>(null);
  const modeRef = useRef<ZoomMode>("fit");
  const fitScaleRef = useRef(1);

  const enterFitMode = useCallback(() => {
    const width = frameHostRef.current?.clientWidth ?? 0;
    const scale = width > 0 ? width / pageWidthPx : 1;
    fitScaleRef.current = scale;
    modeRef.current = "fit";
    setMode("fit");
    setZoom(scale);
  }, [pageWidthPx]);

  const trackHostWidth = useCallback(() => {
    const width = frameHostRef.current?.clientWidth ?? 0;
    if (width <= 0) return;
    fitScaleRef.current = width / pageWidthPx;
    if (modeRef.current === "fit") {
      setZoom(fitScaleRef.current);
    }
  }, [pageWidthPx]);

  useEffect(() => {
    enterFitMode();
    if (!frameHostRef.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(trackHostWidth);
    observer.observe(frameHostRef.current);
    return () => observer.disconnect();
  }, [enterFitMode, trackHostWidth]);

  const manualStep = (direction: "in" | "out") => {
    const base = modeRef.current === "fit" ? fitScaleRef.current : zoom;
    modeRef.current = "manual";
    setMode("manual");
    setZoom(direction === "in" ? stepAbove(base) : stepBelow(base));
  };

  return (
    <Card className="flex min-h-0 flex-1 flex-col p-3">
      <div ref={frameHostRef} className="relative min-h-0 flex-1 overflow-auto" data-testid="canvas-viewport">
        <div
          className="absolute left-0 top-0 h-full w-full"
          style={{
            transform: `scale(${zoom})`,
            transformOrigin: "top left",
            width: `${100 / zoom}%`,
            height: `${100 / zoom}%`,
          }}
        >
          <iframe
            title="CV preview"
            srcDoc={html}
            sandbox=""
            className="h-full w-full rounded border border-[var(--as-border)] bg-white"
            data-testid="preview-frame"
          />
          {loading && (
            <div
              aria-hidden
              className="cv-shimmer absolute inset-0 rounded border border-[var(--as-border)]"
              data-testid="preview-skeleton"
            />
          )}
        </div>
      </div>
      <div
        className="mx-auto mt-2 flex shrink-0 items-center gap-1 rounded-full border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-1 py-0.5 shadow-sm"
        role="group"
        aria-label="Preview zoom"
        data-testid="zoom-bar"
      >
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() => manualStep("out")}
          disabled={zoom <= ZOOM_STEPS[0]}
          data-testid="zoom-out"
          className="cursor-pointer rounded-full p-1.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:pointer-events-none disabled:opacity-40"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <span className="min-w-12 text-center text-xs font-medium tabular-nums" data-testid="zoom-label">
          {Math.round(zoom * 100)}%
        </span>
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() => manualStep("in")}
          disabled={zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1]}
          data-testid="zoom-in"
          className="cursor-pointer rounded-full p-1.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:pointer-events-none disabled:opacity-40"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <span aria-hidden className="mx-0.5 h-4 w-px bg-[var(--as-border)]" />
        <button
          type="button"
          aria-label="Fit to width"
          aria-pressed={mode === "fit"}
          onClick={enterFitMode}
          data-testid="zoom-fit"
          title="Fit to width"
          className={`cursor-pointer rounded-full p-1.5 transition-colors ${
            mode === "fit"
              ? "bg-[var(--as-muted)] text-[var(--as-fg)]"
              : "text-[var(--as-muted-fg)] hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
          }`}
        >
          <Maximize className="h-3.5 w-3.5" />
        </button>
      </div>
    </Card>
  );
}
