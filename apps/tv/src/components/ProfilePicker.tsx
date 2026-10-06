// M10 link a roster player to a profile (from Watch's "Link profile" and the Review
// identity question). Up/Down pick a profile, Select links it (POST /profiles/{id}/links,
// which also names the roster player after the profile), Back cancels. While open it owns
// the remote. Test hooks: `profile-picker`, `picker-profile` rows, `picker-note`.
import { useCallback, useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
import { listWindow } from "../../../../packages/tv-core/src/discovery";
import { sportsText, type Profile } from "../../../../packages/tv-core/src/profiles";
import { api } from "../api";
import { Avatar } from "./Avatar";
import { useDpad, type DpadAction } from "../input";
import { color, focusRing, font, px } from "../theme";
import { Hint, T, styles as ui, useAsync } from "../ui";

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
    <View style={styles.scrim}>
      <View style={styles.panel} testID="profile-picker" dataSet={{ playerId }}>
        <T style={ui.h2}>Link {playerLabel} to a profile</T>
        <T style={{ color: color.dim }}>Linking names this player after the profile in this game.</T>
        {error ? <T testID="picker-note">Could not load profiles: {error.message}</T> : null}
        {profiles && list.length === 0 ? (
          <T testID="picker-empty">No profiles yet. Create one on your phone at /profiles.</T>
        ) : null}
        <View style={{ marginTop: px(16) }}>
          {list.slice(first, first + VISIBLE).map((p, k) => {
            const on = first + k === focus;
            return (
              <View
                key={p.profile_id}
                testID="picker-profile"
                dataSet={{ profileId: p.profile_id, focused: on ? "true" : "false" }}
                style={[styles.row, focusRing(on), on && { backgroundColor: color.raised }]}
              >
                <Avatar name={p.name} photo={p.photo_url} size={56} />
                <T style={{ flex: 1, fontWeight: "700", marginLeft: px(20) }} numberOfLines={1}>
                  {p.name}
                </T>
                <T style={styles.meta}>{sportsText(p)}</T>
              </View>
            );
          })}
        </View>
        {note ? <T testID="picker-note">{note}</T> : null}
        <Hint>Up/Down pick · Select links · Back cancels</Hint>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  scrim: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    backgroundColor: "rgba(5, 7, 10, 0.8)",
    alignItems: "center",
    justifyContent: "center",
  },
  panel: { width: px(1000), padding: px(40), borderRadius: px(16), backgroundColor: color.panel },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: px(20),
    paddingVertical: px(8),
    borderRadius: px(12),
    marginBottom: px(8),
  },
  meta: { color: color.dim, fontSize: font.small },
});
