// A play's replay angles inside the player (M8; docs/ux/redesign.md "Do more": Angles and
// Free view). Watch swaps its game video for this while it is open: the play's
// pre-rendered angle videos, Left/Right cutting between them like broadcast cameras. The
// angles are time-aligned, so a cut is just a src swap on PlayerSurface, which resumes at
// the same media time and play state; the play loops. A cut shows the angle name big in
// the lower-left bug for ANGLE_BUG_MS, then it shrinks.
// Free view (2.5D, Down, or straight from Do more): the angle player stays mounted and
// paused underneath; the scene starts at its time and hands its own time back on exit.
// Back: Free view → the angle → the game (Watch resumes it where it was).
import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, View, useWindowDimensions } from "react-native";
import {
  ANGLE_BUG_MS,
  cycleAngle,
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
import { ApiErrorBanner, Fade, Hint, Loading, T, useAsync } from "../ui";

/** Free view D-pad → camera step; Up/Down dolly instead of elevating in zoom mode. */
const FREE_STEP: Partial<Record<DpadAction, [CameraAction, CameraAction]>> = {
  left: ["left", "left"],
  right: ["right", "right"],
  up: ["up", "zoom-in"],
  down: ["down", "zoom-out"],
};

export function AngleView({
  gameId,
  playId,
  start,
  onBack,
}: {
  gameId: string;
  playId: string;
  /** the angle to open on, or "free" for Free view straight away */
  start: number | "free";
  /** Back from the angle (or from a Free view opened straight away). */
  onBack: (m: ReplayManifest | null) => void;
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
  const [zoom, setZoom] = useState(false);
  const sceneTime = useRef(0);
  const resume = useRef<null | boolean>(null);
  // Free view chosen straight from Do more: Back from it goes back to the game.
  const freeOnly = useRef(start === "free");
  const lastPress = useRef<Partial<Record<CameraAction, number>>>({});
  const { width: winW, height: winH } = useWindowDimensions();
  const count = m?.angles.length ?? 0;

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
      setZoom(false);
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
        const step = FREE_STEP[a];
        if (a === "back") {
          if (freeOnly.current) return onBack(m ?? null);
          resume.current = !free.paused;
          setFree(null);
        } else if (step) {
          const act = step[zoom ? 1 : 0];
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
        } else if (a === "menu") setZoom((z) => !z);
        else if (a === "select" || a === "playpause")
          setFree({ ...free, paused: !free.paused });
        return;
      }
      if (a === "back") onBack(m ?? null);
      else if ((a === "left" || a === "right") && count > 1) {
        setIndex((i) => cycleAngle(i, count, a === "right" ? 1 : -1));
        setBig(true);
      } else if (a === "select" || a === "playpause") handle?.toggle();
      else if (a === "down" && scene) {
        freeOnly.current = false;
        enterFree(scene, !(handle?.paused() ?? true));
      }
    },
    [count, handle, free, scene, zoom, preset, m, onBack, enterFree],
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
        <Hint k="Back">The game</Hint>
      </View>
    );
  }
  const stageW = Math.min(winW, (winH * 16) / 9);
  const inFree = free && scene && cam;
  const freeData = inFree
    ? {
        preset: preset ?? "",
        az: cam.azimuth.toFixed(2),
        el: cam.elevation.toFixed(2),
        dist: cam.distance.toFixed(3),
        edges: envelopeEdges(cam, scene).join(" "),
        zoom: zoom ? "true" : "false",
        paused: free.paused ? "true" : "false",
      }
    : {};

  return (
    <View
      style={styles.screen}
      testID="replay"
      dataSet={{
        angle: angle.id,
        tier: angle.tier,
        index,
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
          <View style={styles.top}>
            <T
              style={[type.meta, styles.title]}
              numberOfLines={1}
              testID="replay-title"
            >
              {m.label}
            </T>
            {m.synthetic ? (
              <T style={[type.meta, styles.dim]} testID="replay-synthetic">
                Synthetic
              </T>
            ) : null}
          </View>

          {inFree ? (
            <FreeHud
              scene={scene}
              cam={cam}
              preset={preset}
              big={big}
              paused={free.paused}
            />
          ) : (
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
                    dataSet={{ tier: angle.tier }}
                  >
                    {tierBadge(angle.tier)}
                  </T>
                </View>
                <T style={[type.meta, styles.dim]} testID="replay-angle-pos">
                  {`${index + 1} / ${count}`}
                </T>
              </View>
              <T
                style={[type.body, big && type.title]}
                testID="replay-angle-label"
              >
                {angle.label}
              </T>
            </View>
          )}

          <View style={styles.hints}>
            <Hint k="◀ ▶" style={styles.hint}>
              {inFree ? "Orbit" : "Angles"}
            </Hint>
            {inFree ? (
              <>
                <Hint k="▲ ▼" style={styles.hint}>
                  {zoom ? "Zoom" : "Height"}
                </Hint>
                <Hint k="Menu" style={styles.hint}>
                  {zoom ? "Height" : "Zoom"}
                </Hint>
              </>
            ) : scene ? (
              <Hint k="▼" style={styles.hint}>
                Free view
              </Hint>
            ) : null}
            <Hint k="Back" style={styles.hint}>
              {inFree && !freeOnly.current ? "The angle" : "The game"}
            </Hint>
          </View>
        </PlayerSurface>
      </View>
    </View>
  );
}

/** Free view overlay: preset bug, the envelope as a small gauge (the limit is part of
 *  the picture, not hidden), edge bars on a clamped side and the D-54 honesty label. */
function FreeHud({
  scene,
  cam,
  preset,
  big,
  paused,
}: {
  scene: SceneLayout;
  cam: CameraState;
  preset: string | null;
  big: boolean;
  paused: boolean;
}) {
  const env = scene.envelope;
  const edges = envelopeEdges(cam, scene);
  const real = presetState("real", scene);
  const frac = (v: number, [lo, hi]: [number, number]) =>
    hi > lo ? (v - lo) / (hi - lo) : 0.5;
  const at = (az: number, el: number) => ({
    left: `${frac(az, env.azimuth_deg) * 100}%` as const,
    bottom: `${frac(el, env.elevation_deg) * 100}%` as const,
  });
  const label =
    scene.presets.find((p) => p.id === preset)?.label ?? "Free camera";
  const sign = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}°`;
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

      <View
        style={styles.bug}
        testID="replay-bug"
        dataSet={{ prominent: big ? "true" : "false" }}
      >
        <View style={styles.bugRow}>
          <View style={styles.tier}>
            <T style={styles.tierText} testID="replay-tier-badge">
              2.5D
            </T>
          </View>
          <T style={[type.meta, styles.dim]}>
            Free view{paused ? ", paused" : ""}
          </T>
        </View>
        <T style={[type.body, big && type.title]} testID="free-preset-label">
          {label}
        </T>
        <T style={[styles.figures, styles.dim]} testID="free-readout">
          {`${sign(cam.azimuth)}  ${cam.elevation.toFixed(1)}°  ${cam.distance.toFixed(1)} m`}
        </T>
        <T style={[type.meta, styles.honesty]} testID="free-honesty">
          {scene.honesty_label}
        </T>
        {/camera saw/i.test(scene.honesty_label) ? null : (
          <T style={[type.meta, styles.dim]} testID="free-limit">
            View limited to what the camera saw
          </T>
        )}
      </View>

      <View style={styles.gaugeBox} testID="free-gauge">
        <T style={[type.meta, styles.dim]}>View limit</T>
        <View style={styles.gauge}>
          <View style={[styles.gaugeReal, at(real.azimuth, real.elevation)]} />
          <View
            style={[styles.gaugeDot, at(cam.azimuth, cam.elevation)]}
            testID="free-gauge-dot"
          />
        </View>
        <T style={type.meta}>
          {edges.includes("d-min")
            ? "closest"
            : edges.includes("d-max")
              ? "farthest"
              : `±${Math.max(-env.azimuth_deg[0], env.azimuth_deg[1]).toFixed(0)}° wide`}
        </T>
      </View>
    </>
  );
}

const HINTS_H = px(56);

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
  top: {
    position: "absolute",
    left: safe.x,
    right: safe.x,
    top: safe.y,
    flexDirection: "row",
    alignItems: "center",
  },
  title: { flexShrink: 1, marginRight: sp(3) },
  dim: { color: color.bleacher },
  figures: { ...type.figures, fontSize: px(26), marginTop: sp(0.5) },

  // Lower-left bug: tier and position on top, the angle (or preset) name below.
  bug: {
    position: "absolute",
    left: safe.x,
    bottom: safe.y + HINTS_H + sp(2),
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
  honesty: { marginTop: sp(1) },

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

  // The envelope: azimuth across, elevation up; ring = the real camera, dot = this view.
  gaugeBox: {
    position: "absolute",
    right: safe.x,
    bottom: safe.y + HINTS_H + sp(2),
    padding: sp(2),
    borderRadius: radius.card,
    backgroundColor: "rgba(18, 26, 35, 0.84)",
    alignItems: "center",
  },
  gauge: {
    width: px(220),
    height: px(110),
    marginVertical: sp(1),
    borderWidth: px(3),
    borderColor: color.line,
    borderRadius: px(4),
  },
  gaugeReal: {
    position: "absolute",
    width: px(22),
    height: px(22),
    marginLeft: px(-11),
    marginBottom: px(-11),
    borderRadius: px(11),
    borderWidth: px(3),
    borderColor: color.bleacher,
  },
  gaugeDot: {
    position: "absolute",
    width: px(18),
    height: px(18),
    marginLeft: px(-9),
    marginBottom: px(-9),
    borderRadius: px(9),
    backgroundColor: color.scoreboard,
  },

  hints: {
    position: "absolute",
    left: safe.x,
    right: safe.x,
    bottom: safe.y,
    height: HINTS_H,
    flexDirection: "row",
    alignItems: "center",
  },
  hint: { marginTop: 0, marginRight: sp(4) },
});
