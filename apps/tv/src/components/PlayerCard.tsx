// The player card (D-83): who a tracked player is and what they did this game, on the right
// third over the paused video (like the Stats panel). Opened from Do more's first tile while
// following someone. Actions: name them, follow or stop, their moments, view or link a
// profile, and the follow spotlight. Up/Down pick an action, Select runs it, Left, Back or
// Menu closes (Watch resumes playback if it was playing).
//
// The name is the viewer's own label for the track (PATCH /games/{id}/players/{pid}); an
// unnamed player stays "Player 7" and nothing names anyone automatically. The stat line is
// counted from the game's events (tv-core statLine): the stats those events support for
// this kind of game (points and shots, or kills and serves), the rest listed as not
// detected, never a guessed 0. A save that fails says so here and leaves the old name.
import { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import { ApiError } from "../../../../packages/tv-core/src/api";
import { statLine } from "../../../../packages/tv-core/src/display";
import type {
  Game,
  GameEvent,
  Player,
} from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { color, face, focusRing, px, radius, safe, sp, type } from "../theme";
import { KeyLegend, Spinner, T } from "../ui";
import { Avatar } from "./Avatar";
import { PANEL_W } from "./StatsPanel";
import { TextEntryDialog } from "./TextEntryDialog";

const PAD = sp(6);
const INNER_W = PANEL_W - PAD - safe.x;
const NAME_MAX = 60; // the API's PlayerPatch limit

type ActId = "edit" | "follow" | "moments" | "profile" | "link" | "spotlight";

const titleCase = (v: string) => v.replace(/(^|\s)\S/g, (m) => m.toUpperCase());

/** "Player 7" for an unnamed track, as on the Moments chips and the follow ring. */
export const playerName = (p: Pick<Player, "id" | "name">) =>
  p.name ?? `Player ${p.id.replace(/^p/, "")}`;

function saveError(e: unknown): string {
  return e instanceof ApiError && e.status > 0
    ? `Couldn't save the name (${e.status}: ${e.message})`
    : "Couldn't save the name: the server could not be reached";
}

export function PlayerCard({
  game,
  player,
  tint,
  following,
  moments,
  onRenamed,
  onFollow,
  onMoments,
  onProfile,
  onLink,
  spotlight,
  onSpotlight,
  onClose,
  onPlayPause,
}: {
  game: Game;
  player: Player;
  /** the drawn team colour (Watch's ink map), as on the ring */
  tint: string;
  following: boolean;
  /** how many of the game's moments are this player's */
  moments: number;
  onRenamed: (p: Player) => void;
  /** follow them, or (already following) stop */
  onFollow: () => void;
  onMoments: () => void;
  /** absent when no cross-game profile is linked to this player */
  onProfile?: () => void;
  /** link this player to a cross-game profile (offered when there is no `onProfile`) */
  onLink?: () => void;
  /** the follow spotlight's state, and its toggle (offered while following) */
  spotlight?: boolean;
  onSpotlight?: () => void;
  onClose: () => void;
  onPlayPause: () => void;
}) {
  // undefined while loading, null when the events could not be read
  const [events, setEvents] = useState<GameEvent[] | null | undefined>(
    undefined,
  );
  const [photo, setPhoto] = useState<string | null>(null);
  const [focus, setFocus] = useState<ActId>("edit");
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState<{ text: string; error: boolean } | null>(
    null,
  );
  useEffect(() => {
    let on = true;
    api.getEvents(game).then(
      (e) => on && setEvents(e),
      () => on && setEvents(null),
    );
    return () => {
      on = false;
    };
    // the game's id, not every re-read of it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [game.id]);
  const profileId = player.profile_id;
  useEffect(() => {
    if (!profileId) return setPhoto(null);
    let on = true;
    api.getProfile(profileId).then(
      (p) => on && setPhoto(p.photo_url),
      () => {}, // the initials stay
    );
    return () => {
      on = false;
    };
  }, [profileId]);

  const name = playerName(player);
  const acts: { id: ActId; label: string; run: () => void }[] = [
    {
      id: "edit",
      label: player.name ? "Edit name" : "Name this player",
      run: () => setEditing(true),
    },
    {
      id: "follow",
      label: following ? "Stop following" : `Follow ${name}`,
      run: onFollow,
    },
    {
      id: "moments",
      label: `Their moments (${moments})`,
      run: onMoments,
    },
    ...(onProfile
      ? [{ id: "profile" as const, label: "View profile", run: onProfile }]
      : onLink
        ? [{ id: "link" as const, label: "Link to a profile", run: onLink }]
        : []),
    ...(following && onSpotlight
      ? [
          {
            id: "spotlight" as const,
            label: spotlight ? "Spotlight on" : "Spotlight off",
            run: onSpotlight,
          },
        ]
      : []),
  ];
  const k = Math.max(
    0,
    acts.findIndex((a) => a.id === focus),
  );

  const save = (raw: string) => {
    setEditing(false);
    const v = raw.trim().slice(0, NAME_MAX);
    if (!v || v === player.name) return;
    setStatus({ text: "Saving…", error: false });
    api.patchPlayer(game.id, player.id, { name: v }).then(
      (p) => {
        onRenamed(p);
        setStatus({ text: "Name saved", error: false });
      },
      (e) => setStatus({ text: saveError(e), error: true }),
    );
  };

  // useDpad keeps the latest handler in a ref: no memo needed
  useDpad((a: DpadAction) => {
    // Left closes, as on the Stats panel (the card sits on the right)
    if (a === "back" || a === "menu" || a === "left") onClose();
    else if (a === "playpause") onPlayPause();
    else if (a === "up") setFocus(acts[Math.max(0, k - 1)].id);
    else if (a === "down") setFocus(acts[Math.min(acts.length - 1, k + 1)].id);
    else if (a === "select") acts[k].run();
  }, !editing);

  const line = events ? statLine(events, player.id) : null;

  return (
    <>
      <View
        style={styles.panel}
        testID="player-card"
        dataSet={{ playerId: player.id }}
      >
        <View style={styles.head}>
          <View style={[styles.ring, { borderColor: tint }]}>
            {player.name || photo ? (
              <Avatar name={name} photo={photo} size={112} />
            ) : (
              // an unnamed track: its number ("12"), not initials ("P1")
              <View style={styles.anon}>
                <T style={styles.anonText}>{player.id.replace(/^p/, "")}</T>
              </View>
            )}
          </View>
          <View style={styles.who}>
            <T style={type.title} numberOfLines={1} testID="player-card-name">
              {name}
            </T>
            {/* a mixed kit (the id is half one team, half the other): no team beats a wrong one */}
            {player.team_mixed ? null : (
              <View style={styles.teamRow}>
                <View
                  style={[styles.swatch, { backgroundColor: tint }]}
                  testID="player-card-team"
                  dataSet={{ color: tint, team: String(player.team) }}
                />
                <T style={[type.meta, styles.dim]} numberOfLines={1}>
                  {`Team ${player.team + 1}`}
                </T>
              </View>
            )}
            {player.name ? null : (
              <T style={[type.meta, styles.dim]} numberOfLines={1}>
                Anonymous until named
              </T>
            )}
          </View>
        </View>

        <T style={[type.meta, styles.dim, styles.section]}>
          This game · auto-detected
        </T>
        {events === undefined ? (
          <View style={styles.statsBox}>
            <Spinner small testID="player-card-loading" />
          </View>
        ) : !line || (!line.cells.length && !line.missing.length) ? (
          <T style={[type.body, styles.dim]} testID="player-card-no-stats">
            {events === null
              ? "The stats could not be loaded"
              : "No stats detected in this game yet"}
          </T>
        ) : (
          <>
            {line.cells.length ? (
              <View style={styles.statsBox}>
                {line.cells.map((c) => (
                  <View
                    key={c.label}
                    style={[
                      styles.cell,
                      { width: INNER_W / Math.max(5, line.cells.length) },
                    ]}
                    testID={`player-stat-${c.label}`}
                    dataSet={{ value: c.value }}
                  >
                    <T style={styles.fig}>{c.value}</T>
                    <T style={[type.meta, styles.dim]}>{c.label}</T>
                  </View>
                ))}
              </View>
            ) : (
              <T style={[type.body, styles.dim]} testID="player-card-no-stats">
                No stats detected for this player yet
              </T>
            )}
            {line.note ? (
              <T style={[type.meta, styles.dim]} testID="player-stat-note">
                {line.note}
              </T>
            ) : null}
            {line.missing.length ? (
              // one quiet line, however many: most of a rally game's stats on real
              // footage today (D-83)
              <T
                style={[type.meta, styles.dim]}
                numberOfLines={2}
                testID="player-stat-missing"
              >
                {`Not detected yet: ${line.missing.join(", ")}`}
              </T>
            ) : null}
          </>
        )}

        <View style={styles.acts}>
          {acts.map((a, i) => (
            <View
              key={a.id}
              testID={`player-card-${a.id}`}
              dataSet={{ focused: i === k ? "true" : "false" }}
              style={[styles.act, focusRing(i === k), i === k && styles.actOn]}
            >
              <T
                style={[styles.actText, i === k && { color: color.floor }]}
                numberOfLines={1}
              >
                {a.label}
              </T>
            </View>
          ))}
        </View>
        {status ? (
          <T
            style={[type.meta, status.error ? styles.error : styles.dim]}
            numberOfLines={2}
            testID="player-card-status"
            dataSet={{ error: status.error ? "true" : "false" }}
          >
            {status.text}
          </T>
        ) : null}
        <KeyLegend
          items={[
            { k: "Select", label: "Choose" },
            { k: "◀", label: "Close" },
          ]}
          style={styles.legend}
        />
      </View>

      {editing ? (
        <TextEntryDialog
          idPrefix="player-name"
          title={`Name ${name}`}
          initial={player.name}
          format={titleCase}
          dataSet={{ playerId: player.id }}
          onCancel={() => setEditing(false)}
          onSubmit={save}
        />
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  panel: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    width: PANEL_W,
    paddingLeft: PAD,
    paddingRight: safe.x,
    paddingTop: safe.y,
    paddingBottom: safe.y,
    backgroundColor: "rgba(29, 40, 52, 0.94)", // Bench, as the Stats panel
  },
  head: { flexDirection: "row", alignItems: "center" },
  anon: {
    width: px(112),
    height: px(112),
    borderRadius: px(56),
    backgroundColor: color.line,
    alignItems: "center",
    justifyContent: "center",
  },
  anonText: {
    fontFamily: face.figures,
    fontSize: px(48),
    lineHeight: px(56),
    color: color.bleacher,
    textAlign: "center",
    includeFontPadding: false,
  },
  ring: {
    borderWidth: px(4),
    borderRadius: px(64),
    padding: px(4),
  },
  who: { flex: 1, marginLeft: sp(3) },
  teamRow: { flexDirection: "row", alignItems: "center", marginTop: sp(1) },
  swatch: {
    width: px(20),
    height: px(20),
    borderRadius: px(10),
    marginRight: sp(1.5),
  },
  dim: { color: color.bleacher },
  error: { color: color.missed },
  section: { marginTop: sp(4) },
  statsBox: {
    flexDirection: "row",
    alignItems: "center",
    minHeight: px(96),
    marginBottom: sp(1),
  },
  cell: { alignItems: "center" },
  fig: {
    fontFamily: face.figures,
    fontSize: px(48),
    lineHeight: px(56),
    fontVariant: ["tabular-nums"],
  },
  acts: { marginTop: "auto" },
  act: {
    height: px(72),
    marginTop: sp(1.5),
    borderRadius: radius.chip,
    backgroundColor: color.line,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: sp(3),
  },
  actOn: { backgroundColor: color.chalk },
  // Centred both ways on Android too: no font padding above the ascender.
  actText: {
    ...type.body,
    fontWeight: "600",
    textAlign: "center",
    textAlignVertical: "center",
    includeFontPadding: false,
  },
  // in the panel's flow, under the actions, right-aligned as everywhere
  legend: {
    position: "relative",
    right: 0,
    bottom: 0,
    marginTop: sp(2),
    alignSelf: "flex-end",
  },
});
