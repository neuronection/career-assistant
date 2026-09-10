import { Coffee, Github } from "lucide-react";
import type { SponsorChannel } from "@neuronection/assistant-ui";

export const NEURONECTION_URL = "https://neuronection.com";

/** Funding channels shared by the sidebar footer popup and the About page. */
export const SPONSOR_CHANNELS: SponsorChannel[] = [
  {
    id: "buymeacoffee",
    name: "Buy Me a Coffee",
    href: "https://buymeacoffee.com/neuronection",
    description: "One-off support — funds hosting and development.",
    icon: Coffee,
    external: true,
    highlight: true,
  },
  {
    id: "github-star",
    name: "Star on GitHub",
    href: "https://github.com/neuronection/career-assistant",
    description: "Free — stars are the only marketing the project has.",
    icon: Github,
    external: true,
  },
];
