import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight, Heart } from "lucide-react";
import {
  CareerMark,
  HealthMark,
  NeuronectionMark,
  NeuronectionWordmark,
  SponsorCard,
  StudyMark,
} from "@neuronection/assistant-ui";
import type { LogoProps } from "@neuronection/assistant-ui";
import packageJson from "../../package.json";

import { Modal, ModalContent } from "@/components/ui";
import { NEURONECTION_URL, SPONSOR_CHANNELS } from "@/config/funding";

const fundPillClass =
  "inline-flex h-8 items-center gap-1.5 rounded-full border border-rose-100 bg-rose-50 px-4 text-[13px] font-medium text-rose-600 transition-colors hover:bg-rose-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600 [&_svg]:size-4";
const aboutPillClass =
  "inline-flex h-8 items-center rounded-full px-4 text-[13px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600";
const fundPillCompactClass =
  "inline-flex h-7 items-center gap-1 rounded-full border border-rose-100 bg-rose-50 px-3 text-xs font-medium text-rose-600 transition-colors hover:bg-rose-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600 [&_svg]:size-3.5";
const aboutPillCompactClass =
  "inline-flex h-7 items-center rounded-full px-3 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600";

/** Family assistants listed in the footer; every row links to its site. */
const FAMILY_LINKS: {
  name: string;
  Mark: React.ComponentType<LogoProps>;
  href: string;
  current?: boolean;
}[] = [
  { name: "Health", Mark: HealthMark, href: "https://health-assistant.io" },
  {
    name: "Career",
    Mark: CareerMark,
    href: "https://neuronection.com/en/career/",
    current: true,
  },
  { name: "Study", Mark: StudyMark, href: "https://neuronection.com/en/study/" },
];

/**
 * Sidebar footer ad block: family branding, the three family assistants,
 * About and Fund actions plus the version. Collapses to icons in the
 * collapsed rail; `compact` (short viewports) drops the branding +
 * family panel and slims the pills so the nav list keeps the space.
 */
export function SidebarFooter({
  collapsed,
  compact = false,
}: {
  collapsed: boolean;
  compact?: boolean;
}) {
  const navigate = useNavigate();
  const [fundOpen, setFundOpen] = useState(false);

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-1.5">
        <a
          href={NEURONECTION_URL}
          target="_blank"
          rel="noreferrer"
          title="Part of Neuronection"
          aria-label="Part of Neuronection"
          className="flex rounded-lg p-1.5 text-slate-400 transition-colors hover:text-primary-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
        >
          <NeuronectionMark size={18} />
        </a>
        <button
          type="button"
          title="Support this project"
          aria-label="Support this project"
          onClick={() => setFundOpen(true)}
          className="flex size-7 items-center justify-center rounded-full text-rose-500 transition-colors hover:bg-rose-50 hover:text-rose-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-600"
        >
          <Heart className="size-4" />
        </button>
        <span className="text-[11px] font-medium text-slate-500">v{packageJson.version}</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-2.5">
      {!compact && (
        <a
          href={NEURONECTION_URL}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 self-start text-xs text-slate-500 transition-colors hover:text-primary-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
        >
          <span>Part of</span>
          <NeuronectionMark size={16} />
          <NeuronectionWordmark height={14} />
        </a>
      )}
      {!compact && (
        <div className="w-full rounded-[var(--as-radius)] bg-slate-50 px-2 pb-1.5 pt-2">
          <p className="px-1.5 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            More from the family
          </p>
          {FAMILY_LINKS.map(({ name, Mark, href, current }) => (
            <a
              key={href}
              href={href}
              target="_blank"
              rel="noreferrer"
              aria-label={`${name} Assistant`}
              className="group flex items-center gap-2 rounded-[var(--as-radius-sm)] px-1.5 py-1 text-sm transition-colors hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
            >
              <Mark size={16} />
              <span
                className={`w-12 text-left ${
                  current ? "font-bold text-slate-900" : "font-medium text-slate-700"
                }`}
              >
                {name}
              </span>
              <span className="font-medium text-slate-500">Assistant</span>
              <ArrowUpRight
                aria-hidden
                className="ml-auto size-3.5 text-slate-300 transition-colors group-hover:text-primary-600"
              />
            </a>
          ))}
        </div>
      )}
      {compact ? (
        <>
          <div className="flex w-full items-center justify-between">
            <a
              href={NEURONECTION_URL}
              target="_blank"
              rel="noreferrer"
              title="Part of Neuronection"
              aria-label="Part of Neuronection"
              className="flex flex-col items-center gap-1 text-slate-400 transition-colors hover:text-primary-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
            >
              <NeuronectionMark size={20} />
              <NeuronectionWordmark height={7} />
            </a>
            <span className="text-xs font-medium text-slate-500">
              v{packageJson.version}
            </span>
          </div>
          <div className="flex items-center justify-center gap-2">
            <button
              type="button"
              onClick={() => setFundOpen(true)}
              className={fundPillCompactClass}
            >
              <Heart />
              Fund
            </button>
            <button
              type="button"
              onClick={() => navigate("/about")}
              className={aboutPillCompactClass}
            >
              About
            </button>
          </div>
        </>
      ) : (
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setFundOpen(true)} className={fundPillClass}>
            <Heart />
            Fund
          </button>
          <button type="button" onClick={() => navigate("/about")} className={aboutPillClass}>
            About
          </button>
        </div>
      )}
      {!compact && (
        <p className="text-xs font-medium text-slate-500">v{packageJson.version}</p>
      )}

      <Modal open={fundOpen} onOpenChange={setFundOpen}>
        <ModalContent size="sm" aria-describedby={undefined}>
          <SponsorCard
            channels={SPONSOR_CHANNELS}
            title="Help Career Assistant grow"
            columns={1}
            className="border-none bg-transparent shadow-none"
          />
        </ModalContent>
      </Modal>
    </div>
  );
}
