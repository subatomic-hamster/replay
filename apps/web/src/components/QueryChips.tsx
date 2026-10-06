// H3 — preset query chips from sport_ui.chips (§4.8: no sport-name branching).
interface Props {
  chips: string[];
  focusIndex: number;
  activeChip?: string | null;
}

export { FALLBACK_CHIPS } from "../../../../packages/tv-core/src/display";

export function QueryChips({ chips, focusIndex, activeChip }: Props) {
  return (
    <div className="chips" role="listbox" aria-label="Preset queries">
      {chips.map((c, i) => (
        <span
          key={c}
          role="option"
          aria-selected={c === activeChip}
          className={`chip${i === focusIndex ? " focused" : ""}${c === activeChip ? " active" : ""}`}
          data-testid="query-chip"
          data-chip={c}
          data-focused={i === focusIndex ? "true" : "false"}
        >
          {c}
        </span>
      ))}
    </div>
  );
}
