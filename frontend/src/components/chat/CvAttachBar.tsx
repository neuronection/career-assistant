import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText, Paperclip, X } from "lucide-react";

import { fetchCvs } from "@/api/cv";
import { useCareerChatContext } from "@/components/chat/useCareerChat";

interface CvOption {
  id: string;
  title: string;
}

let cvsCache: CvOption[] | null = null;

async function loadCvs(): Promise<CvOption[]> {
  if (cvsCache !== null) {
    return cvsCache;
  }
  try {
    const rows = await fetchCvs();
    cvsCache = rows.map((row) => ({ id: row.id, title: row.title }));
  } catch {
    cvsCache = [];
  }
  return cvsCache;
}

/**
 * Composer CV reference chips (plan 78) — the open Studio CV is attached
 * automatically by the chat hook, so this renders the attached chips
 * only, in the composer's `suggestions`/`attachments` rail. Renders
 * nothing when there is nothing to show.
 */
export function CvAttachChips() {
  const { t } = useTranslation();
  const chat = useCareerChatContext();

  if (chat.attachments.length === 0) {
    return null;
  }
  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-1"
      data-testid="chat-attach-bar"
    >
      {chat.attachments.map((entry) => (
        <span
          key={entry.cv_id}
          data-testid={`chat-attachment-${entry.cv_id}`}
          className="inline-flex max-w-full items-center gap-1 rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
        >
          <FileText className="size-3 shrink-0" aria-hidden />
          <span className="max-w-[12rem] truncate">{entry.title}</span>
          <button
            type="button"
            aria-label={t("chat.attach.remove", { title: entry.title })}
            onClick={() => chat.detachCv(entry.cv_id)}
            className="shrink-0 rounded-full hover:text-[var(--as-fg)]"
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
    </div>
  );
}

/** The paperclip trigger (composer toolbar): opens the CV picker. */
export function CvAttachButton() {
  const { t } = useTranslation();
  const chat = useCareerChatContext();
  const [open, setOpen] = useState(false);
  const [cvs, setCvs] = useState<CvOption[]>(cvsCache ?? []);

  useEffect(() => {
    if (!open || cvs.length > 0) {
      return;
    }
    let cancelled = false;
    void loadCvs().then((rows) => {
      if (!cancelled) {
        setCvs(rows);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [open, cvs.length]);

  if (chat.attachments.length >= 2) {
    return null;
  }
  return (
    <div className="relative" data-testid="chat-attach-open-wrap">
      <button
        type="button"
        aria-label={t("chat.attach.open")}
        data-testid="chat-attach-open"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center rounded-full p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
      >
        <Paperclip className="size-3.5" aria-hidden />
      </button>
      {open ? (
        <div className="absolute bottom-full left-0 z-20 mb-1 max-h-56 w-56 overflow-auto rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-1 shadow-lg">
          {cvs.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-[var(--as-muted-fg)]">
              {t("chat.attach.none")}
            </p>
          ) : (
            cvs.map((cv) => {
              const attached = chat.attachments.some(
                (entry) => entry.cv_id === cv.id,
              );
              return (
                <button
                  key={cv.id}
                  type="button"
                  data-testid={`chat-attach-cv-${cv.id}`}
                  disabled={attached}
                  onClick={() => {
                    chat.attachCv(cv);
                    setOpen(false);
                  }}
                  className="flex w-full items-center gap-1.5 rounded-[var(--as-radius)] px-2 py-1.5 text-left text-xs text-[var(--as-fg)] hover:bg-[var(--as-muted)] disabled:opacity-40"
                >
                  <FileText className="size-3 shrink-0" aria-hidden />
                  <span className="truncate">{cv.title}</span>
                </button>
              );
            })
          )}
        </div>
      ) : null}
    </div>
  );
}
