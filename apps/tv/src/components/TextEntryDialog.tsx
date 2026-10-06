// D-pad text entry: an optional preset row plus an on-screen keyboard (S-24/S-25). While
// open it owns the whole input surface; on a keyboard Backspace deletes a character
// (S-25 precedence), on a remote Back cancels. Test hooks: `${idPrefix}-dialog|-value|-key-<label>`.
import { useCallback, useState } from "react";
import { StyleSheet, View } from "react-native";
import { useDpad, type DpadAction } from "../input";
import { color, font, px } from "../theme";
import { Hint, Pill, T, styles as ui } from "../ui";

interface Props {
  idPrefix: string;
  title: string;
  initial?: string | null;
  presets?: string[];
  format?: (value: string) => string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
  dataSet?: Record<string, string>;
}

const LETTER_ROWS = ["ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ'-"];

type Cell = { kind: "preset" | "char" | "space" | "del" | "save" | "cancel"; label: string };

export function TextEntryDialog({
  idPrefix,
  title,
  initial,
  presets = [],
  format = (v) => v,
  onSubmit,
  onCancel,
  dataSet,
}: Props) {
  const [value, setValue] = useState(initial ?? "");
  const [row, setRow] = useState(0);
  const [col, setCol] = useState(0);

  const grid: Cell[][] = [
    presets.map((label): Cell => ({ kind: "preset", label })),
    ...LETTER_ROWS.map((r) => [...r].map((label): Cell => ({ kind: "char", label }))),
    [
      { kind: "space", label: "SPACE" },
      { kind: "del", label: "DEL" },
      { kind: "save", label: "SAVE" },
      { kind: "cancel", label: "CANCEL" },
    ] as Cell[],
  ].filter((r) => r.length > 0);

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
    (a: DpadAction) => {
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
    <View style={styles.backdrop}>
      <View style={styles.dialog} testID={`${idPrefix}-dialog`} dataSet={dataSet}>
        <T style={ui.h2}>{title}</T>
        <View style={styles.value}>
          <T testID={`${idPrefix}-value`} style={{ fontSize: font.h2, color: shown ? color.fg : color.dim }}>
            {shown || "type here…"}
          </T>
        </View>
        {grid.map((cells, r) => (
          <View style={styles.row} key={r}>
            {cells.map((cell, c) => (
              <Pill
                key={cell.label}
                label={cell.label}
                focused={r === row && c === col}
                testID={`${idPrefix}-key-${cell.label}`}
                style={cell.kind === "char" ? styles.key : undefined}
              />
            ))}
          </View>
        ))}
        <Hint>Arrows move · Select picks · DEL deletes a letter · Back cancels</Hint>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    backgroundColor: "rgba(5, 7, 10, 0.86)",
    alignItems: "center",
    justifyContent: "center",
  },
  dialog: {
    backgroundColor: color.panel,
    padding: px(48),
    borderRadius: px(16),
    borderWidth: px(2),
    borderColor: color.line,
  },
  value: {
    backgroundColor: color.ink,
    paddingHorizontal: px(24),
    paddingVertical: px(12),
    marginBottom: px(24),
    borderRadius: px(8),
    minWidth: px(800),
  },
  row: { flexDirection: "row", flexWrap: "wrap" },
  key: { minWidth: px(72), alignItems: "center", borderRadius: px(10) },
});
