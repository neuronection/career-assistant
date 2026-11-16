import { useTranslation } from "react-i18next";

export type KitTabKey = "cv" | "letter" | "answers" | "checklist" | "timeline";

export const KIT_TABS: KitTabKey[] = [
  "cv",
  "letter",
  "answers",
  "checklist",
  "timeline",
];

/** The kit's five-tab rail (plan 212 §3.6): a real tablist with roving
 * tabindex and arrow-key movement, matching the market-stats pattern. */
export function KitTabs({
  active,
  onChange,
}: {
  active: KitTabKey;
  onChange: (tab: KitTabKey) => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="tablist"
      aria-label={t("applications.kit.tabs.aria")}
      className="flex gap-1 overflow-x-auto border-b border-[var(--as-border)]"
      data-testid="kit-tabs"
    >
      {KIT_TABS.map((tab, index) => {
        const selected = tab === active;
        return (
          <button
            key={tab}
            type="button"
            role="tab"
            id={`kit-tab-${tab}`}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab)}
            onKeyDown={(event) => {
              if (
                event.key !== "ArrowRight" &&
                event.key !== "ArrowLeft" &&
                event.key !== "Home" &&
                event.key !== "End"
              ) {
                return;
              }
              event.preventDefault();
              const next =
                event.key === "Home"
                  ? KIT_TABS[0]
                  : event.key === "End"
                    ? KIT_TABS[KIT_TABS.length - 1]
                    : KIT_TABS[
                        (index + (event.key === "ArrowRight" ? 1 : -1) + KIT_TABS.length) %
                          KIT_TABS.length
                      ];
              onChange(next);
              document.getElementById(`kit-tab-${next}`)?.focus();
            }}
            className={`min-h-[40px] whitespace-nowrap rounded-t-lg px-3 text-xs font-medium transition-colors ${
              selected
                ? "border border-b-0 border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-fg)]"
                : "text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
            }`}
            data-testid={`kit-tab-${tab}`}
          >
            {t(`applications.kit.tabs.${tab}`)}
          </button>
        );
      })}
    </div>
  );
}
