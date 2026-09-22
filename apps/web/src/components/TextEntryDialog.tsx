// D-pad text entry: an optional preset row plus an on-screen keyboard. While it is open
// it owns the whole input surface, so Backspace deletes a character instead of
// navigating Back (S-25 precedence); Escape cancels.
//
// Two users: TagDialog (W7, presets = roster names) and the Highlights "Ask…" chip
// (H3 free text). Test hooks are `${idPrefix}-dialog|-value|-key-<label>`.
import { useCallback, useState } from "react";
import { useDpad } from "../platform/keys";

interface Props {
  idPrefix: string;
  title: string;
  initial?: string | null;
  /** One-tap answers rendered above the keyboard (roster names, saved queries…). */
  presets?: string[];
  /** Applied to the preview and to what onSubmit receives. */
  format?: (value: string) => string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
  /** Extra data attributes for the dialog root (e.g. data-player-id). */
  data?: Record<string, string>;
}

const LETTER_ROWS = ["ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ'-"];

type Cell =
  | { kind: "preset" | "char"; label: string }
  | { kind: "space" | "del" | "save" | "cancel"; label: string };

export function TextEntryDialog({
  idPrefix,
  title,
  initial,
  presets = [],
  format = (v) => v,
  onSubmit,
  onCancel,
  data = {},
}: Props) {
  const [value, setValue] = useState(initial ?? "");
  const [row, setRow] = useState(0);
  const [col, setCol] = useState(0);

  const grid: Cell[][] = (
    [
      presets.map((label): Cell => ({ kind: "preset", label })),
      ...LETTER_ROWS.map((r) => [...r].map((label): Cell => ({ kind: "char", label }))),
      [
        { kind: "space", label: "SPACE" },
        { kind: "del", label: "DEL" },
        { kind: "save", label: "SAVE" },
        { kind: "cancel", label: "CANCEL" },
      ] as Cell[],
    ] as Cell[][]
  ).filter((r) => r.length > 0);

  const activate = useCallback(
    (cell: Cell) => {
      switch (cell.kind) {
        case "preset":
          onSubmit(cell.label);
          break;
        case "char":
          setValue((v) => (v + cell.label.toLowerCase()).slice(0, 64));
          break;
        case "space":
          setValue((v) => (v + " ").slice(0, 64));
          break;
        case "del":
          setValue((v) => v.slice(0, -1));
          break;
        case "save":
          if (value.trim()) onSubmit(format(value));
          break;
        case "cancel":
          onCancel();
          break;
      }
    },
    [onSubmit, onCancel, format, value],
  );

  const onAction = useCallback(
    (a: string) => {
      switch (a) {
        case "up":
        case "down": {
          const next = a === "up" ? Math.max(0, row - 1) : Math.min(grid.length - 1, row + 1);
          setRow(next);
          setCol(Math.min(col, grid[next].length - 1));
          break;
        }
        case "left":
          setCol((c) => Math.max(0, c - 1));
          break;
        case "right":
          setCol((c) => Math.min(grid[row].length - 1, c + 1));
          break;
        case "select":
          activate(grid[row][col]);
          break;
        case "delete":
          setValue((v) => v.slice(0, -1));
          break;
        case "back":
          onCancel();
          break;
      }
    },
    [grid, row, col, activate, onCancel],
  );
  useDpad(onAction, true, true);

  const shown = format(value);

  return (
    <div className="tag-dialog" data-testid={`${idPrefix}-dialog`} role="dialog" {...data}>
      <h2>{title}</h2>
      <div className="tag-value" data-testid={`${idPrefix}-value`}>
        {shown || <span className="dim">type here…</span>}
      </div>
      {grid.map((cells, r) => (
        <div className="tag-row" key={r}>
          {cells.map((cell, c) => (
            <span
              key={cell.label}
              className={`tag-key kind-${cell.kind}${r === row && c === col ? " focused" : ""}`}
              data-testid={`${idPrefix}-key-${cell.label}`}
              data-focused={r === row && c === col ? "true" : "false"}
            >
              {cell.label}
            </span>
          ))}
        </div>
      ))}
      <p className="hint">
        Arrows move · Enter picks · Backspace deletes a letter · Escape cancels
      </p>
    </div>
  );
}
