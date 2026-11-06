import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Heart } from "lucide-react";
import {
  FamilyMenu,
  NeuronectionMark,
  NeuronectionWordmark,
  SponsorCard,
} from "@neuronection/assistant-ui";
import packageJson from "../../package.json";

import { Modal, ModalContent } from "@/components/ui";
import { UpdateBadge } from "@/components/UpdateBadge";
import { NEURONECTION_URL, SPONSOR_CHANNELS } from "@/config/funding";

const fundPillClass =
  "inline-flex h-8 items-center gap-1.5 rounded-full border border-rose-100 bg-rose-50 px-3 text-xs font-medium text-rose-600 transition-colors hover:bg-rose-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600 [&_svg]:size-4";
const aboutPillClass =
  "inline-flex h-8 items-center rounded-full px-3 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600";
const fundPillCompactClass =
  "inline-flex h-7 items-center gap-1 rounded-full border border-rose-100 bg-rose-50 px-2.5 text-[11px] font-medium text-rose-600 transition-colors hover:bg-rose-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600 [&_svg]:size-3.5";
const aboutPillCompactClass =
  "inline-flex h-7 items-center rounded-full px-2.5 text-[11px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600";

const brandLineClass =
  "flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5 text-[11px] text-slate-500 transition-colors hover:text-primary-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600";

/**
 * Sidebar footer project block: family branding, the family switcher,
 * About and Fund actions plus the version. Copy comes from i18n and the
 * sponsor channels from config (ADR-006 keeps this app-side). `compact`
 * (short viewports) slims the pills; the collapsed rail renders icons only.
 */
export function SidebarFooter({
  collapsed,
  compact = false,
}: {
  collapsed: boolean;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [fundOpen, setFundOpen] = useState(false);

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-1.5">
        <a
          href={NEURONECTION_URL}
          target="_blank"
          rel="noreferrer"
          title={t("footer.partOfNeuronection")}
          aria-label={t("footer.partOfNeuronection")}
          className="flex rounded-lg p-1.5 text-slate-400 transition-colors hover:text-primary-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
        >
          <NeuronectionMark size={18} />
        </a>
        <button
          type="button"
          title={t("footer.supportProject")}
          aria-label={t("footer.supportProject")}
          onClick={() => setFundOpen(true)}
          className="flex size-7 items-center justify-center rounded-full text-rose-500 transition-colors hover:bg-rose-50 hover:text-rose-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600"
        >
          <Heart className="size-4" />
        </button>
        <UpdateBadge version={packageJson.version} className="text-[11px]" />
        <Modal open={fundOpen} onOpenChange={setFundOpen}>
          <ModalContent size="sm" aria-describedby={undefined}>
            <SponsorCard
              channels={SPONSOR_CHANNELS}
              title={t("footer.sponsorTitle")}
              columns={1}
              className="border-none bg-transparent shadow-none"
            />
          </ModalContent>
        </Modal>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-2">
      <a
        href={NEURONECTION_URL}
        target="_blank"
        rel="noreferrer"
        className={`${brandLineClass} self-start`}
      >
        <span>{t("footer.partOf")}</span>
        <NeuronectionMark size={16} />
        <NeuronectionWordmark height={12} />
        <span className="text-slate-400">{t("footer.family")}</span>
      </a>
      <div className="flex flex-wrap items-center justify-center gap-1.5">
        <FamilyMenu
          current="career"
          label={t("footer.explore")}
          ariaLabel={t("footer.exploreProjects")}
          menuLabel={t("footer.neuronectionFamily")}
          familyLabel={t("footer.family")}
          countLabel={(count) => t("footer.appCount", { count })}
          closeLabel={t("common.close")}
          currentLabel={t("footer.current")}
          version={`v${packageJson.version}`}
          className={compact ? "h-7 px-2 text-[11px]" : undefined}
        />
        <button
          type="button"
          onClick={() => setFundOpen(true)}
          className={compact ? fundPillCompactClass : fundPillClass}
        >
          <Heart />
          {t("footer.fund")}
        </button>
        <button
          type="button"
          onClick={() => navigate("/about")}
          className={compact ? aboutPillCompactClass : aboutPillClass}
        >
          {t("footer.about")}
        </button>
      </div>
      <UpdateBadge version={packageJson.version} className="text-[10px]" />

      <Modal open={fundOpen} onOpenChange={setFundOpen}>
        <ModalContent size="sm" aria-describedby={undefined}>
          <SponsorCard
            channels={SPONSOR_CHANNELS}
            title={t("footer.sponsorTitle")}
            columns={1}
            className="border-none bg-transparent shadow-none"
          />
        </ModalContent>
      </Modal>
    </div>
  );
}
