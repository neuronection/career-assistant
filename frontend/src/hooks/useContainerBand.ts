import { useEffect, useRef, useState } from "react";

/** The page's own width band (plan 195 §3.6): the chat dock steals width
 * without moving the viewport, so the layout keys off the container. */
export type ContainerBand = "compact" | "medium" | "wide";

export const COMPACT_MAX_PX = 640;
export const MEDIUM_MAX_PX = 1024;

export function bandForWidth(width: number): ContainerBand {
  if (width < COMPACT_MAX_PX) return "compact";
  if (width < MEDIUM_MAX_PX) return "medium";
  return "wide";
}

export function useContainerBand(override?: ContainerBand) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [measured, setMeasured] = useState<ContainerBand>("wide");

  useEffect(() => {
    if (override) return;
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width !== undefined) setMeasured(bandForWidth(width));
    });
    observer.observe(node);
    setMeasured(bandForWidth(node.getBoundingClientRect().width || window.innerWidth));
    return () => observer.disconnect();
  }, [override]);

  return { ref, band: override ?? measured };
}
