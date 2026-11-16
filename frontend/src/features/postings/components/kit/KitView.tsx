import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Target } from "lucide-react";

import { linkApplicationDocument } from "@/api/applications";
import { preparePostingKit } from "@/api/postings";
import { apiDetail } from "@/api/client";
import { Button, EmptyState } from "@/components/ui";
import { KitAnswersTab } from "@/features/postings/components/kit/KitAnswersTab";
import { KitChecklistTab } from "@/features/postings/components/kit/KitChecklistTab";
import { KitCvTab } from "@/features/postings/components/kit/KitCvTab";
import { KitLetterTab } from "@/features/postings/components/kit/KitLetterTab";
import { KitTabs, type KitTabKey } from "@/features/postings/components/kit/KitTabs";
import { KitTimelineTab } from "@/features/postings/components/kit/KitTimelineTab";
import type { ApplicationKit, KitPrepare, PostingKit } from "@/types/wire";

const TAB_PANEL_TESTID: Record<KitTabKey, string> = {
  cv: "kit-panel-cv",
  letter: "kit-panel-letter",
  answers: "kit-panel-answers",
  checklist: "kit-panel-checklist",
  timeline: "kit-panel-timeline",
};

/** The five-tab kit body shared by the posting kit and the application
 * kit page. Review discipline: prep runs only on the button, proposals
 * apply/dismiss per card, and document links go through the tracker's
 * own audited endpoints. */
export function KitView({
  kit,
  applicationId,
  onChanged,
  timelineFallback,
}: {
  kit: PostingKit | ApplicationKit;
  applicationId: string | null;
  onChanged: () => void;
  timelineFallback?: React.ReactNode;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<KitTabKey>("cv");
  const [prepare, setPrepare] = useState<KitPrepare | null>(null);
  const [prepareBusy, setPrepareBusy] = useState(false);
  const [prepareError, setPrepareError] = useState("");
  const [dismissed, setDismissed] = useState<string[]>([]);

  const isApplicationKit = "timeline" in kit;
  const appKit = isApplicationKit ? (kit as ApplicationKit) : null;

  async function runPrepare() {
    setPrepareBusy(true);
    setPrepareError("");
    try {
      setPrepare(await preparePostingKit(kit.posting.ref));
    } catch (exc) {
      setPrepareError(apiDetail(exc));
    } finally {
      setPrepareBusy(false);
    }
  }

  async function linkDocument(body: { cv_id?: string; cover_letter_id?: string }) {
    if (applicationId === null) return;
    try {
      await linkApplicationDocument(applicationId, body);
      onChanged();
    } catch (exc) {
      setPrepareError(apiDetail(exc));
    }
  }

  return (
    <div className="mt-2">
      <KitTabs active={tab} onChange={setTab} />
      {prepareError !== "" && (
        <p className="mt-2 text-xs text-rose-600" data-testid="kit-error">
          {prepareError}
        </p>
      )}
      <div
        role="tabpanel"
        id={`kit-panel-${tab}`}
        aria-labelledby={`kit-tab-${tab}`}
        data-testid={TAB_PANEL_TESTID[tab]}
      >
        {tab === "cv" && (
          <KitCvTab
            kit={kit}
            applicationId={applicationId}
            prepare={prepare}
            prepareBusy={prepareBusy}
            onPrepare={() => void runPrepare()}
            onLinkDocument={(cvId) => void linkDocument({ cv_id: cvId })}
            dismissed={dismissed}
            onDismiss={(key) => setDismissed((prev) => [...prev, key])}
          />
        )}
        {tab === "letter" && (
          <KitLetterTab
            kit={kit}
            applicationId={applicationId}
            onLinkDocument={(coverLetterId) => void linkDocument({ cover_letter_id: coverLetterId })}
            onChanged={onChanged}
          />
        )}
        {tab === "answers" && <KitAnswersTab kit={kit} onChanged={onChanged} />}
        {tab === "checklist" && <KitChecklistTab kit={kit} />}
        {tab === "timeline" && (
          isApplicationKit ? (
            <KitTimelineTab
              kit={appKit}
              stageLabel={(stage) => t(`applications.stage.${stage}`, { defaultValue: stage })}
              markAppliedAction={timelineFallback}
            />
          ) : applicationId !== null ? (
            <div className="py-6" data-testid="kit-timeline-tracked">
              <EmptyState
                icon={Target}
                title={t("applications.kit.timeline.trackedTitle")}
                description={t("applications.kit.timeline.trackedBody")}
                action={
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/applications/${applicationId}`}>
                      {t("applications.kit.openApplication")}
                    </Link>
                  </Button>
                }
              />
            </div>
          ) : (
            <KitTimelineTab
              kit={null}
              stageLabel={(stage) => t(`applications.stage.${stage}`, { defaultValue: stage })}
              markAppliedAction={timelineFallback}
            />
          )
        )}
      </div>
    </div>
  );
}
