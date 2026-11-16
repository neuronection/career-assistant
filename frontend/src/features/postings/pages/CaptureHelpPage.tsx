import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui";

function bookmarklet(): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return `javascript:(function(){window.open('${origin}/postings?capture='+encodeURIComponent(location.href),'_blank')})()`;
}

export function CaptureHelpPage() {
  const { t } = useTranslation();
  return (
    <div className="ca-workspace mx-auto max-w-3xl space-y-4" data-testid="capture-help">
      <div>
        <h1 className="text-xl font-semibold text-[var(--as-fg)]">{t("capture.helpTitle")}</h1>
        <p className="mt-1 text-sm text-[var(--as-muted-fg)]">{t("capture.helpIntro")}</p>
      </div>
      <div className="space-y-3 rounded-[var(--as-radius-lg)] border border-[var(--as-border)] p-4">
        <p className="text-sm text-[var(--as-fg)]">{t("capture.helpDrag")}</p>
        <a
          href={bookmarklet()}
          draggable
          onClick={(event) => event.preventDefault()}
          className="inline-block rounded-[var(--as-radius)] border border-[var(--as-accent)] px-3 py-2 text-sm font-medium text-[var(--as-accent)]"
          data-testid="capture-bookmarklet"
        >
          {t("capture.bookmarklet")}
        </a>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-[var(--as-muted-fg)]">
          <li>{t("capture.helpStep1")}</li>
          <li>{t("capture.helpStep2")}</li>
          <li>{t("capture.helpStep3")}</li>
        </ol>
      </div>
      <Button variant="outline" asChild>
        <Link to="/postings">{t("capture.back")}</Link>
      </Button>
    </div>
  );
}
