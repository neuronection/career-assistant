import { useEffect, useRef, useState, type JSX } from "react";
import { useTranslation } from "react-i18next";

import { getUpdateCheck, type UpdateCheck } from "@/api/version";

let updateCheckPromise: Promise<UpdateCheck | null> | null = null;

/** Fetched once per app boot from the public update-check endpoint and
 * cached so the badge never refetches; a failure reads as "no update". */
export function loadUpdateCheck(): Promise<UpdateCheck | null> {
  if (updateCheckPromise === null) {
    updateCheckPromise = getUpdateCheck().catch(() => null);
  }
  return updateCheckPromise;
}

export function clearUpdateCheckCache(): void {
  updateCheckPromise = null;
}

/** Discreet update indicator around the sidebar version text (ADR-0048:
 * check-only — the dot is a status, not an interruption; there is nothing
 * to dismiss and it clears itself once the app is on the offered
 * version). Click opens a popover with the release links. */
export function UpdateBadge({
  version,
  className = "text-[11px]",
}: {
  version: string;
  className?: string;
}): JSX.Element {
  const { t } = useTranslation();
  const [check, setCheck] = useState<UpdateCheck | null>(null);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let alive = true;
    void loadUpdateCheck().then((value) => {
      if (alive) setCheck(value);
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const latest = check?.update_available ? check.latest_version : null;

  return (
    <span ref={rootRef} className="relative inline-flex items-center">
      <button
        type="button"
        aria-expanded={open}
        title={latest ? t("update.tooltip", { version: latest }) : undefined}
        onClick={() => setOpen((value) => !value)}
        className={`relative inline-flex items-center rounded font-medium text-slate-500 transition-colors hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 ${className}`}
      >
        v{version}
        {latest !== null && (
          <span
            aria-hidden
            className="absolute -right-1 -top-0.5 size-1.5 rounded-full bg-primary-600"
          />
        )}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={t("update.title")}
          className="absolute bottom-full left-0 z-50 mb-2 w-56 rounded-[var(--as-radius)] border border-slate-200 bg-white p-3 text-left shadow-lg"
        >
          <p className="text-xs font-semibold text-slate-900">
            {latest ? t("update.tooltip", { version: latest }) : `v${version}`}
          </p>
          <div className="mt-2 flex flex-col gap-1 text-xs">
            <a
              href={check?.release_url ?? "#"}
              target="_blank"
              rel="noreferrer"
              className="text-primary-600 hover:underline"
            >
              {t("update.releaseNotes")}
            </a>
            <a
              href={(check?.release_url ?? "").split("/tag/")[0]}
              target="_blank"
              rel="noreferrer"
              className="text-primary-600 hover:underline"
            >
              {t("update.allReleases")}
            </a>
          </div>
        </div>
      )}
    </span>
  );
}
