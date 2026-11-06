import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import * as surfaceApi from "@/api/extensions";
import type { SurfacePageView } from "@/api/extensions";
import { apiDetail } from "@/api/client";
import {
  EmptyState,
  SurfaceRenderer,
  type SurfaceActionId,
  type SurfaceFilter,
  type SurfaceNode,
  type SurfaceRow,
  type SurfaceView,
} from "@/components/ui";

/**
 * Extension surface page (plan 32 Phase 4 / ADR-0040 clause 16): a routed
 * declarative surface of an installed mini-app, rendered through the
 * family SurfaceRenderer with the host-resolved label set the backend
 * serves — never extension markup. Route: `/extensions/:extensionId`; the
 * kill switch (extension disabled) surfaces as the empty state (the API
 * 404s), never a broken page.
 */

type FacetState = Record<string, string>;

function applyFilter(rows: SurfaceRow[], state: FacetState): SurfaceRow[] {
  const facets = Object.entries(state).filter(([, value]) => value !== "");
  if (facets.length === 0) return rows;
  return rows.filter((row) =>
    facets.every(([facet, value]) => {
      const bound = (row.values as Record<string, unknown>)?.[facet];
      return bound === undefined || String(bound) === String(value);
    }),
  );
}

export function ExtensionSurfacePage() {
  const { extensionId = "" } = useParams();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [view, setView] = useState<SurfacePageView | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [facets, setFacets] = useState<FacetState>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setView(null);
    setError("");
    surfaceApi
      .fetchSurfacePage(extensionId)
      .then((data) => {
        if (!cancelled) setView(data);
      })
      .catch((err) => {
        if (!cancelled) setError(apiDetail(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [extensionId]);

  const surface = view?.surface;

  const surfaceNodes = (surface?.nodes ?? []) as SurfaceNode[];
  const surfaceRows = (surface?.rows ?? []) as SurfaceRow[];

  const filterDefs = useMemo<SurfaceFilter[]>(
    () =>
      (surface?.filters ?? []).map((facet) => ({
        id: facet.id,
        options: facet.options.map((option) => ({
          value: option.value,
          label: option.label ?? facet.id,
        })),
      })),
    [surface],
  );

  const filteredRows = useMemo(
    () => applyFilter(surfaceRows, facets),
    [surfaceRows, facets],
  );

  const onFilterChange = useCallback((facetId: string, value: string | null) => {
    setFacets((current) => ({ ...current, [facetId]: value ?? "" }));
  }, []);

  const onAction = useCallback(
    async (action: { id: SurfaceActionId; rowId?: string }) => {
      if (action.id === "run:export" && view) {
        const deck = await surfaceApi.exportSurfacePage(view.extensionId);
        const blob = new Blob([JSON.stringify(deck, null, 2)], {
          type: "application/json",
        });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `${view.extensionId}-v${view.version}.json`;
        link.click();
        URL.revokeObjectURL(link.href);
        return;
      }
      if (action.id === "item:open") {
        navigate("/cv", { state: { layout: action.rowId } });
      }
    },
    [navigate, view],
  );

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center" data-testid="surface-page-loading">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" aria-hidden />
      </div>
    );
  }

  if (!view) {
    return (
      <div className="p-6" data-testid="surface-page-missing">
        <EmptyState
          title={t("extensions.page.missingTitle")}
          description={error || t("extensions.page.missingDescription")}
          action={
            <Link to="/settings/tools" className="text-sm text-primary-600">
              {t("extensions.page.backToTools")}
            </Link>
          }
        />
      </div>
    );
  }

  const degraded = Object.entries(surface?.degraded ?? {});

  return (
    <div className="mx-auto max-w-5xl p-6" data-testid="extension-surface-page">
      <header className="mb-6 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-xl font-bold text-slate-900">{view.title}</h1>
        <span className="text-xs text-slate-500">v{view.version}</span>
        {degraded.length > 0 && (
          <span
            className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
            data-testid="surface-degrade-chip"
            title={t("extensions.page.degradedHint")}
          >
            {t("extensions.page.degraded", { surface: degraded[0]?.[0] ?? "" })}
          </span>
        )}
      </header>
      <SurfaceRenderer
        surface={
          {
            nodes: surfaceNodes,
            rows: filteredRows,
            values: surface?.values ?? {},
            groups: surface?.groups ?? {},
          } satisfies SurfaceView
        }
        labels={surface?.labels ?? {}}
        filters={filterDefs}
        activeFilters={facets}
        onFilterChange={onFilterChange}
        onAction={(action) => void onAction(action)}
      />
    </div>
  );
}
