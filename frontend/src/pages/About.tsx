import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Github, Linkedin, Mail } from "lucide-react";
import { AboutPanel } from "@neuronection/assistant-ui";
import packageJson from "../../package.json";
import { SPONSOR_CHANNELS } from "@/config/funding";
import { loadUpdateCheck } from "@/components/UpdateBadge";

export function About() {
  const { t } = useTranslation();
  const [check, setCheck] = useState<Awaited<ReturnType<typeof loadUpdateCheck>>>(null);

  useEffect(() => {
    let alive = true;
    void loadUpdateCheck().then((value) => {
      if (alive) setCheck(value);
    });
    return () => {
      alive = false;
    };
  }, []);
  return (
    <div className="mx-auto w-full max-w-4xl p-6 pb-20">
      <AboutPanel
        appName="Career Assistant"
        familyCurrent="career"
        tagline={t("about.tagline")}
        description={t("about.description")}
        version={packageJson.version}
        license={{
          name: "Apache License 2.0",
          href: "https://www.apache.org/licenses/LICENSE-2.0",
        }}
        linksTitle={t("about.linksTitle")}
        links={[
          { group: "Project", href: "https://github.com/neuronection/career-assistant", label: "GitHub", subtitle: "neuronection/career-assistant", icon: Github },
          { group: "Creator", href: "https://www.linkedin.com/in/ilias-chatzopoulos-aabb22163/", label: "LinkedIn", subtitle: "Ilias Chatzopoulos", icon: Linkedin },
          { group: "Creator", copyValue: "constliakos@gmail.com", label: "constliakos@gmail.com", subtitle: t("about.clickToCopy"), icon: Mail },
        ]}
        creator={{
          name: "Ilias Chatzopoulos",
          role: "Founder & Lead Architect",
          href: "https://github.com/constLiakos",
        }}
        tech={[
          "FastAPI",
          "async SQLAlchemy 2",
          "PostgreSQL (JSONB)",
          "React 18 + Vite + TypeScript",
          "Tailwind",
          "reactflow",
          "OpenAI-compatible AI",
          "structured outputs + audit trail",
          "pytest + vitest",
          "Apache-2.0",
        ]}
        sponsor={{
          channels: SPONSOR_CHANNELS,
          title: t("about.sponsorTitle"),
        }}
        copyright="© 2026 Neuronection"
      />
      {check?.update_available && check.latest_version && (
        <p className="mt-4 rounded-[var(--as-radius)] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          v{packageJson.version} {t("update.installed")} ·{" "}
          <a
            href={check.release_url}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-primary-600 hover:underline"
          >
            v{check.latest_version} {t("update.availableSuffix")}
          </a>{" "}
          ·{" "}
          <a
            href={check.release_url}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-primary-600 hover:underline"
          >
            {t("update.releaseNotes")}
          </a>
        </p>
      )}
    </div>
  );
}
