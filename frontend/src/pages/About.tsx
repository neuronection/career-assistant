import { useTranslation } from "react-i18next";
import { Github, Linkedin, Mail } from "lucide-react";
import { AboutPanel } from "@neuronection/assistant-ui";
import packageJson from "../../package.json";
import { SPONSOR_CHANNELS } from "@/config/funding";

export function About() {
  const { t } = useTranslation();
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
          { group: "Creator", copyValue: "constliakos@gmail.com", label: "constliakos@gmail.com", subtitle: "Click to copy", icon: Mail },
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
    </div>
  );
}
