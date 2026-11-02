import { useState } from "react";

import { OrgAvatar } from "@/components/company/OrgAvatar";
import type { JobSourcePreset } from "@/config/jobSourcePresets";

/**
 * A preset's identity tile: the tenant logo when the artwork file exists
 * (`public/presets/<slug>.svg|png`), else the deterministic monogram —
 * the same fallback the gallery, the sources list and the detail header
 * share (plan 183).
 */
export function PresetLogo({ preset, size = 40 }: { preset: JobSourcePreset; size?: number }) {
  const [failed, setFailed] = useState(false);
  if (preset.logo && !failed) {
    return (
      <img
        src={preset.logo}
        alt=""
        loading="lazy"
        style={{ width: size, height: size }}
        className="shrink-0 rounded-lg object-contain"
        onError={() => setFailed(true)}
      />
    );
  }
  return <OrgAvatar name={preset.name} size={size} className="rounded-lg" />;
}
