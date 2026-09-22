// W7 — tag a player from the TV. Thin wrapper over the generic D-pad text entry
// (S-24 presets, S-25 on-screen keyboard); test hooks stay `tag-dialog|tag-value|tag-key-*`.
import { TextEntryDialog } from "./TextEntryDialog";

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

export function TagDialog({ playerId, initial, taken, onSave, onCancel }: Props) {
  return (
    <TextEntryDialog
      idPrefix="tag"
      title={`Tag player ${playerId}`}
      initial={initial}
      presets={PRESET_NAMES.filter((n) => n === initial || !taken.includes(n))}
      format={displayName}
      onSubmit={onSave}
      onCancel={onCancel}
      data={{ "data-player-id": playerId }}
    />
  );
}
