import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiDetail } from "@/api/client";
import {
  fetchMappingsAlerts,
  mappingActionError,
  saveMappingsAlerts,
  type MappingAlerts,
} from "@/api/mappings";
import { Button } from "@/components/ui";
import { NumberField } from "@/features/cv/components/cv/formPrimitives";

/**
 * The alert settings card (plan 205 AD10/S9): the accounted-for floor the
 * alert sweep evaluates against. Editable here — the sweep reads it on its
 * next run; the schedule itself is boot-provisioned and daily.
 */
export function MappingAlertsCard() {
  const { t } = useTranslation();
  const [alerts, setAlerts] = useState<MappingAlerts | null>(null);
  const [floor, setFloor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const current = await fetchMappingsAlerts();
      setAlerts(current);
      setFloor(current.coverage_floor);
    } catch (caught) {
      setError(apiDetail(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (floor == null) return;
    setBusy(true);
    setNote(null);
    try {
      const saved = await saveMappingsAlerts(floor);
      setAlerts(saved);
      setNote(t("mappingsConsole.alerts.saved"));
      await load();
    } catch (caught) {
      setNote(mappingActionError(caught));
    } finally {
      setBusy(false);
    }
  };

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!alerts) return null;

  return (
    <div className="rounded-xl border p-4" data-testid="mappings-alerts">
      <h3 className="mb-2 text-sm font-semibold text-slate-800">
        {t("mappingsConsole.alerts.title")}
      </h3>
      <NumberField
        label={t("mappingsConsole.alerts.coverageFloor")}
        value={floor}
        onChange={(value: number | null) => setFloor(value)}
        min={0}
        max={1}
        testId="mappings-alerts-floor"
      />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={busy || floor == null}
          onClick={() => void save()}
          data-testid="mappings-alerts-save"
        >
          {t("mappingsConsole.alerts.save")}
        </Button>
        <span className="text-xs text-slate-500">{t("mappingsConsole.alerts.note")}</span>
      </div>
      {note && (
        <p className="mt-2 text-sm text-slate-600" data-testid="mappings-alerts-note">
          {note}
        </p>
      )}
    </div>
  );
}
