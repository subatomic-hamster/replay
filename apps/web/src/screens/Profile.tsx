// M10 profile on the web TV (/tv/players/:id): per-sport career stats (corrections flagged
// EDITED with the auto value kept beside them), the collectible card (PNG from the API +
// its JSON), the career reel (the player's plays across games, played in order) and link
// management (unlink; accept or decline suggestions — face ones only ever for a
// face-enrolled profile). apps/tv/src/screens/Profile.tsx is the same screen on RN.
//
// Keys: ←/→ pick a tab, ↓ or Enter enters it, ↑ from its top row or Escape returns to the
// tabs, Escape on the tabs leaves. Never branches on the sport (D-58).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Avatar } from "../components/Avatar";
import { useDpad, type DpadAction } from "../platform/keys";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { useClockTime } from "../playback/clock";
import { navigate, useLocation } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import { fmtClock, listWindow } from "../../../../packages/tv-core/src/discovery";
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

const TABS = ["Stats", "Card", "Reel", "Links"] as const;
const STAT_ROWS = 8;
const LIST_ROWS = 6;

interface TabProps {
  profile: ProfileDoc;
  active: boolean;
  onExit: () => void;
  onChange: (p: ProfileDoc) => void;
}

export function Profile({ profileId }: { profileId: string }) {
  const from = useLocation().params.get("from");
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
      if (a === "back") navigate(`/tv/players${from ? `?from=${from}` : ""}`);
      else if (a === "left") setTab((i) => Math.max(0, i - 1));
      else if (a === "right") setTab((i) => Math.min(TABS.length - 1, i + 1));
      else if (a === "down" || a === "select") setZone("body");
    },
    [from],
  );
  useDpad(onAction, zone === "tabs");
  const exit = useCallback(() => setZone("tabs"), []);

  if (error) return <ApiErrorBanner error={error} onRetry={() => setNonce((n) => n + 1)} />;
  if (!profile) return <div className="screen">Loading…</div>;

  const props: TabProps = { profile, active: zone === "body", onExit: exit, onChange: setProfile };
  return (
    <div
      className="screen profile"
      data-testid="profile"
      data-profile-id={profileId}
      data-zone={zone}
      data-tab={TABS[tab].toLowerCase()}
    >
      <header className="profile-head">
        <Avatar name={profile.name} photo={profile.photo_url} size={128} />
        <div>
          <h1 data-testid="profile-name">{profile.name}</h1>
          <p className="dim" data-testid="profile-sports">
            {sportsText(profile)}
            {profile.positions.length ? ` · ${profile.positions.join(" / ")}` : ""}
          </p>
        </div>
        {profile.face_enrolled ? (
          <span className="clip-badge" data-testid="face-enrolled">
            FACE ENROLLED (OPT-IN)
          </span>
        ) : null}
      </header>
      <div className="chips">
        {TABS.map((name, i) => (
          <span
            key={name}
            className={`chip${zone === "tabs" && i === tab ? " focused" : ""}${i === tab ? " active" : ""}`}
            data-testid={`profile-tab-${name.toLowerCase()}`}
            data-focused={zone === "tabs" && i === tab ? "true" : "false"}
          >
            {name}
          </span>
        ))}
      </div>
      {tab === 0 ? <StatsTab {...props} /> : null}
      {tab === 1 ? <CardTab {...props} /> : null}
      {tab === 2 ? <ReelTab {...props} /> : null}
      {tab === 3 ? <LinksTab {...props} /> : null}
      <p className="hint">
        {zone === "tabs" ? (
          <>
            <b>←/→</b> pick a tab · <b>↓</b> enters it · <b>Escape</b> returns to Players
          </>
        ) : (
          <>
            <b>↑/↓</b> move · <b>Enter</b> acts · <b>Escape</b> returns to the tabs
          </>
        )}
      </p>
    </div>
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
  const [edit, setEdit] = useState<{ key: string; value: number; at: 0 | 1 } | null>(null);
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
        else if ((a === "left" || a === "right") && edit.at === 0) {
          setEdit({ ...edit, value: stepStat(edit.value, a === "right" ? 1 : -1) });
        } else if (a === "down" && r?.edited) setEdit({ ...edit, at: 1 });
        else if (a === "up") setEdit({ ...edit, at: 0 });
        else if (a === "select") save(edit.key, edit.at === 0 ? edit.value : null);
        return;
      }
      if (a === "back") onExit();
      else if (a === "up") {
        if (row > (multi ? -1 : 0)) setRow(row - 1);
        else onExit();
      } else if (a === "down") setRow((i) => Math.min(rows.length - 1, i + 1));
      else if ((a === "left" || a === "right") && row === -1) {
        setSportIdx((i) => Math.max(0, Math.min(sports.length - 1, i + (a === "right" ? 1 : -1))));
      } else if (a === "select" && rows[row]?.editable) {
        setEdit({ key: rows[row].key, value: rows[row].value, at: 0 });
        setNote("");
      }
    },
    [edit, rows, row, multi, sports.length, save, onExit],
  );
  useDpad(onAction, active);

  if (!sports.length) return <p data-testid="stats-empty">No stats yet: link this player to a game first.</p>;
  const s = bySport[sport];
  const first = listWindow(Math.max(0, row), rows.length, STAT_ROWS);
  return (
    <section data-testid="stats-tab" data-sport={sport}>
      {multi ? (
        <div className="chips">
          {sports.map((x, i) => (
            <span
              key={x}
              className={`chip${active && row === -1 && i === sportIdx ? " focused" : ""}${i === sportIdx ? " active" : ""}`}
              data-testid={`stats-sport-${x}`}
              data-focused={active && row === -1 && i === sportIdx ? "true" : "false"}
            >
              {x[0].toUpperCase() + x.slice(1)}
            </span>
          ))}
        </div>
      ) : null}
      <p className="dim" data-testid="stats-label">
        {s?.label === "auto-detected" ? "Auto-detected" : "Stats"} across {s?.stats.games ?? 0} linked{" "}
        {s?.stats.games === 1 ? "game" : "games"} · corrections are marked EDITED, the auto value is kept
      </p>
      <ul className="stat-list">
        {rows.slice(first, first + STAT_ROWS).map((r, k) => {
          const on = active && first + k === row;
          const editing = edit?.key === r.key;
          return (
            <li
              key={r.key}
              className={`stat-row${on && !editing ? " focused" : ""}${on ? " current" : ""}`}
              data-testid="stat-row"
              data-key={r.key}
              data-edited={r.edited ? "true" : "false"}
              data-focused={on ? "true" : "false"}
              data-value={r.value}
            >
              <span className="stat-label">{r.label}</span>
              {editing ? (
                <>
                  <span
                    className={`stat-stepper${edit.at === 0 ? " focused" : ""}`}
                    data-testid="stat-edit"
                    data-value={edit.value}
                  >
                    ◀ {edit.value} ▶
                  </span>
                  {r.edited ? (
                    <span
                      className={`btn${edit.at === 1 ? " focused" : ""}`}
                      data-testid="stat-use-auto"
                      data-focused={edit.at === 1 ? "true" : "false"}
                    >
                      Use auto ({r.auto ?? "none"})
                    </span>
                  ) : null}
                </>
              ) : (
                <span className="stat-value" data-testid="stat-value">
                  {r.value}
                </span>
              )}
              <span className="stat-flag">
                {r.edited ? (
                  <span className="edited" data-testid="stat-edited">
                    EDITED · auto {r.auto ?? "–"}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
      {note ? (
        <p className="dim" data-testid="stat-note">
          {note}
        </p>
      ) : null}
      {edit ? (
        <p className="hint">
          <b>←/→</b> change the value · <b>Enter</b> saves · <b>↓</b> use the auto value · <b>Escape</b> cancels
        </p>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------- collectible card

function CardTab({ profile, active, onExit }: TabProps) {
  const [card, setCard] = useState<PlayerCard | null>(null);
  const [note, setNote] = useState("");
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getCard(profile.profile_id).then(setCard, (e: Error) => setNote(`No card: ${e.message}`));
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

  if (!card) return <p data-testid="card-note">{note || "Loading the card…"}</p>;
  const png = `${api.profileMediaUrl(card.png)}${version ? `?v=${version}` : ""}`;
  return (
    <section className="card-tab" data-testid="card-tab" data-rendered={card.rendered ? "true" : "false"}>
      <div className="card-image">
        {card.rendered ? (
          <img src={png} alt={`${card.name} player card`} data-testid="card-png" />
        ) : (
          <span className="dim">No card image yet. Press Enter on “Render card”.</span>
        )}
      </div>
      <div data-testid="card-json">
        <h2 className="card-title" data-testid="card-title">
          {card.title}
        </h2>
        <p className="dim">
          {[card.sport, card.games === 1 ? "1 game" : `${card.games} games`, card.positions.join(" / ")]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <div className="card-tiles">
          {card.stats.map((t) => (
            <div key={t.key} className="card-tile" data-testid="card-tile" data-key={t.key} data-edited={t.edited ? "true" : "false"}>
              <b>{String(t.value)}</b>
              <span className="dim">{t.label}</span>
              {t.edited ? <span className="edited">EDITED</span> : null}
            </div>
          ))}
        </div>
        <p className="dim">
          {card.label === "auto-detected" ? "Auto-detected stats" : card.label}
          {card.user_edited ? " · edited values marked" : ""}
          {card.title_source
            ? ` · title: ${card.title_source === "llm" ? "rephrased, fact-checked" : "fact-checked template"}`
            : ""}
        </p>
        {card.best_moment ? (
          <p className="dim" data-testid="card-best">
            Best moment: {card.best_moment.game_id} at {fmtClock(card.best_moment.t ?? card.best_moment.t_start)}
          </p>
        ) : null}
        <span
          className={`btn${active ? " focused" : ""}`}
          data-testid="card-render"
          data-focused={active ? "true" : "false"}
        >
          {card.rendered ? "Re-render card" : "Render card"}
        </span>
        {note ? (
          <p className="dim" data-testid="card-note">
            {note}
          </p>
        ) : null}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- career reel

function ReelTab({ profile, active, onExit }: TabProps) {
  const { data: reel, error } = useAsync(() => api.getReel(profile.profile_id), [profile]);
  const items = useMemo(() => playableReel(reel), [reel]);
  const [focus, setFocus] = useState(0);
  const [cur, setCur] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const t = useClockTime(handle?.clock ?? null, 1 / 10);
  const armed = useRef(false);
  const item = cur !== null ? items[cur] : undefined;

  // Each item starts at its play's start once its video knows its duration; a new game is
  // a new <video> (keyed by URL), so the old one's position never leaks in.
  useEffect(() => {
    armed.current = false;
    if (!handle || !item) return;
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
      } else if (a === "down") setFocus((i) => Math.min(items.length - 1, i + 1));
      else if (a === "select" && items[focus]) {
        setCur(focus);
        setNonce((n) => n + 1);
      } else if (a === "playpause") handle?.toggle();
    },
    [focus, items, handle, onExit],
  );
  useDpad(onAction, active);

  if (error) return <p data-testid="reel-note">No reel: {error.message}</p>;
  if (!reel) return <p>Loading the reel…</p>;
  if (!items.length) return <p data-testid="reel-empty">No plays yet: link this player to a processed game.</p>;
  const first = listWindow(focus, items.length, LIST_ROWS);
  return (
    <section className="clips-layout" data-testid="reel-tab">
      <div className="surface">
        {item?.url ? (
          <PlayerSurface key={item.url} ref={setHandle} src={item.url} muted>
            <div
              className="rally-counter"
              data-testid="reel-counter"
              data-index={(cur ?? 0) + 1}
              data-game-id={item.game_id}
              data-play-id={item.play_id}
            >
              PLAY {(cur ?? 0) + 1} / {items.length} · {item.game_title ?? item.game_id}
            </div>
          </PlayerSurface>
        ) : (
          <div className="reel-idle dim">
            {items.length} plays · {fmtClock(reel.duration_s)} · Enter on a play starts the reel there
          </div>
        )}
      </div>
      <ul className="clip-list">
        {items.slice(first, first + LIST_ROWS).map((it, k) => {
          const i = first + k;
          const on = active && i === focus;
          return (
            <li
              key={`${it.game_id}/${it.play_id}`}
              className={`clip-card${on ? " focused" : ""}${i === cur ? " current" : ""}`}
              data-testid="reel-item"
              data-index={i}
              data-focused={on ? "true" : "false"}
              data-current={i === cur ? "true" : "false"}
              data-game-id={it.game_id}
              data-t-start={it.t_start}
            >
              <div>{it.game_title ?? it.game_id}</div>
              <div className="dim">
                {fmtClock(it.t_start)}–{fmtClock(it.t_end)}
                {it.points ? ` · ${it.points} pts` : ""}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------- links + suggestions

type LinkRow =
  | { kind: "link"; game_id: string; player_id: string; missing?: string }
  | { kind: "suggestion"; game_id: string; player_id: string; title: string; reasons: string[]; face: boolean };

function LinksTab({ profile, active, onExit, onChange }: TabProps) {
  const id = profile.profile_id;
  const { data: games } = useAsync(() => api.listGames(), []);
  const { data: raw, reload } = useAsync(() => api.getSuggestions(id), [id, profile]);
  const [declined, setDeclined] = useState<Set<string>>(new Set());
  const [row, setRow] = useState(0);
  const [col, setCol] = useState(0);
  const [note, setNote] = useState("");
  const title = useCallback((g: string) => games?.find((x) => x.id === g)?.title ?? g, [games]);

  const rows = useMemo<LinkRow[]>(() => {
    const missing = new Map((profile.missing_links ?? []).map((m) => [suggestionKey(m), m.missing]));
    return [
      ...profile.linked.map((l): LinkRow => ({ kind: "link", ...l, missing: missing.get(suggestionKey(l)) })),
      ...visibleSuggestions(profile, raw ?? [], declined).map(
        (s): LinkRow => ({
          kind: "suggestion",
          game_id: s.game_id,
          player_id: s.player_id,
          title: s.game_title ?? s.game_id,
          reasons: s.reasons.map(reasonText),
          face: s.reasons.some((r) => r.kind === "face"),
        }),
      ),
    ];
  }, [profile, raw, declined]);

  const act = useCallback(
    (r: LinkRow, c: number) => {
      const done = (msg: string) => (p: ProfileDoc) => {
        onChange(p);
        reload();
        setNote(msg);
      };
      const fail = (e: Error) => setNote(`Failed: ${e.message}`);
      if (r.kind === "link") {
        api.unlinkProfile(id, r.game_id, r.player_id).then(done(`Unlinked #${r.player_id} in ${title(r.game_id)}`), fail);
      } else if (c === 0) {
        api.linkProfile(id, r.game_id, r.player_id).then(done(`Linked #${r.player_id} in ${title(r.game_id)}`), fail);
      } else {
        setDeclined((s) => new Set(s).add(suggestionKey(r)));
        setNote("Suggestion declined");
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

  const n = profile.linked.length;
  const first = listWindow(row, rows.length, LIST_ROWS);
  return (
    <section data-testid="links-tab">
      <p className="dim">
        Linked in {n} {n === 1 ? "game" : "games"} · {SUGGESTION_NOTE}
      </p>
      {rows.length === 0 ? <p data-testid="links-empty">No links or suggestions yet.</p> : null}
      <ul className="link-list">
        {rows.slice(first, first + LIST_ROWS).map((r, k) => {
          const on = active && first + k === row;
          return (
            <li
              key={`${r.kind}/${suggestionKey(r)}`}
              className={`link-row${on ? " current" : ""}`}
              data-testid={r.kind === "link" ? "link-row" : "suggestion-row"}
              data-game-id={r.game_id}
              data-player-id={r.player_id}
              data-focused={on ? "true" : "false"}
              data-face={r.kind === "suggestion" && r.face ? "true" : "false"}
            >
              <div className="link-text">
                <div>
                  {r.kind === "link" ? title(r.game_id) : r.title} · #{r.player_id}
                  {r.kind === "link" && r.missing ? ` · ${r.missing} missing` : ""}
                </div>
                {r.kind === "suggestion" ? (
                  <div className="suggest" data-testid="suggestion-reason">
                    {r.face
                      ? "FACE SUGGESTION (opt-in) · confirm only if this is them"
                      : "SUGGESTION · needs your confirmation"}{" "}
                    · {r.reasons.join(" + ")}
                  </div>
                ) : null}
              </div>
              {r.kind === "link" ? (
                <span className={`btn${on ? " focused" : ""}`} data-testid="link-unlink" data-focused={on ? "true" : "false"}>
                  Unlink
                </span>
              ) : (
                <>
                  <span
                    className={`btn${on && col === 0 ? " focused" : ""}`}
                    data-testid="suggestion-accept"
                    data-focused={on && col === 0 ? "true" : "false"}
                  >
                    Accept
                  </span>
                  <span
                    className={`btn${on && col === 1 ? " focused" : ""}`}
                    data-testid="suggestion-decline"
                    data-focused={on && col === 1 ? "true" : "false"}
                  >
                    Decline
                  </span>
                </>
              )}
            </li>
          );
        })}
      </ul>
      {note ? (
        <p className="dim" data-testid="links-note">
          {note}
        </p>
      ) : null}
    </section>
  );
}
