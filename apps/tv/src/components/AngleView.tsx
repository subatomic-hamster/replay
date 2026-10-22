// A play's replay angles inside the player (M8; docs/ux/redesign.md "Do more": Angles and
// Free view). Watch swaps its game video for this while it is open: the play's
// pre-rendered angle videos, Left/Right cutting between them like broadcast cameras. The
// angles are time-aligned, so a cut is just a src swap on PlayerSurface, which resumes at
// the same media time and play state; the play loops. A cut shows the angle name and its
// honesty line big in the lower-left bug for ANGLE_BUG_MS, then they shrink. The badge
// ("Camera" / "Virtual replay") is always there: every recreated frame says so.
// Free view (Down, or straight from Do more): the angle player stays mounted and paused
// underneath; the scene starts at its time and hands its own time back on exit.
// Player's view (Tier C `pov:<pid>`, one per tracked player): one slot in the Left/Right
// cut, the key player's first; Up on it switches to the next player's eyes. It is a
// virtual view (the real players' cutouts on a reconstructed court, D-88), and the bug
// says so.
// Back: Free view → the angle → the game (Watch resumes it where it was). The top-left
// breadcrumb names where Back goes.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, View, useWindowDimensions } from "react-native";
import {
  ANGLE_BUG_MS,
  angleHonesty,
  angleLabel,
  cutOrder,
  cycleAngle,
  nextPov,
  povOf,
  RECREATED,
  tierBadge,
  type ReplayManifest,
} from "../../../../packages/tv-core/src/replays";
import type { SceneLayout } from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { PlayerSurface, type PlayerHandle } from "../playback/PlayerSurface";
import { FreeView } from "../scene/FreeView";
import {
  envelopeEdges,
  MIN_STEP_MS,
  presetState,
  stepCamera,
  type CameraAction,
  type CameraState,
} from "../scene/camera";
import { artFor } from "../gameState";
import { color, face, px, radius, safe, sp, type } from "../theme";
import {
  ApiErrorBanner,
  ContextChip,
  Fade,
  KeyLegend,
  Loading,
  T,
  useAsync,
} from "../ui";

/** Free view D-pad → camera step: Left/Right orbit, Up/Down height. */
const FREE_STEP: Partial<Record<DpadAction, CameraAction>> = {
  left: "left",
  right: "right",
  up: "up",
  down: "down",
};

/** A Free view preset's name; `real` sits inside a recreated scene, so not "Real camera". */
const presetName = (id: string | null, scene: SceneLayout) =>
  id === "real"
    ? "From the camera's spot"
    : (scene.presets.find((p) => p.id === id)?.label ?? "Free camera");

/** Where the Tier C burn-in ("VIRTUAL VIEW" top-left, to x 404 of 1280) ends. */
const TIER_C_BURN = 410 / 1280;

export function AngleView({
  gameId,
  playId,
  start,
  onBack,
  from = [],
}: {
  gameId: string;
  playId: string;
  /** the angle to open on, or "free" for Free view straight away */
  start: number | "free";
  /** Back from the angle (or from a Free view opened straight away). */
  onBack: (m: ReplayManifest | null) => void;
  /** The breadcrumb before "Replay angles": where Back returns, e.g. the game's title. */
  from?: string[];
}) {
  const {
    data: m,
    error,
    reload,
  } = useAsync(() => api.getReplay(gameId, playId), [gameId, playId]);
  const sceneUrl = m?.scene_url;
  // The scene layout loads with the manifest; a failure only hides Free view.
  const { data: scene } = useAsync(
    () => (sceneUrl ? api.getScene(gameId, playId) : Promise.resolve(null)),
    [sceneUrl, gameId, playId],
  );
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const [index, setIndex] = useState(start === "free" ? 0 : start);
  const [big, setBig] = useState(true);
  const [free, setFree] = useState<null | { start: number; paused: boolean }>(
    null,
  );
  const [cam, setCam] = useState<CameraState | null>(null);
  const [preset, setPreset] = useState<string | null>("real");
  const sceneTime = useRef(0);
  const resume = useRef<null | boolean>(null);
  // Free view chosen straight from Do more: Back from it goes back to the game.
  const freeOnly = useRef(start === "free");
  const lastPress = useRef<Partial<Record<CameraAction, number>>>({});
  const { width: winW, height: winH } = useWindowDimensions();
  const count = m?.angles.length ?? 0;
  // Left/Right walk the cut order (all virtual POVs share one slot)
  const order = useMemo(
    () => (m ? cutOrder(m.angles, Math.min(index, count - 1)) : []),
    [m, index, count],
  );

  // A replay starts playing; PlayerSurface holds the request until the media can play.
  useEffect(() => {
    if (m && handle && !freeOnly.current) handle.play();
  }, [m, handle]);

  // The big label shrinks ANGLE_BUG_MS after the last cut or preset change.
  useEffect(() => {
    if (!big) return;
    const timer = setTimeout(() => setBig(false), ANGLE_BUG_MS);
    return () => clearTimeout(timer);
  }, [big, index, preset]);

  // After leaving free view: the scene reported its final time while unmounting, so the
  // angle resumes exactly there.
  useEffect(() => {
    if (free || resume.current === null || !handle) return;
    handle.seek(sceneTime.current);
    if (resume.current) handle.play();
    resume.current = null;
  }, [free, handle]);

  const enterFree = useCallback(
    (sc: SceneLayout, playing: boolean) => {
      const t = handle?.currentTime() ?? 0;
      handle?.pause();
      sceneTime.current = t;
      setCam(presetState("real", sc));
      setPreset("real");
      setBig(true);
      setFree({ start: t, paused: !playing });
    },
    [handle],
  );

  // Free view straight from Do more: once the scene is in, playing from the play's start.
  // A play without a scene falls back to its angles.
  useEffect(() => {
    if (!freeOnly.current || free || !m) return;
    if (scene) enterFree(scene, true);
    else if (!sceneUrl) {
      freeOnly.current = false;
      handle?.play();
    }
  }, [scene, m, free, sceneUrl, enterFree, handle]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (free && scene) {
        const act = FREE_STEP[a];
        if (a === "back") {
          if (freeOnly.current) return onBack(m ?? null);
          resume.current = !free.paused;
          setFree(null);
        } else if (act) {
          const now = Date.now();
          const dt = now - (lastPress.current[act] ?? -Infinity);
          if (dt < MIN_STEP_MS) return; // auto-repeat faster than the hold rate
          lastPress.current[act] = now;
          setCam((c) => c && stepCamera(c, act, dt, scene));
          setPreset(null);
        } else if (a === "seek-fwd" || a === "seek-back") {
          const ids = scene.presets.map((p) => p.id);
          const i = preset ? ids.indexOf(preset) : a === "seek-fwd" ? -1 : 0;
          const next =
            ids[(i + (a === "seek-fwd" ? 1 : -1) + ids.length) % ids.length];
          setPreset(next);
          setCam(presetState(next, scene));
          setBig(true);
        } else if (a === "select" || a === "playpause")
          setFree({ ...free, paused: !free.paused });
        return;
      }
      if (a === "back") onBack(m ?? null);
      else if ((a === "left" || a === "right") && order.length > 1) {
        const k = Math.max(0, order.indexOf(index));
        setIndex(order[cycleAngle(k, order.length, a === "right" ? 1 : -1)]);
        setBig(true);
      } else if (a === "up" && m && povOf(m.angles[index])) {
        setIndex(nextPov(m.angles, index));
        setBig(true);
      } else if (a === "select" || a === "playpause") handle?.toggle();
      else if (a === "down" && scene) {
        freeOnly.current = false;
        enterFree(scene, !(handle?.paused() ?? true));
      }
    },
    [order, index, handle, free, scene, preset, m, onBack, enterFree],
  );
  useDpad(onAction);
  const onSceneTime = useCallback((t: number) => {
    sceneTime.current = t;
  }, []);

  if (error)
    return (
      <ApiErrorBanner error={error} onRetry={reload} art={artFor(gameId)} />
    );
  if (!m) return <Loading art={artFor(gameId)} />;
  const angle = m.angles[Math.min(index, count - 1)];
  if (!angle) {
    return (
      <View style={styles.empty} testID="replay">
        <T>This replay has no rendered angles.</T>
        <KeyLegend
          items={[{ k: "Back", label: "Game" }]}
          style={styles.legend}
        />
      </View>
    );
  }
  const stageW = Math.min(winW, (winH * 16) / 9);
  const pov = povOf(angle);
  const povs = m.angles.filter((a) => povOf(a)).length;
  const inFree = free && scene && cam;
  const freeData = inFree
    ? {
        preset: preset ?? "",
        az: cam.azimuth.toFixed(2),
        el: cam.elevation.toFixed(2),
        dist: cam.distance.toFixed(3),
        edges: envelopeEdges(cam, scene).join(" "),
        paused: free.paused ? "true" : "false",
      }
    : {};
  const honesty = angleHonesty(angle);
  const legend = inFree
    ? [
        { k: "◀▶", label: "Orbit" },
        { k: "▲▼", label: "Height" },
        { k: "Back", label: freeOnly.current ? "Game" : "Angles" },
      ]
    : [
        { k: "◀▶", label: "Angles" },
        ...(pov && povs > 1
          ? [{ k: "▲", label: "Next player" }]
          : scene
            ? [{ k: "▼", label: "Free view" }]
            : []),
        { k: "Back", label: "Game" },
      ];

  return (
    <View
      style={styles.screen}
      testID="replay"
      dataSet={{
        angle: angle.id,
        tier: angle.tier,
        index,
        pov: pov ?? "",
        cuts: order.length,
        mode: inFree ? "free" : "angles",
        free: scene ? "true" : "false",
        play: m.play_id,
        ...freeData,
      }}
    >
      <View style={{ width: stageW }}>
        <PlayerSurface
          ref={setHandle}
          src={angle.url}
          poster={artFor(gameId)}
          muted
          loop
        >
          {inFree ? (
            <FreeView
              layout={scene}
              camera={cam}
              paused={free.paused}
              startTimeSec={free.start}
              onTime={onSceneTime}
            />
          ) : null}
          <Fade side="top" length={px(200)} strength={0.7} />
          <Fade side="bottom" length={px(360)} strength={0.8} />
          {/* The breadcrumb; Tier C videos burn "VIRTUAL VIEW" top-left, so it moves
              past that burn-in. */}
          <View
            pointerEvents="none"
            style={[
              styles.crumb,
              angle.tier === "C" && !inFree && { left: stageW * TIER_C_BURN },
            ]}
          >
            <ContextChip
              kind="room"
              parts={[...from, "Replay angles", m.label]}
            />
          </View>
          {m.synthetic ? (
            <T style={[type.meta, styles.synthetic]} testID="replay-synthetic">
              Synthetic
            </T>
          ) : null}

          {inFree ? <FreeEdges edges={envelopeEdges(cam, scene)} /> : null}
          <View
            style={styles.bug}
            testID="replay-bug"
            dataSet={{ prominent: big ? "true" : "false" }}
          >
            <View style={styles.bugRow}>
              <View style={styles.tier}>
                <T
                  style={styles.tierText}
                  testID="replay-tier-badge"
                  dataSet={{ tier: inFree ? "B" : angle.tier }}
                >
                  {inFree ? tierBadge("B") : tierBadge(angle.tier)}
                </T>
              </View>
              {inFree ? (
                <T style={[type.meta, styles.dim]}>
                  Free view{free.paused ? ", paused" : ""}
                </T>
              ) : (
                <T style={[type.meta, styles.dim]} testID="replay-angle-pos">
                  {`${order.indexOf(index) + 1} of ${order.length}`}
                </T>
              )}
            </View>
            <T
              style={[type.body, big && type.title]}
              testID={inFree ? "free-preset-label" : "replay-angle-label"}
            >
              {inFree ? presetName(preset, scene) : angleLabel(angle)}
            </T>
            {inFree || honesty ? (
              <T
                style={[big ? type.body : type.meta, styles.honesty]}
                testID={
                  inFree
                    ? "free-honesty"
                    : pov
                      ? "pov-honesty"
                      : "angle-honesty"
                }
              >
                {inFree ? RECREATED : honesty}
              </T>
            ) : null}
          </View>

          <KeyLegend items={legend} style={styles.legend} />
        </PlayerSurface>
      </View>
    </View>
  );
}

/** Free view's limit, without words: a thin amber bar on each clamped screen edge. */
function FreeEdges({ edges }: { edges: string[] }) {
  return (
    <>
      {edges.includes("az-min") ? (
        <View style={[styles.edge, styles.edgeLeft]} testID="edge-az-min" />
      ) : null}
      {edges.includes("az-max") ? (
        <View style={[styles.edge, styles.edgeRight]} testID="edge-az-max" />
      ) : null}
      {edges.includes("el-max") ? (
        <View style={[styles.edge, styles.edgeTop]} testID="edge-el-max" />
      ) : null}
      {edges.includes("el-min") ? (
        <View style={[styles.edge, styles.edgeBottom]} testID="edge-el-min" />
      ) : null}
    </>
  );
}

const LEGEND_H = px(56);

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: "#000",
    alignItems: "center",
    justifyContent: "center",
  },
  empty: {
    flex: 1,
    backgroundColor: color.floor,
    paddingHorizontal: safe.x,
    paddingVertical: safe.y,
    justifyContent: "center",
  },
  // The breadcrumb's box (the chip places itself at the safe corner inside it).
  crumb: { position: "absolute", left: 0, right: 0, top: 0, height: px(160) },
  synthetic: {
    position: "absolute",
    right: safe.x,
    top: safe.y,
    color: color.bleacher,
  },
  dim: { color: color.bleacher },

  // Lower-left bug: badge and position on top, then the angle (or viewpoint) name and
  // the honesty line.
  bug: {
    position: "absolute",
    left: safe.x,
    bottom: safe.y + LEGEND_H + sp(2),
    maxWidth: px(900),
    paddingHorizontal: sp(3),
    paddingVertical: sp(2),
    borderRadius: radius.card,
    backgroundColor: "rgba(18, 26, 35, 0.84)",
  },
  bugRow: { flexDirection: "row", alignItems: "center" },
  tier: {
    paddingHorizontal: sp(1.5),
    borderRadius: radius.chip,
    backgroundColor: color.chalk,
    marginRight: sp(2),
  },
  tierText: { ...type.meta, color: color.floor, fontFamily: face.semibold },
  honesty: { marginTop: sp(1), color: color.bleacher },

  // A clamped envelope side: a thin amber bar on that screen edge.
  edge: {
    position: "absolute",
    backgroundColor: color.scoreboard,
    opacity: 0.6,
  },
  edgeLeft: { left: 0, top: 0, bottom: 0, width: px(10) },
  edgeRight: { right: 0, top: 0, bottom: 0, width: px(10) },
  edgeTop: { left: 0, right: 0, top: 0, height: px(10) },
  edgeBottom: { left: 0, right: 0, bottom: 0, height: px(10) },

  // No timeline in the room: the legend sits on the bottom safe line.
  legend: { bottom: safe.y, height: LEGEND_H },
});
