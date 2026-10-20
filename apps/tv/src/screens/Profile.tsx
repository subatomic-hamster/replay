// M10 profile on the TV: per-sport career stats (corrections flagged EDITED, the auto value
// kept beside them), the collectible card (PNG from the API + its JSON), the career reel
// (the player's plays across games, played in order) and link management (unlink, accept
// or decline suggestions; face suggestions only ever for a face-enrolled profile).
//
// Remote: Left/Right pick a tab, Down (or Select) enters it, Up from its top row or Back
// returns to the tabs, Back from the tabs leaves. Never branches on the sport: the stat
// rows are whatever keys the career stats carry (D-58).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Image, StyleSheet, View } from "react-native";
import {
  fmtClock,
  listWindow,
} from "../../../../packages/tv-core/src/discovery";
import {
  playableReel,
  reasonText,
  sportsText,
  statLabel,
  statPatch,
  statRows,
  stepStat,
  suggestionKey,
  SUGGESTION_NOTE,
  visibleSuggestions,
  type PlayerCard,
  type Profile as ProfileDoc,
} from "../../../../packages/tv-core/src/profiles";
import { api } from "../api";
import { Avatar } from "../components/Avatar";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import {
  PlayerSurface,
  useClockTime,
  type PlayerHandle,
} from "../playback/PlayerSurface";
import { color, face, focusRing, font, px } from "../theme";
import {
  ApiErrorBanner,
  Hint,
  Loading,
  Pill,
  T,
  styles as ui,
  useAsync,
} from "../ui";

const TABS = ["Stats", "Card", "Reel", "Links"] as const;
const STAT_ROWS = 8;
const LIST_ROWS = 6;

interface TabProps {
  profile: ProfileDoc;
  active: boolean;
  onExit: () => void;
  onChange: (p: ProfileDoc) => void;
}

export function Profile({
  profileId,
  from,
}: {
  profileId: string;
  from?: string;
}) {
  const [profile, setProfile] = useState<ProfileDoc | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  const [tab, setTab] = useState(0);
  const [zone, setZone] = useState<"tabs" | "body">("tabs");

  useEffect(() => {
    setError(null);
    api.getProfile(profileId).then(setProfile, setError);
  }, [profileId, nonce]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate({ name: "players", from });
      else if (a === "left") setTab((i) => Math.max(0, i - 1));
      else if (a === "right") setTab((i) => Math.min(TABS.length - 1, i + 1));
      else if (a === "down" || a === "select") setZone("body");
    },
    [from],
  );
  useDpad(onAction, zone === "tabs");
  const exit = useCallback(() => setZone("tabs"), []);

  if (error)
    return (
      <ApiErrorBanner error={error} onRetry={() => setNonce((n) => n + 1)} />
    );
  if (!profile) return <Loading />;

  const props: TabProps = {
    profile,
    active: zone === "body",
    onExit: exit,
    onChange: setProfile,
  };
  return (
    <View
      style={ui.screen}
      testID="profile"
      dataSet={{ profileId, zone, tab: TABS[tab].toLowerCase() }}
    >
      <View style={styles.head}>
        <Avatar name={profile.name} photo={profile.photo_url} size={128} />
        <View style={{ marginLeft: px(32), flex: 1 }}>
          <T style={[ui.h1, { marginBottom: px(4) }]} testID="profile-name">
            {profile.name}
          </T>
          <T style={{ color: color.dim }} testID="profile-sports">
            {sportsText(profile)}
            {profile.positions.length
              ? ` · ${profile.positions.join(" / ")}`
              : ""}
          </T>
        </View>
        {profile.face_enrolled ? (
          <T style={styles.badge} testID="face-enrolled">
            FACE ENROLLED (OPT-IN)
          </T>
        ) : null}
      </View>
      <View style={styles.tabs}>
        {TABS.map((name, i) => (
          <Pill
            key={name}
            label={name}
            focused={zone === "tabs" && i === tab}
            active={i === tab}
            testID={`profile-tab-${name.toLowerCase()}`}
          />
        ))}
      </View>
      {tab === 0 ? <StatsTab {...props} /> : null}
      {tab === 1 ? <CardTab {...props} /> : null}
      {tab === 2 ? <ReelTab {...props} /> : null}
      {tab === 3 ? <LinksTab {...props} /> : null}
      <Hint>
        {zone === "tabs"
          ? "Left/Right pick a tab · Down enters it · Back returns to Players"
          : "Up/Down move · Select acts · Back returns to the tabs"}
      </Hint>
    </View>
  );
}

// ---------------------------------------------------------------- stats + corrections

function StatsTab({ profile, active, onExit, onChange }: TabProps) {
  const bySport = useMemo(() => profile.stats_by_sport ?? {}, [profile]);
  const sports = Object.keys(bySport);
  const multi = sports.length > 1;
  const [sportIdx, setSportIdx] = useState(0);
  const sport = sports[Math.min(sportIdx, sports.length - 1)];
  const rows = useMemo(() => statRows(bySport[sport]), [bySport, sport]);
  const [row, setRow] = useState(multi ? -1 : 0);
  const [edit, setEdit] = useState<{
    key: string;
    value: number;
    at: 0 | 1;
  } | null>(null);
  const [note, setNote] = useState("");

  const save = useCallback(
    (key: string, value: number | null) => {
      api.patchProfile(profile.profile_id, statPatch(sport, key, value)).then(
        (p) => {
          onChange(p);
          setEdit(null);
          setNote(
            value === null
              ? `${statLabel(key)}: back to the auto value`
              : `${statLabel(key)} saved as ${value} (edited)`,
          );
        },
        (e: Error) => setNote(`Not saved: ${e.message}`),
      );
    },
    [profile.profile_id, sport, onChange],
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      if (edit) {
        const r = rows.find((x) => x.key === edit.key);
        if (a === "back") setEdit(null);
        else if ((a === "left" || a === "right") && edit.at === 0)
          setEdit({
            ...edit,
            value: stepStat(edit.value, a === "right" ? 1 : -1),
          });
        else if (a === "down" && r?.edited) setEdit({ ...edit, at: 1 });
        else if (a === "up") setEdit({ ...edit, at: 0 });
        else if (a === "select")
          save(edit.key, edit.at === 0 ? edit.value : null);
        return;
      }
      if (a === "back") onExit();
      else if (a === "up") {
        if (row > (multi ? -1 : 0)) setRow(row - 1);
        else onExit();
      } else if (a === "down") setRow((i) => Math.min(rows.length - 1, i + 1));
      else if ((a === "left" || a === "right") && row === -1) {
        setSportIdx((i) =>
          Math.max(
            0,
            Math.min(sports.length - 1, i + (a === "right" ? 1 : -1)),
          ),
        );
      } else if (a === "select" && rows[row]?.editable) {
        setEdit({ key: rows[row].key, value: rows[row].value, at: 0 });
        setNote("");
      }
    },
    [edit, rows, row, multi, sports.length, save, onExit],
  );
  useDpad(onAction, active);

  if (!sports.length) {
    return (
      <T testID="stats-empty">
        No stats yet: link this player to a game first.
      </T>
    );
  }
  const first = listWindow(Math.max(0, row), rows.length, STAT_ROWS);
  return (
    <View testID="stats-tab" dataSet={{ sport }}>
      {multi ? (
        <View style={styles.row}>
          {sports.map((s, i) => (
            <Pill
              key={s}
              label={s[0].toUpperCase() + s.slice(1)}
              focused={active && row === -1 && i === sportIdx}
              active={i === sportIdx}
              testID={`stats-sport-${s}`}
            />
          ))}
        </View>
      ) : null}
      <T style={styles.dim} testID="stats-label">
        {bySport[sport]?.label === "auto-detected" ? "Auto-detected" : "Stats"}{" "}
        across {bySport[sport]?.stats.games ?? 0} linked
        {bySport[sport]?.stats.games === 1 ? " game" : " games"} · corrections
        are marked EDITED, the auto value is kept
      </T>
      {rows.slice(first, first + STAT_ROWS).map((r, k) => {
        const i = first + k;
        const on = active && i === row;
        const editing = edit?.key === r.key;
        return (
          <View
            key={r.key}
            testID="stat-row"
            dataSet={{
              key: r.key,
              edited: r.edited ? "true" : "false",
              focused: on ? "true" : "false",
              value: r.value,
            }}
            style={[
              styles.statRow,
              focusRing(on && !editing),
              on && { backgroundColor: color.raised },
            ]}
          >
            <T style={{ flex: 1 }}>{r.label}</T>
            {editing ? (
              <>
                <View
                  style={[styles.stepper, focusRing(edit.at === 0)]}
                  testID="stat-edit"
                  dataSet={{ value: edit.value }}
                >
                  <T style={styles.value}>◀ {edit.value} ▶</T>
                </View>
                {r.edited ? (
                  <Pill
                    label={`Use auto (${r.auto ?? "none"})`}
                    focused={edit.at === 1}
                    testID="stat-use-auto"
                    style={{ marginLeft: px(16), marginBottom: 0 }}
                  />
                ) : null}
              </>
            ) : (
              <T style={styles.value} testID="stat-value">
                {r.value}
              </T>
            )}
            <View style={styles.flag}>
              {r.edited ? (
                <T style={styles.edited} testID="stat-edited">
                  EDITED · auto {r.auto ?? "–"}
                </T>
              ) : null}
            </View>
          </View>
        );
      })}
      {note ? (
        <T style={styles.dim} testID="stat-note">
          {note}
        </T>
      ) : null}
      {edit ? (
        <Hint>
          Left/Right change the value · Select saves · Down: use the auto value
          · Back cancels
        </Hint>
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------- collectible card

function CardTab({ profile, active, onExit }: TabProps) {
  const [card, setCard] = useState<PlayerCard | null>(null);
  const [note, setNote] = useState("");
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .getCard(profile.profile_id)
      .then(setCard, (e: Error) => setNote(`No card: ${e.message}`));
  }, [profile]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back" || a === "up") onExit();
      else if (a === "select" && !busy) {
        setBusy(true);
        setNote("Rendering the card…");
        api
          .renderCard(profile.profile_id)
          .then(
            (c) => {
              setCard(c);
              setVersion(Date.now());
              setNote("");
            },
            (e: Error) => setNote(`Not rendered: ${e.message}`),
          )
          .finally(() => setBusy(false));
      }
    },
    [busy, profile.profile_id, onExit],
  );
  useDpad(onAction, active);

  if (!card) return <T testID="card-note">{note || "Loading the card…"}</T>;
  const png = `${api.profileMediaUrl(card.png)}${version ? `?v=${version}` : ""}`;
  return (
    <View
      style={styles.cardTab}
      testID="card-tab"
      dataSet={{ rendered: card.rendered ? "true" : "false" }}
    >
      <View style={styles.cardImage}>
        {card.rendered ? (
          <Image
            source={{ uri: png }}
            style={StyleSheet.absoluteFill}
            resizeMode="contain"
            testID="card-png"
          />
        ) : (
          <T style={styles.dim}>No card image yet. Select “Render card”.</T>
        )}
      </View>
      <View style={{ flex: 1, marginLeft: px(40) }} testID="card-json">
        <T style={ui.h2} testID="card-title">
          {card.title}
        </T>
        <T style={styles.dim}>
          {[
            card.sport,
            card.games === 1 ? "1 game" : `${card.games} games`,
            card.positions.join(" / "),
          ]
            .filter(Boolean)
            .join(" · ")}
        </T>
        <View style={[styles.row, { marginTop: px(20) }]}>
          {card.stats.map((tile) => (
            <View
              key={tile.key}
              style={styles.tile}
              testID="card-tile"
              dataSet={{
                key: tile.key,
                edited: tile.edited ? "true" : "false",
              }}
            >
              <T style={styles.tileValue}>{String(tile.value)}</T>
              <T style={styles.dim}>{tile.label}</T>
              {tile.edited ? <T style={styles.edited}>EDITED</T> : null}
            </View>
          ))}
        </View>
        <T style={styles.dim}>
          {card.label === "auto-detected" ? "Auto-detected stats" : card.label}
          {card.user_edited ? " · edited values marked" : ""}
          {card.title_source
            ? ` · title: ${card.title_source === "llm" ? "rephrased, fact-checked" : "fact-checked template"}`
            : ""}
        </T>
        {card.best_moment ? (
          <T style={styles.dim} testID="card-best">
            Best moment: {card.best_moment.game_id} at{" "}
            {fmtClock(card.best_moment.t ?? card.best_moment.t_start)}
          </T>
        ) : null}
        <View style={[styles.row, { marginTop: px(24) }]}>
          <Pill
            label={card.rendered ? "Re-render card" : "Render card"}
            focused={active}
            testID="card-render"
          />
        </View>
        {note ? (
          <T style={styles.dim} testID="card-note">
            {note}
          </T>
        ) : null}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------- career reel

function ReelTab({ profile, active, onExit }: TabProps) {
  const { data: reel, error } = useAsync(
    () => api.getReel(profile.profile_id),
    [profile],
  );
  const items = useMemo(() => playableReel(reel), [reel]);
  const [focus, setFocus] = useState(0);
  const [cur, setCur] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const t = useClockTime(handle?.clock ?? null, 1 / 10);
  const armed = useRef(false);
  const item = cur !== null ? items[cur] : undefined;

  // Each item starts at its play's start once its video knows its duration; a new game
  // is a new <video> (keyed by URL), so the old one's position never leaks in. A failed
  // video never will (the handle changes when it fails, so this re-runs and stops).
  useEffect(() => {
    armed.current = false;
    if (!handle || handle.error() || !item) return;
    const timer = setInterval(() => {
      if (handle.duration() > 0) {
        handle.seek(item.t_start);
        handle.play();
        armed.current = true;
        clearInterval(timer);
      }
    }, 50);
    return () => clearInterval(timer);
  }, [handle, item, nonce]);

  useEffect(() => {
    if (!handle || !item || cur === null || !armed.current) return;
    if (handle.currentTime() < item.t_end) return;
    if (cur + 1 < items.length) {
      setCur(cur + 1);
      setFocus(cur + 1);
    } else handle.pause();
  }, [t, handle, item, cur, items.length]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") onExit();
      else if (a === "up") {
        if (focus > 0) setFocus(focus - 1);
        else onExit();
      } else if (a === "down")
        setFocus((i) => Math.min(items.length - 1, i + 1));
      else if (a === "select" && items[focus]) {
        setCur(focus);
        setNonce((n) => n + 1);
      } else if (a === "playpause") handle?.toggle();
    },
    [focus, items, handle, onExit],
  );
  useDpad(onAction, active);

  if (error) return <T testID="reel-note">No reel: {error.message}</T>;
  if (!reel) return <T>Loading the reel…</T>;
  if (!items.length)
    return (
      <T testID="reel-empty">
        No plays yet: link this player to a processed game.
      </T>
    );
  const first = listWindow(focus, items.length, LIST_ROWS);
  return (
    <View style={styles.reel} testID="reel-tab">
      <View style={{ width: px(960) }}>
        {item?.url ? (
          <PlayerSurface key={item.url} ref={setHandle} src={item.url} muted>
            <View style={styles.counter}>
              <T
                style={styles.counterText}
                testID="reel-counter"
                dataSet={{
                  index: (cur ?? 0) + 1,
                  gameId: item.game_id,
                  playId: item.play_id,
                }}
              >
                PLAY {(cur ?? 0) + 1} / {items.length} ·{" "}
                {item.game_title ?? item.game_id}
              </T>
            </View>
          </PlayerSurface>
        ) : (
          <View style={styles.reelIdle}>
            <T style={styles.dim}>
              {items.length} plays · {fmtClock(reel.duration_s)} · Select a play
              to start the reel there
            </T>
          </View>
        )}
      </View>
      <View style={{ flex: 1, marginLeft: px(32) }}>
        {items.slice(first, first + LIST_ROWS).map((it, k) => {
          const i = first + k;
          const on = active && i === focus;
          return (
            <View
              key={`${it.game_id}/${it.play_id}`}
              testID="reel-item"
              dataSet={{
                index: i,
                focused: on ? "true" : "false",
                current: i === cur ? "true" : "false",
                gameId: it.game_id,
                tStart: it.t_start,
              }}
              style={[
                styles.listRow,
                focusRing(on),
                i === cur && { backgroundColor: color.raised },
              ]}
            >
              <T numberOfLines={1}>{it.game_title ?? it.game_id}</T>
              <T style={styles.dim}>
                {fmtClock(it.t_start)}–{fmtClock(it.t_end)}
                {it.points ? ` · ${it.points} pts` : ""}
              </T>
            </View>
          );
        })}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------- links + suggestions

type LinkRow =
  | { kind: "link"; game_id: string; player_id: string; missing?: string }
  | {
      kind: "suggestion";
      game_id: string;
      player_id: string;
      title: string;
      reasons: string[];
      face: boolean;
    };

function LinksTab({ profile, active, onExit, onChange }: TabProps) {
  const id = profile.profile_id;
  const { data: games } = useAsync(() => api.listGames(), []);
  const { data: raw, reload } = useAsync(
    () => api.getSuggestions(id),
    [id, profile],
  );
  const [row, setRow] = useState(0);
  const [col, setCol] = useState(0);
  const [note, setNote] = useState("");
  const title = useCallback(
    (g: string) => games?.find((x) => x.id === g)?.title ?? g,
    [games],
  );

  const rows = useMemo<LinkRow[]>(() => {
    const missing = new Map(
      (profile.missing_links ?? []).map((m) => [suggestionKey(m), m.missing]),
    );
    return [
      ...profile.linked.map((l): LinkRow => ({
        kind: "link",
        ...l,
        missing: missing.get(suggestionKey(l)),
      })),
      ...visibleSuggestions(profile, raw ?? []).map((s): LinkRow => ({
        kind: "suggestion",
        game_id: s.game_id,
        player_id: s.player_id,
        title: s.game_title ?? s.game_id,
        reasons: s.reasons.map(reasonText),
        face: s.reasons.some((r) => r.kind === "face"),
      })),
    ];
  }, [profile, raw]);
  const nLinks = profile.linked.length;

  const act = useCallback(
    (r: LinkRow, c: number) => {
      const done = (msg: string) => (p: ProfileDoc) => {
        onChange(p);
        reload();
        setNote(msg);
      };
      const fail = (e: Error) => setNote(`Failed: ${e.message}`);
      if (r.kind === "link") {
        api
          .unlinkProfile(id, r.game_id, r.player_id)
          .then(done(`Unlinked #${r.player_id} in ${title(r.game_id)}`), fail);
      } else if (c === 0) {
        api
          .linkProfile(id, r.game_id, r.player_id)
          .then(done(`Linked #${r.player_id} in ${title(r.game_id)}`), fail);
      } else {
        api.declineSuggestion(id, r.game_id, r.player_id).then(() => {
          reload();
          setNote("Suggestion declined");
        }, fail);
      }
      setCol(0);
    },
    [id, onChange, reload, title],
  );

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") onExit();
      else if (a === "up") {
        if (row > 0) setRow(row - 1);
        else onExit();
        setCol(0);
      } else if (a === "down") {
        setRow((i) => Math.min(rows.length - 1, i + 1));
        setCol(0);
      } else if (a === "left") setCol(0);
      else if (a === "right") setCol(rows[row]?.kind === "suggestion" ? 1 : 0);
      else if (a === "select" && rows[row]) act(rows[row], col);
    },
    [row, col, rows, act, onExit],
  );
  useDpad(onAction, active);

  useEffect(() => {
    if (row > rows.length - 1) setRow(Math.max(0, rows.length - 1));
  }, [row, rows.length]);

  const first = listWindow(row, rows.length, LIST_ROWS);
  return (
    <View testID="links-tab">
      <T style={styles.dim}>
        Linked in {nLinks} {nLinks === 1 ? "game" : "games"} · {SUGGESTION_NOTE}
      </T>
      {rows.length === 0 ? (
        <T testID="links-empty">No links or suggestions yet.</T>
      ) : null}
      {rows.slice(first, first + LIST_ROWS).map((r, k) => {
        const i = first + k;
        const on = active && i === row;
        return (
          <View
            key={`${r.kind}/${suggestionKey(r)}`}
            testID={r.kind === "link" ? "link-row" : "suggestion-row"}
            dataSet={{
              gameId: r.game_id,
              playerId: r.player_id,
              focused: on ? "true" : "false",
              face: r.kind === "suggestion" && r.face ? "true" : "false",
            }}
            style={[styles.linkRow, on && { backgroundColor: color.raised }]}
          >
            <View style={{ flex: 1 }}>
              <T numberOfLines={1}>
                {r.kind === "link" ? title(r.game_id) : r.title} · #
                {r.player_id}
                {r.kind === "link" && r.missing
                  ? ` · ${r.missing} missing`
                  : ""}
              </T>
              {r.kind === "suggestion" ? (
                <T style={styles.suggest} testID="suggestion-reason">
                  {r.face
                    ? "FACE SUGGESTION (opt-in) · confirm only if this is them"
                    : "SUGGESTION · needs your confirmation"}{" "}
                  · {r.reasons.join(" + ")}
                </T>
              ) : null}
            </View>
            {r.kind === "link" ? (
              <Pill
                label="Unlink"
                focused={on}
                testID="link-unlink"
                style={{ marginBottom: 0 }}
              />
            ) : (
              <>
                <Pill
                  label="Accept"
                  focused={on && col === 0}
                  testID="suggestion-accept"
                  style={{ marginBottom: 0 }}
                />
                <Pill
                  label="Decline"
                  focused={on && col === 1}
                  testID="suggestion-decline"
                  style={{ marginBottom: 0 }}
                />
              </>
            )}
          </View>
        );
      })}
      {note ? (
        <T style={styles.dim} testID="links-note">
          {note}
        </T>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", marginBottom: px(16) },
  badge: {
    color: color.floor,
    backgroundColor: color.chalk,
    fontWeight: "800",
    fontSize: font.small,
    paddingHorizontal: px(16),
    paddingVertical: px(4),
    borderRadius: px(8),
  },
  tabs: { flexDirection: "row", marginBottom: px(8) },
  row: { flexDirection: "row", flexWrap: "wrap", alignItems: "center" },
  dim: { color: color.dim, fontSize: font.small, marginVertical: px(6) },
  statRow: {
    flexDirection: "row",
    alignItems: "center",
    width: px(1300),
    paddingHorizontal: px(20),
    paddingVertical: px(4),
    borderRadius: px(10),
  },
  value: {
    width: px(200),
    textAlign: "right",
    fontFamily: face.figures,
    fontVariant: ["tabular-nums"],
  },
  stepper: {
    borderRadius: px(10),
    paddingHorizontal: px(8),
    backgroundColor: color.line,
  },
  flag: { width: px(360), marginLeft: px(24) },
  edited: { color: color.chalk, fontSize: font.small, fontWeight: "600" },
  cardTab: { flexDirection: "row" },
  cardImage: {
    width: px(405),
    height: px(540),
    borderRadius: px(12),
    backgroundColor: color.panel,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  tile: { width: px(170), marginRight: px(16), marginBottom: px(12) },
  tileValue: { fontSize: px(56), fontFamily: face.figures },
  reel: { flexDirection: "row" },
  reelIdle: {
    aspectRatio: 16 / 9,
    backgroundColor: color.panel,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: px(12),
  },
  counter: { position: "absolute", left: px(24), top: px(24) },
  counterText: {
    color: color.onAccent,
    backgroundColor: color.accent,
    fontWeight: "800",
    paddingHorizontal: px(16),
    borderRadius: px(8),
  },
  listRow: {
    paddingHorizontal: px(20),
    paddingVertical: px(6),
    borderRadius: px(12),
    marginBottom: px(8),
    backgroundColor: color.panel,
  },
  linkRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: px(20),
    paddingVertical: px(8),
    borderRadius: px(12),
    marginBottom: px(8),
  },
  suggest: { color: color.chalk, fontSize: font.small },
});
