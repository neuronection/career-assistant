import { useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * First-page thumbnail for CV listing cards: the engine-rendered
 * `preview.png` (disk-cached server-side by render hash) as a plain
 * `<img>` — same precedent as the chat template preview strip. `stamp`
 * (the CV's updated_at epoch) busts the browser cache after edits;
 * a missing print engine degrades to the placeholder, never an error.
 */
export function CvThumbnail({ cvId, stamp }: { cvId: string; stamp: number }) {
  const { t } = useTranslation();
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  return (
    <div
      className="relative w-20 shrink-0 self-center overflow-hidden rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)]"
      data-testid="cv-card-thumbnail"
      data-thumbnail-state={state}
    >
      <div
        aria-hidden
        className={`aspect-[210/297] w-full ${state === "loading" ? "cv-shimmer" : ""}`}
      />
      {state !== "error" && (
        <img
          src={`/api/v1/cv/${cvId}/preview.png?v=${stamp}`}
          alt={t("cvStudio.thumbnailAlt")}
          className="absolute inset-0 h-full w-full object-cover object-top"
          loading="lazy"
          decoding="async"
          onLoad={() => setState("ready")}
          onError={() => setState("error")}
        />
      )}
    </div>
  );
}
