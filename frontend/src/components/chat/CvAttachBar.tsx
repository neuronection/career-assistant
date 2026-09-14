import { useEffect, useState } from "react";
import { useMatch } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FileText, Paperclip, X } from "lucide-react";

import { fetchCvs } from "@/api/cv";
import { useCareerChatContext } from "@/components/chat/useCareerChat";

/**
 * CV reference attachments in the composer (plan 78): the open Studio CV
 * is one click away (suggested chip), the popover attaches any CV, and
 * pending attachments ride the next message. Attachments are a property
 * of the question — never a session mode.
 */
export function CvAttachBar() {
  const { t } = useTranslation();
  const chat = useCareerChatContext();
  const studioMatch = useMatch("/cv/:id");
  const [cvs, setCvs] = useState<{ id: string; title: string }[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if ((!open && studioMatch === null) || cvs.length > 0) {
      return;
    }
    let cancelled = false;
    void fetchCvs().then((rows) => {
      if (!cancelled) {
        setCvs(rows.map((row) => ({ id: row.id, title: row.title })));
      }
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open, cvs.length, studioMatch]);

  const openCv =
    studioMatch?.params.id !== undefined
      ? cvs.find((cv) => cv.id === studioMatch.params.id) ??
        (cvs.length === 0
          ? { id: studioMatch.params.id, title: t("chat.attach.openCv") }
          : null)
      : null;
  const suggestedAttached =
    openCv !== null && chat.attachments.some((entry) => entry.cv_id === openCv.id);

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1" data-testid="chat-attach-bar">
      {chat.attachments.map((entry) => (
        <span
          key={entry.cv_id}
          data-testid={`chat-attachment-${entry.cv_id}`}
          className="inline-flex max-w-[14rem] items-center gap-1 rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
        >
          <FileText className="size-3 shrink-0" aria-hidden />
          <span className="truncate">{entry.title}</span>
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
      {openCv !== null && !suggestedAttached ? (
        <button
          type="button"
          data-testid="chat-attach-cv"
          onClick={() => chat.attachCv(openCv)}
          className="inline-flex items-center gap-1 rounded-full border border-dashed border-primary-300 px-2 py-0.5 text-[10px] font-medium text-primary-700 transition-colors hover:bg-primary-50"
        >
          <FileText className="size-3" aria-hidden />
          {t("chat.attach.suggest", { title: openCv.title })}
        </button>
      ) : null}
      {chat.attachments.length < 2 ? (
        <div className="relative">
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
      ) : null}
    </div>
  );
}
