// W7 — tag a player from the TV. Fully D-pad navigable: a preset first-name list plus
// an on-screen keyboard. While it is open it owns the whole input surface, so Backspace
// deletes a character instead of navigating Back (S-25 precedence); Escape cancels.
import { useCallback, useState } from "react";
import { useDpad } from "../platform/keys";

interface Props {
  playerId: string;
  initial?: string | null;
  /** Names already on the roster, filtered out of the preset list. */
  taken: string[];
  onSave: (name: string) => void;
  onCancel: () => void;
}

// ponytail: a hardcoded list beats a contacts import for a demo. Swap for the team
// roster once games have one.
const PRESET_NAMES = ["Marcus", "Jordan", "Alex", "Sam", "Chris", "Taylor", "Zoe", "Riley"];

/** Title-case what the on-screen keyboard produced; the API gets exactly this. */
function displayName(v: string) {
  return v.replace(/(^|\s)\S/g, (m) => m.toUpperCase());
}

const LETTER_ROWS = ["ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ'-"];

type Cell =
  | { kind: "preset" | "char"; label: string }
  | { kind: "space" | "del" | "save" | "cancel"; label: string };

export function TagDialog({ playerId, initial, taken, onSave, onCancel }: Props) {
  const [value, setValue] = useState(initial ?? "");
  const [row, setRow] = useState(0);
  const [col, setCol] = useState(0);

  const presets = PRESET_NAMES.filter((n) => n === initial || !taken.includes(n));
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
          onSave(cell.label);
          break;
        case "char":
          setValue((v) => (v + cell.label.toLowerCase()).slice(0, 24));
          break;
        case "space":
          setValue((v) => (v + " ").slice(0, 24));
          break;
        case "del":
          setValue((v) => v.slice(0, -1));
          break;
        case "save":
          if (value.trim()) onSave(displayName(value));
          break;
        case "cancel":
          onCancel();
          break;
      }
    },
    [onSave, onCancel, value],
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

  const shown = displayName(value);

  return (
    <div className="tag-dialog" data-testid="tag-dialog" data-player-id={playerId} role="dialog">
      <h2>Tag player {playerId}</h2>
      <div className="tag-value" data-testid="tag-value">
        {shown || <span className="dim">type a name…</span>}
      </div>
      {grid.map((cells, r) => (
        <div className="tag-row" key={r}>
          {cells.map((cell, c) => (
            <span
              key={cell.label}
              className={`tag-key kind-${cell.kind}${r === row && c === col ? " focused" : ""}`}
              data-testid={`tag-key-${cell.label}`}
              data-focused={r === row && c === col ? "true" : "false"}
            >
              {cell.label}
            </span>
          ))}
        </div>
      ))}
      <p className="hint">Arrows move · Enter picks · Backspace deletes a letter · Escape cancels</p>
    </div>
  );
}
