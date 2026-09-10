import { useEffect, useMemo, useRef, useState } from "react";
import { Modal, ModalContent } from "@/components/ui";

export interface CommandItem {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  commands: CommandItem[];
}

/**
 * Keyboard command palette (Ctrl/Cmd+K in the builder): fuzzy-free
 * substring filter, arrow navigation, Enter runs. Candidate for the
 * family library when a second app needs one.
 */
export function CommandPalette({ open, onClose, commands }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter((command) =>
      `${command.label} ${command.hint ?? ""}`.toLowerCase().includes(needle)
    );
  }, [commands, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  useEffect(() => {
    setCursor((current) => Math.min(current, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 pt-24"
      onClick={onClose}
      data-testid="command-palette"
    >
      <Modal open onOpenChange={(next) => !next && onClose()}>
        <ModalContent
          size="md"
          className="absolute top-24"
          onClick={(event) => event.stopPropagation()}
        >
          <input
            ref={inputRef}
            autoFocus
            value={query}
            placeholder="Type a command…"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setCursor((c) => Math.min(c + 1, filtered.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              } else if (event.key === "Enter") {
                event.preventDefault();
                const command = filtered[cursor];
                if (command) {
                  onClose();
                  command.run();
                }
              } else if (event.key === "Escape") {
                onClose();
              }
            }}
            className="w-full border-b p-3 text-sm outline-none"
            data-testid="command-input"
          />
          <ul className="max-h-80 overflow-y-auto p-1">
            {filtered.length === 0 && (
              <li className="p-3 text-sm text-[var(--as-muted-fg)]">No matching command</li>
            )}
            {filtered.map((command, index) => (
              <li key={command.id}>
                <button
                  className={`flex w-full items-center justify-between rounded px-3 py-2 text-left text-sm ${
                    index === cursor ? "bg-[var(--as-muted)]" : "hover:bg-[var(--as-muted)]/60"
                  }`}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => {
                    onClose();
                    command.run();
                  }}
                  data-testid={`command-${command.id}`}
                >
                  <span>{command.label}</span>
                  {command.hint && (
                    <span className="text-xs text-[var(--as-muted-fg)]">{command.hint}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </ModalContent>
      </Modal>
    </div>
  );
}
