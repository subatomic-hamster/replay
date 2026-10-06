// M10 link a roster player to a profile (Watch's "Link profile", the Review identity
// question). Arrows pick a profile, Enter links it (POST /profiles/{id}/links, which also
// names the roster player after the profile), Escape cancels. Owns the keys while open.
import { useCallback, useMemo, useState } from "react";
import { api } from "../api/client";
import { useDpad, type DpadAction } from "../platform/keys";
import { useAsync } from "../ui";
import { Avatar } from "./Avatar";
import { listWindow } from "../../../../packages/tv-core/src/discovery";
import { sportsText, type Profile } from "../../../../packages/tv-core/src/profiles";

const VISIBLE = 6;

export function ProfilePicker({
  gameId,
  playerId,
  playerLabel,
  onLinked,
  onCancel,
}: {
  gameId: string;
  playerId: string;
  playerLabel: string;
  onLinked: (p: Profile) => void;
  onCancel: () => void;
}) {
  const { data: profiles, error } = useAsync(() => api.listProfiles(), []);
  const [focus, setFocus] = useState(0);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const list = useMemo(() => profiles ?? [], [profiles]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") onCancel();
      else if (a === "up" || a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "down" || a === "right") setFocus((i) => Math.max(0, Math.min(list.length - 1, i + 1)));
      else if (a === "select" && list[focus] && !busy) {
        setBusy(true);
        api.linkProfile(list[focus].profile_id, gameId, playerId).then(onLinked, (e: Error) => {
          setNote(`Not linked: ${e.message}`);
          setBusy(false);
        });
      }
    },
    [list, focus, busy, gameId, playerId, onLinked, onCancel],
  );
  useDpad(onAction);

  const first = listWindow(focus, list.length, VISIBLE);
  return (
    <div className="export-scrim">
      <div className="export-panel" data-testid="profile-picker" data-player-id={playerId}>
        <h2>Link {playerLabel} to a profile</h2>
        <p className="dim">Linking names this player after the profile in this game.</p>
        {error ? <p data-testid="picker-note">Could not load profiles: {error.message}</p> : null}
        {profiles && list.length === 0 ? (
          <p data-testid="picker-empty">No profiles yet. Create one on your phone at /profiles.</p>
        ) : null}
        <ul className="picker-list">
          {list.slice(first, first + VISIBLE).map((p, k) => {
            const on = first + k === focus;
            return (
              <li
                key={p.profile_id}
                className={`picker-row${on ? " focused" : ""}`}
                data-testid="picker-profile"
                data-profile-id={p.profile_id}
                data-focused={on ? "true" : "false"}
              >
                <Avatar name={p.name} photo={p.photo_url} size={56} />
                <b>{p.name}</b>
                <span className="dim">{sportsText(p)}</span>
              </li>
            );
          })}
        </ul>
        {note ? <p data-testid="picker-note">{note}</p> : null}
        <p className="hint">
          <b>↑/↓</b> pick · <b>Enter</b> links · <b>Escape</b> cancels
        </p>
      </div>
    </div>
  );
}
