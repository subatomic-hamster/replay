// M10 Players: every profile (photo or initials, sports, linked games). Arrows move over
// the grid, Select opens the profile, Back returns to where it was opened from. Profiles
// are created and edited on the phone (/profiles); the TV links, corrects and plays.
import { useCallback, useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
import { listWindow } from "../../../../packages/tv-core/src/discovery";
import { sportsText } from "../../../../packages/tv-core/src/profiles";
import { api } from "../api";
import { Avatar } from "../components/Avatar";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, focusRing, font, px, radius, safe } from "../theme";
import {
  ApiErrorBanner,
  ContextChip,
  KeyLegend,
  Loading,
  T,
  styles as ui,
  useAsync,
} from "../ui";

const COLS = 5;
const ROWS = 2;

export function Players({ from }: { from?: string }) {
  const { data, error, reload } = useAsync(() => api.listProfiles(), []);
  const [focus, setFocus] = useState(0);
  const list = useMemo(() => data ?? [], [data]);
  const gameTitle = useGameTitle(from);

  const onAction = useCallback(
    (a: DpadAction) => {
      const n = list.length;
      if (a === "back")
        navigate(from ? { name: "watch", gameId: from } : { name: "library" });
      else if (a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "right")
        setFocus((i) => Math.max(0, Math.min(n - 1, i + 1)));
      else if (a === "up") setFocus((i) => (i - COLS >= 0 ? i - COLS : i));
      else if (a === "down")
        setFocus((i) => Math.max(0, Math.min(n - 1, i + COLS)));
      else if (a === "select" && list[focus])
        navigate({ name: "profile", profileId: list[focus].profile_id, from });
    },
    [list, focus, from],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!data) return <Loading />;

  // whole rows scroll: the window starts on a row boundary
  const firstRow = listWindow(
    Math.floor(focus / COLS),
    Math.ceil(list.length / COLS),
    ROWS,
  );
  const shown = list.slice(firstRow * COLS, (firstRow + ROWS) * COLS);

  return (
    <View style={ui.safe} testID="players">
      <ContextChip parts={[gameTitle ?? "Home", "Players"]} kind="room" />
      <T style={[ui.h1, styles.head]}>Players</T>
      {list.length === 0 ? (
        <T testID="players-empty">
          No profiles yet. Create one on your phone at /profiles.
        </T>
      ) : null}
      <View style={styles.grid}>
        {shown.map((p, k) => {
          const i = firstRow * COLS + k;
          const on = i === focus;
          return (
            <View
              key={p.profile_id}
              testID="profile-card"
              dataSet={{
                profileId: p.profile_id,
                focused: on ? "true" : "false",
              }}
              style={[styles.card, focusRing(on)]}
            >
              <Avatar name={p.name} photo={p.photo_url} size={160} />
              <T
                style={styles.name}
                numberOfLines={1}
                testID="profile-card-name"
              >
                {p.name}
              </T>
              {sportsText(p) ? (
                <T
                  style={styles.meta}
                  numberOfLines={1}
                  testID="profile-card-sports"
                >
                  {sportsText(p)}
                </T>
              ) : null}
              <T style={styles.meta} testID="profile-card-games">
                {p.linked.length} {p.linked.length === 1 ? "game" : "games"}
              </T>
            </View>
          );
        })}
      </View>
      <KeyLegend
        items={[
          ...(list.length ? [{ k: "Select", label: "Open" }] : []),
          { k: "Back", label: from ? "Game" : "Home" },
        ]}
        style={{ bottom: safe.y }}
      />
    </View>
  );
}

/** The title of the game a Players or Profile screen was opened from (`from`), for its
 *  breadcrumb; null when it was not opened from a game. */
export function useGameTitle(gameId?: string): string | null {
  const { data } = useAsync(
    () => (gameId ? api.getGame(gameId) : Promise.resolve(null)),
    [gameId],
  );
  return gameId ? (data?.title ?? "The game") : null;
}

const styles = StyleSheet.create({
  /** below the breadcrumb */
  head: { marginTop: px(64) },
  grid: { flexDirection: "row", flexWrap: "wrap" },
  card: {
    // COLS cards and their margins inside the 1728 px safe width (5 x (312 + 32))
    width: px(312),
    alignItems: "center",
    paddingVertical: px(24),
    marginRight: px(32),
    marginBottom: px(32),
    borderRadius: radius.card,
    backgroundColor: color.panel,
  },
  name: { fontSize: font.h2, fontWeight: "700", marginTop: px(16) },
  meta: { color: color.dim, fontSize: font.small },
});
