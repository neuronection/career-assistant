import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@neuronection/assistant-ui";

import { fetchFollowupSurface, updateFollowupRules } from "@/api/applications";
import { apiDetail } from "@/api/client";
import { Button, Spinner } from "@/components/ui";
import { ToggleRow } from "@/components/cv/formPrimitives";
import type { FollowupRules } from "@/types/application";

const DEFAULT_RULE: FollowupRules = {
  enabled: true,
  cadence_days: [7, 14],
  milestone_checkins: true,
  channels: {},
};

const ROUTE_KEYS = ["default", "followup_due", "interview_checkin", "offer_checkin"] as const;
const ROUTE_CHANNELS = ["email", "webhook"] as const;

function sameRules(a: FollowupRules, b: FollowupRules): boolean {
  return (
    a.enabled === b.enabled &&
    a.milestone_checkins === b.milestone_checkins &&
    a.cadence_days.join(",") === b.cadence_days.join(",") &&
    JSON.stringify(a.channels) === JSON.stringify(b.channels)
  );
}

/** Follow-up cadence settings block (plan 116.3): enable switch,
 * cadence editor and the interview/offer check-in toggle. One block,
 * mounted by Settings → Notifications and the tracker toolbar. */
export function FollowupRulesCard({ showChannels = false }: { showChannels?: boolean }) {
  const { t } = useTranslation();
  const [rules, setRules] = useState<FollowupRules | null>(null);
  const [draft, setDraft] = useState<FollowupRules | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void fetchFollowupSurface()
      .then((surface) => {
        setRules(surface.rules);
        setDraft(surface.rules);
      })
      .catch(() => {
        setRules(DEFAULT_RULE);
        setDraft(DEFAULT_RULE);
      });
  }, []);

  if (draft === null) {
    return (
      <div className="flex justify-center py-4" data-testid="followup-rules-loading">
        <Spinner />
      </div>
    );
  }

  const change = (patch: Partial<FollowupRules>) => {
    setSaved(false);
    setDraft((current) => (current === null ? current : { ...current, ...patch }));
  };

  const setDay = (index: number, value: number) => {
    const cadence = draft.cadence_days.map((day, at) => (at === index ? value : day));
    change({ cadence_days: cadence });
  };

  const removeDay = (index: number) => {
    if (draft.cadence_days.length <= 1) return;
    change({ cadence_days: draft.cadence_days.filter((_, at) => at !== index) });
  };

  const addDay = () => {
    const last = draft.cadence_days[draft.cadence_days.length - 1] ?? 7;
    change({ cadence_days: [...draft.cadence_days, Math.min(last + 7, 120)] });
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await updateFollowupRules({
        enabled: draft.enabled,
        cadence_days: draft.cadence_days,
        milestone_checkins: draft.milestone_checkins,
        ...(showChannels ? { channels: draft.channels } : {}),
      });
      setRules(next);
      setDraft(next);
      setSaved(true);
    } catch (exc) {
      setError(apiDetail(exc));
    } finally {
      setBusy(false);
    }
  };

  const toggleRouteChannel = (route: string, channel: string) => {
    const current = draft.channels[route] ?? [];
    const next = current.includes(channel)
      ? current.filter((entry) => entry !== channel)
      : [...current, channel];
    const channels = { ...draft.channels };
    if (next.length === 0) delete channels[route];
    else channels[route] = next;
    change({ channels });
  };

  const dirty = rules === null || !sameRules(rules, draft);

  return (
    <section className="space-y-3" data-testid="followup-rules">
      <p className="text-xs text-[var(--as-muted-fg)]">
        {t("followupRules.body")}
      </p>
      <ToggleRow
        label={t("followupRules.enabled")}
        checked={draft.enabled}
        onChange={(enabled) => change({ enabled })}
      />
      <ToggleRow
        label={t("followupRules.milestones")}
        checked={draft.milestone_checkins}
        onChange={(milestone_checkins) => change({ milestone_checkins })}
      />
      <div className="space-y-2" data-testid="followup-cadence">
        <p className="text-xs text-[var(--as-muted-fg)]">{t("followupRules.cadence")}</p>
        {draft.cadence_days.map((day, index) => (
          <div key={`${index}-${day}`} className="flex items-end gap-2">
            <label className="flex-1 text-xs text-[var(--as-fg)]">
              <span className="text-[var(--as-muted-fg)]">
                {t("followupRules.step", { count: index + 1 })}
              </span>
              <Input
                type="number"
                min={1}
                max={120}
                value={day}
                aria-label={t("followupRules.stepDays", { count: index + 1 })}
                data-testid={`followup-cadence-day-${index}`}
                onChange={(event) =>
                  setDay(index, Math.max(1, Math.min(120, Number(event.target.value) || 1)))
                }
                className="mt-1 w-full"
              />
            </label>
            <Button
              variant="ghost"
              size="sm"
              data-testid={`followup-cadence-remove-${index}`}
              disabled={draft.cadence_days.length <= 1}
              onClick={() => removeDay(index)}
            >
              {t("followupRules.remove")}
            </Button>
          </div>
        ))}
        <Button
          variant="outline"
          size="sm"
          data-testid="followup-cadence-add"
          onClick={addDay}
          disabled={draft.cadence_days.length >= 5}
        >
          {t("followupRules.addStep")}
        </Button>
      </div>
      {showChannels && (
        <div className="space-y-2" data-testid="followup-channel-routes">
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("followupRules.channelsBody")}
          </p>
          {ROUTE_KEYS.map((route) => (
            <div key={route} className="flex items-center justify-between gap-2">
              <span className="text-xs text-[var(--as-fg)]">
                {t(`followupRules.channels.${route}`)}
              </span>
              <div className="flex items-center gap-3">
                {ROUTE_CHANNELS.map((channel) => (
                  <label
                    key={channel}
                    className="flex items-center gap-1 text-[11px] text-[var(--as-muted-fg)]"
                  >
                    <input
                      type="checkbox"
                      data-testid={`followup-route-${route}-${channel}`}
                      checked={(draft.channels[route] ?? []).includes(channel)}
                      onChange={() => toggleRouteChannel(route, channel)}
                    />
                    {channel}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      {error !== null && (
        <p className="text-xs text-rose-600" data-testid="followup-rules-error">
          {error}
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={() => void save()}
          disabled={busy || !dirty}
          data-testid="followup-rules-save"
        >
          {t("common.save")}
        </Button>
        {saved && !dirty && (
          <span className="text-xs text-emerald-600" data-testid="followup-rules-saved">
            {t("followupRules.saved")}
          </span>
        )}
      </div>
    </section>
  );
}
