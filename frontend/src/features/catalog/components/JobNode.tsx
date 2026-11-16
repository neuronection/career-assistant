import { Handle, Position, type NodeProps } from "reactflow";

import { NODE_FONT_SIZE, NODE_HEIGHT, NODE_WIDTH } from "./graphLayout";

export interface JobNodeData {
  code: string;
  title: string;
  familyRoot: string | null;
  color: string;
  focused: boolean;
  neighbour: boolean;
  dimmed: boolean;
  animate: boolean;
  delayMs: number;
  onSelect: (code: string) => void;
}

const HANDLES = [
  { id: "s-left", type: "source", position: Position.Left },
  { id: "s-right", type: "source", position: Position.Right },
  { id: "s-top", type: "source", position: Position.Top },
  { id: "s-bottom", type: "source", position: Position.Bottom },
  { id: "t-left", type: "target", position: Position.Left },
  { id: "t-right", type: "target", position: Position.Right },
  { id: "t-bottom", type: "target", position: Position.Bottom },
  { id: "t-top", type: "target", position: Position.Top },
] as const;

/**
 * One job in the constellation.
 *
 * All eight handles stay mounted: React Flow 11 measures handle rectangles from
 * the DOM, so hiding a side with `display:none` or a zero size breaks edge
 * routing. `visibility:hidden` keeps the layout box and the measurement intact.
 *
 * The entry animation lives on the inner surface, never on the box: an
 * `animation-fill-mode: both` opacity on the box would pin it at 1 and swallow
 * the dim state, and a translated box would be measured with offset handles.
 */
export function JobNode({ data }: NodeProps<JobNodeData>) {
  const { code, title, familyRoot, color, focused, neighbour, dimmed, animate, delayMs, onSelect } = data;
  const classes = [
    "ca-graph-node",
    animate ? "ca-graph-node-enter" : "",
    dimmed ? "ca-graph-node-dim" : "",
    neighbour ? "ca-graph-node-neighbour" : "",
    focused ? "ca-graph-node-focus" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={focused}
      aria-label={title}
      data-testid={`graph-focus-${code}`}
      data-family={familyRoot ?? "unknown"}
      data-focused={focused ? "true" : "false"}
      data-neighbour={neighbour ? "true" : "false"}
      data-dimmed={dimmed ? "true" : "false"}
      className={classes}
      style={{
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        background: color,
        fontSize: NODE_FONT_SIZE,
        pointerEvents: "all",
      }}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(code);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          onSelect(code);
        }
      }}
    >
      <span
        className="ca-graph-node-surface"
        style={animate ? { animationDelay: `${delayMs}ms` } : undefined}
      >
        <span className="ca-graph-node-label">{title}</span>
      </span>
      {HANDLES.map((handle) => (
        <Handle
          key={handle.id}
          id={handle.id}
          type={handle.type}
          position={handle.position}
          isConnectable={false}
          style={{ visibility: "hidden", pointerEvents: "none" }}
        />
      ))}
    </div>
  );
}
