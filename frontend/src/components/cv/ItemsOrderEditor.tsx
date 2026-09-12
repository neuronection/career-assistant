import { useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

export interface ItemOption {
  id: string;
  label: string;
}

/**
 * Reorder disclosure for one items block: the rows in the user's
 * `props.order` first, then the remainder in resolved order. Drag via
 * the ⠿ handle (row inputs swallow gestures) + up/down buttons for
 * keyboard a11y. Persists the FULL id array after each change — the
 * renderer's remainder rule handles later deletions.
 */
export function ItemsOrderEditor({
  options,
  order,
  onChange,
}: {
  options: ItemOption[];
  order: string[];
  onChange: (order: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  const known = new Set(options.map((option) => option.id));
  const ids = [
    ...order.filter((id) => known.has(id)),
    ...options.map((option) => option.id).filter((id) => !order.includes(id)),
  ];
  const labelOf = (id: string) =>
    options.find((option) => option.id === id)?.label ?? id.slice(0, 8);
  const untouched =
    JSON.stringify(ids) === JSON.stringify(options.map((option) => option.id));

  const move = (id: string, delta: number) => {
    const index = ids.indexOf(id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= ids.length) return;
    const next = [...ids];
    next.splice(target, 0, next.splice(index, 1)[0]);
    onChange(next);
  };

  const dropOn = (id: string) => {
    if (!dragId || dragId === id) {
      setDragId(null);
      setDragOverId(null);
      return;
    }
    const next = ids.filter((entry) => entry !== dragId);
    next.splice(ids.indexOf(id), 0, dragId);
    onChange(next);
    setDragId(null);
    setDragOverId(null);
  };

  return (
    <div className="rounded-lg border border-[var(--as-border)]" data-testid="items-order">
      <button
        type="button"
        aria-expanded={open}
        data-testid="items-order-toggle"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full cursor-pointer items-center justify-between px-2 py-1.5 text-xs font-medium text-[var(--as-fg)] transition-colors duration-150 hover:bg-[var(--as-muted)]"
      >
        <span>
          Reorder items
          {untouched ? (
            <span className="ml-1.5 text-[var(--as-muted-fg)]">· default order</span>
          ) : (
            <span
              className="ml-1.5 rounded-full bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)] px-1.5 py-0.5 text-[10px] text-[var(--as-accent)]"
            >
              custom
            </span>
          )}
        </span>
        <span aria-hidden className="text-[var(--as-muted-fg)]">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <ul className="space-y-1 border-t border-[var(--as-border)] p-1.5" data-testid="items-order-list">
          {ids.map((id, index) => (
            <li
              key={id}
              draggable
              onDragStart={(event) => {
                if (!event.dataTransfer) return;
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", labelOf(id));
                setDragId(id);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOverId(id);
              }}
              onDrop={(event) => {
                event.preventDefault();
                dropOn(id);
              }}
              onDragEnd={() => {
                setDragId(null);
                setDragOverId(null);
              }}
              className={`flex items-center gap-1 rounded-md px-1 py-0.5 text-xs transition-colors ${
                dragOverId === id ? "cv-drop-slot" : ""
              } ${dragId === id ? "opacity-40" : ""}`}
              data-testid={`items-order-row-${id}`}
            >
              <span
                draggable
                role="button"
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === "ArrowUp") {
                    event.preventDefault();
                    move(id, -1);
                  }
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    move(id, 1);
                  }
                }}
                className={`select-none cursor-grab px-0.5 text-[var(--as-muted-fg)] ${
                  dragId === id ? "cursor-grabbing" : ""
                }`}
                aria-label={`Reorder ${labelOf(id)} — use up and down arrow keys`}
                title="Drag, or focus and use ↑/↓"
                data-testid={`items-order-handle-${id}`}
              >
                ⠿
              </span>
              <span className="min-w-0 flex-1 truncate">{index + 1}. {labelOf(id)}</span>
              <button
                type="button"
                aria-label={`Move ${labelOf(id)} up`}
                data-testid={`items-order-up-${id}`}
                disabled={index === 0}
                onClick={() => move(id, -1)}
                className="cursor-pointer rounded p-0.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:opacity-30"
              >
                <ArrowUp className="h-3 w-3" aria-hidden />
              </button>
              <button
                type="button"
                aria-label={`Move ${labelOf(id)} down`}
                data-testid={`items-order-down-${id}`}
                disabled={index === ids.length - 1}
                onClick={() => move(id, 1)}
                className="cursor-pointer rounded p-0.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:opacity-30"
              >
                <ArrowDown className="h-3 w-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
