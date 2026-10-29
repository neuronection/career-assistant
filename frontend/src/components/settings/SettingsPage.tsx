import { useEffect, useState, type MouseEventHandler, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";

/** One anchor target of the in-page rail — the page renders the matching
 * `id` on its section wrappers (`SettingsSectionCard` sits inside a
 * `<section id>` or the card is wrapped in an anchor div). */
export interface SettingsSectionLink {
  id: string;
  label: string;
}

/** Page scaffold for every settings page (plan 148): icon + title +
 * description + status chips, then rail + content. The rail is a sticky
 * anchor nav that only exists when the PAGE column is wide (≥62rem
 * container — the chat dock narrows the column, so this must not key off
 * the viewport). Testids: `settings-page`, `settings-page-rail`,
 * `settings-page-rail-{id}`. */
export function SettingsPage({
  icon: Icon,
  title,
  description,
  statusChips,
  actions,
  sections,
  children,
}: {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  statusChips?: ReactNode;
  actions?: ReactNode;
  sections?: SettingsSectionLink[];
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const [active, setActive] = useState(sections?.[0]?.id ?? "");
  const sectionIds = sections?.map((section) => section.id).join(",");

  useEffect(() => {
    if (!sectionIds) return;
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]?.target.id) setActive(visible[0].target.id);
      },
      { rootMargin: "-15% 0px -70% 0px", threshold: 0 },
    );
    for (const id of sectionIds.split(",")) {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [sectionIds]);

  const jump = (id: string): MouseEventHandler<HTMLAnchorElement> => (event) => {
    const element = document.getElementById(id);
    if (!element) return;
    event.preventDefault();
    element.scrollIntoView({ behavior: "smooth", block: "start" });
    setActive(id);
  };

  return (
    <div className="ca-settings" data-testid="settings-page">
      <header className="ca-settings-head">
        {Icon ? (
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[color-mix(in_srgb,var(--as-primary)_12%,var(--as-surface-raised))] text-[var(--as-primary)]"
            aria-hidden
          >
            <Icon className="h-5 w-5" />
          </span>
        ) : null}
        <div className="min-w-0">
          <h1 className="text-xl font-bold tracking-tight text-[var(--as-fg)]">{title}</h1>
          {description ? (
            <p className="mt-0.5 max-w-2xl text-sm text-[var(--as-muted-fg)]">{description}</p>
          ) : null}
        </div>
        {(statusChips || actions) && (
          <div className="flex flex-wrap items-center justify-end gap-2">
            {statusChips}
            {actions}
          </div>
        )}
      </header>
      <div className="ca-settings-layout">
        {sections && sections.length > 0 ? (
          <nav className="ca-settings-rail" aria-label={t("settingsKit.onThisPage")} data-testid="settings-page-rail">
            <p className="ca-settings-rail-title">{t("settingsKit.onThisPage")}</p>
            {sections.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                onClick={jump(section.id)}
                aria-current={active === section.id ? "true" : undefined}
                data-testid={`settings-page-rail-${section.id}`}
                className={`ca-settings-rail-link ${
                  active === section.id ? "ca-settings-rail-link-active" : ""
                }`}
              >
                {section.label}
              </a>
            ))}
          </nav>
        ) : null}
        <div className="ca-settings-content">{children}</div>
      </div>
    </div>
  );
}
