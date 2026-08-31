const DEMAND_STYLES: Record<string, string> = {
  hot: "bg-emerald-100 text-emerald-700",
  growing: "bg-lime-100 text-lime-700",
  stable: "bg-sky-100 text-sky-700",
  declining: "bg-rose-100 text-rose-700",
};

export function DemandBadge({ outlook }: { outlook: string | null | undefined }) {
  if (!outlook) return null;
  return (
    <span
      data-testid="demand-badge"
      className={`text-xs px-2 py-0.5 rounded-full font-medium ${DEMAND_STYLES[outlook] ?? "bg-slate-100 text-slate-600"}`}
    >
      {outlook}
    </span>
  );
}
