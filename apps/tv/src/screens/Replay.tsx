// M8 multi-angle replays. ReplayList: the game's rendered replays as cards (reached from
// the Watch action row's "Replays", shown when the game has any). Replay: one highlight
// where Left/Right cut between its pre-rendered angle videos like broadcast cameras.
// The angles are time-aligned, so a cut is just a src swap on PlayerSurface, which resumes
// at the same media time and play state; the highlight loops at the end. A cut shows the
// angle name big in the lower-left bug for ANGLE_BUG_MS, then it shrinks.
// Back: Replay → ReplayList → Watch.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, View, useWindowDimensions } from "react-native";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import { ANGLE_BUG_MS, cycleAngle, tierBadge, type ReplayTier } from "../../../../packages/tv-core/src/replays";
import type { SceneLayout } from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
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
import { color, focusRing, font, px } from "../theme";
import { ApiErrorBanner, Hint, Loading, T, styles as ui, useAsync } from "../ui";

const TIER_COLOR: Record<ReplayTier, string> = { A: color.made, B: color.dot, C: "#c9a7ff" };

export function ReplayList({ gameId }: { gameId: string }) {
  const { data, error, reload } = useAsync(() => api.listReplays(gameId), [gameId]);
  const [focus, setFocus] = useState(0);
  const replays = useMemo(() => data ?? [], [data]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") navigate({ name: "watch", gameId });
      else if (replays.length === 0) return;
      else if (a === "down" || a === "right") setFocus((i) => Math.min(replays.length - 1, i + 1));
      else if (a === "up" || a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "select") navigate({ name: "replay", gameId, playId: replays[focus].play_id });
    },
    [gameId, replays, focus],
  );
  useDpad(onAction);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!data) return <Loading />;

  return (
    <View style={ui.screen} testID="replay-list">
      <T style={ui.h1}>Replays</T>
      {replays.length === 0 ? <T testID="replay-list-empty">No replays rendered for this game yet.</T> : null}
      {replays.map((r, i) => {
        const on = i === focus;
        return (
          <View
            key={r.play_id}
            testID="replay-card"
            dataSet={{ playId: r.play_id, focused: on ? "true" : "false" }}
            style={[styles.card, focusRing(on), on && { backgroundColor: color.raised }]}
          >
            <T style={styles.cardTitle} numberOfLines={1}>
              {r.label}
            </T>
            <T style={styles.cardMeta}>
              {r.angles} angles · {fmtDuration(r.t_end - r.t_start)}
            </T>
          </View>
        );
      })}
      <Hint>Up/Down move · Select opens a replay · Back to the game</Hint>
    </View>
  );
}

/** Free view D-pad → camera step; Up/Down dolly instead of elevating in zoom mode. */
const FREE_STEP: Partial<Record<DpadAction, [CameraAction, CameraAction]>> = {
  left: ["left", "left"],
  right: ["right", "right"],
  up: ["up", "zoom-in"],
  down: ["down", "zoom-out"],
};

export function Replay({ gameId, playId }: { gameId: string; playId: string }) {
  const { data: m, error, reload } = useAsync(() => api.getReplay(gameId, playId), [gameId, playId]);
  const sceneUrl = m?.scene_url;
  // The scene layout loads with the manifest; a failure only hides the Free view entry.
  const { data: scene } = useAsync(
    () => (sceneUrl ? api.getScene(gameId, playId) : Promise.resolve(null)),
    [sceneUrl, gameId, playId],
  );
  const [handle, setHandle] = useState<PlayerHandle | null>(null);
  const [index, setIndex] = useState(0);
  const [big, setBig] = useState(true);
  // Free view (2.5D): the angle player stays mounted and paused underneath; the scene
  // starts at its time and hands its own time back on exit (time-locked like a cut).
  const [free, setFree] = useState<null | { start: number; paused: boolean }>(null);
  const [cam, setCam] = useState<CameraState | null>(null);
  const [preset, setPreset] = useState<string | null>("real");
  const [zoom, setZoom] = useState(false);
  const sceneTime = useRef(0);
  const resume = useRef<null | boolean>(null);
  const lastPress = useRef<Partial<Record<CameraAction, number>>>({});
  const { width: winW, height: winH } = useWindowDimensions();
  const count = m?.angles.length ?? 0;

  // A replay starts playing; PlayerSurface holds the request until the media can play.
  useEffect(() => {
    if (m && handle) handle.play();
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

  const onAction = useCallback(
    (a: DpadAction) => {
      if (free && scene) {
        const step = FREE_STEP[a];
        if (a === "back") {
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
          const next = ids[(i + (a === "seek-fwd" ? 1 : -1) + ids.length) % ids.length];
          setPreset(next);
          setCam(presetState(next, scene));
          setBig(true);
        } else if (a === "menu") setZoom((z) => !z);
        else if (a === "select" || a === "playpause") setFree({ ...free, paused: !free.paused });
        return;
      }
      if (a === "back") navigate({ name: "replays", gameId });
      else if ((a === "left" || a === "right") && count > 1) {
        setIndex((i) => cycleAngle(i, count, a === "right" ? 1 : -1));
        setBig(true);
      } else if (a === "select" || a === "playpause") handle?.toggle();
      else if (a === "down" && scene) {
        const t = handle?.currentTime() ?? 0;
        const paused = handle?.paused() ?? true;
        handle?.pause();
        sceneTime.current = t;
        setCam(presetState("real", scene));
        setPreset("real");
        setZoom(false);
        setBig(true);
        setFree({ start: t, paused });
      }
    },
    [gameId, count, handle, free, scene, zoom, preset],
  );
  useDpad(onAction);
  const onSceneTime = useCallback((t: number) => {
    sceneTime.current = t;
  }, []);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!m) return <Loading />;
  const angle = m.angles[index];
  if (!angle) {
    return (
      <View style={ui.screen} testID="replay">
        <T>This replay has no rendered angles.</T>
        <Hint>Back to replays</Hint>
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
      dataSet={{ angle: angle.id, tier: angle.tier, index, mode: inFree ? "free" : "angles", ...freeData }}
    >
      <View style={{ width: stageW }}>
        <PlayerSurface ref={setHandle} src={angle.url} muted loop>
          {inFree ? (
            <FreeView
              layout={scene}
              camera={cam}
              paused={free.paused}
              startTimeSec={free.start}
              onTime={onSceneTime}
            />
          ) : null}
          <View style={styles.top}>
            <T style={styles.kicker}>REPLAY</T>
            <T style={styles.title} numberOfLines={1} testID="replay-title">
              {m.label}
            </T>
            {m.synthetic ? (
              <T style={styles.synthetic} testID="replay-synthetic">
                SYNTHETIC
              </T>
            ) : null}
          </View>

          {inFree ? (
            <FreeHud scene={scene} cam={cam} preset={preset} zoom={zoom} big={big} paused={free.paused} />
          ) : (
            <View style={styles.bug} testID="replay-bug" dataSet={{ prominent: big ? "true" : "false" }}>
              <View style={styles.bugRow}>
                <View style={[styles.tier, { backgroundColor: TIER_COLOR[angle.tier] ?? color.dim }]}>
                  <T style={styles.tierText} testID="replay-tier-badge" dataSet={{ tier: angle.tier }}>
                    {tierBadge(angle.tier)}
                  </T>
                </View>
                <T style={styles.arrow}>◀</T>
                <T style={styles.pos} testID="replay-angle-pos">
                  {`${index + 1} / ${count}`}
                </T>
                <T style={styles.arrow}>▶</T>
              </View>
              <T style={[styles.angle, big && styles.angleBig]} testID="replay-angle-label">
                {angle.label}
              </T>
            </View>
          )}

          <View style={styles.hintBar}>
            <Hint>
              {inFree
                ? `◀ ▶ orbit · ▲ ▼ ${zoom ? "zoom" : "height"} (Menu: ${zoom ? "height" : "zoom"}) · Rew/FF presets · Select plays/pauses · Back to the video`
                : `◀ ▶ cut between camera angles${scene ? " · ▼ Free view (2.5D)" : ""} · Select plays/pauses · Back to replays`}
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
  zoom,
  big,
  paused,
}: {
  scene: SceneLayout;
  cam: CameraState;
  preset: string | null;
  zoom: boolean;
  big: boolean;
  paused: boolean;
}) {
  const env = scene.envelope;
  const edges = envelopeEdges(cam, scene);
  const real = presetState("real", scene);
  const frac = (v: number, [lo, hi]: [number, number]) => (hi > lo ? (v - lo) / (hi - lo) : 0.5);
  const at = (az: number, el: number) => ({
    left: `${frac(az, env.azimuth_deg) * 100}%` as const,
    bottom: `${frac(el, env.elevation_deg) * 100}%` as const,
  });
  const label = scene.presets.find((p) => p.id === preset)?.label ?? "Free camera";
  const sign = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}°`;
  return (
    <>
      {edges.includes("az-min") ? <View style={[styles.edge, styles.edgeLeft]} testID="edge-az-min" /> : null}
      {edges.includes("az-max") ? <View style={[styles.edge, styles.edgeRight]} testID="edge-az-max" /> : null}
      {edges.includes("el-max") ? <View style={[styles.edge, styles.edgeTop]} testID="edge-el-max" /> : null}
      {edges.includes("el-min") ? <View style={[styles.edge, styles.edgeBottom]} testID="edge-el-min" /> : null}

      <View style={styles.bug} testID="replay-bug" dataSet={{ prominent: big ? "true" : "false" }}>
        <View style={styles.bugRow}>
          <View style={[styles.tier, { backgroundColor: TIER_COLOR.B }]}>
            <T style={styles.tierText} testID="replay-tier-badge">
              2.5D
            </T>
          </View>
          <T style={styles.pos}>FREE VIEW{paused ? " · paused" : ""}</T>
        </View>
        <T style={[styles.angle, big && styles.angleBig]} testID="free-preset-label">
          {label}
        </T>
        <T style={styles.readout} testID="free-readout">
          {`az ${sign(cam.azimuth)} · el ${cam.elevation.toFixed(1)}° · ${cam.distance.toFixed(1)} m · ▲▼ ${zoom ? "zoom" : "height"}`}
        </T>
        <T style={styles.honesty} testID="free-honesty">
          {scene.honesty_label}
        </T>
        {/camera saw/i.test(scene.honesty_label) ? null : (
          <T style={styles.honestyLimit} testID="free-limit">
            View limited to what the camera saw
          </T>
        )}
      </View>

      <View style={styles.gaugeBox} testID="free-gauge">
        <T style={styles.gaugeTitle}>View limit</T>
        <View style={styles.gauge}>
          <View style={[styles.gaugeReal, at(real.azimuth, real.elevation)]} />
          <View style={[styles.gaugeDot, at(cam.azimuth, cam.elevation)]} testID="free-gauge-dot" />
        </View>
        <T style={styles.gaugeText}>
          {edges.includes("d-min") ? "closest" : edges.includes("d-max") ? "farthest" : `±${Math.max(-env.azimuth_deg[0], env.azimuth_deg[1]).toFixed(0)}° wide`}
        </T>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  card: {
    width: px(900),
    paddingHorizontal: px(28),
    paddingVertical: px(16),
    marginBottom: px(20),
    borderRadius: px(14),
    backgroundColor: color.panel,
  },
  cardTitle: { fontSize: font.h2, fontWeight: "700" },
  cardMeta: { color: color.dim, fontSize: font.small, marginTop: px(6) },

  screen: { flex: 1, backgroundColor: "#000", alignItems: "center", justifyContent: "center" },
  top: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: px(48),
    paddingVertical: px(24),
    backgroundColor: "rgba(5, 7, 10, 0.72)",
  },
  kicker: { color: color.accent, fontSize: font.body, fontWeight: "800", letterSpacing: px(3), marginRight: px(24) },
  title: { flex: 1, fontSize: font.body, fontWeight: "600" },
  synthetic: { color: color.dim, fontSize: font.small, fontWeight: "700", marginLeft: px(24) },

  // Broadcast-style lower-left bug: tier + position on top, the angle name below.
  bug: {
    position: "absolute",
    left: px(48),
    bottom: px(130),
    paddingHorizontal: px(24),
    paddingVertical: px(14),
    borderLeftWidth: px(8),
    borderLeftColor: color.accent,
    borderRadius: px(6),
    backgroundColor: color.scrim,
  },
  bugRow: { flexDirection: "row", alignItems: "center" },
  tier: { paddingHorizontal: px(14), paddingVertical: px(2), borderRadius: px(6), marginRight: px(18) },
  tierText: { color: color.onAccent, fontSize: font.small, fontWeight: "800" },
  arrow: { color: color.dim, fontSize: font.small },
  pos: { fontSize: font.small, fontWeight: "700", marginHorizontal: px(12) },
  angle: { fontSize: font.body, fontWeight: "700", marginTop: px(6) },
  angleBig: { fontSize: font.title },
  readout: { color: color.dim, fontSize: font.small, marginTop: px(6) },
  honesty: { fontSize: font.small, fontWeight: "600", marginTop: px(10) },
  honestyLimit: { fontSize: font.small, fontWeight: "600", marginTop: px(4) },

  // A clamped envelope side: a thin amber bar on that screen edge.
  edge: { position: "absolute", backgroundColor: color.accent, opacity: 0.6 },
  edgeLeft: { left: 0, top: 0, bottom: 0, width: px(10) },
  edgeRight: { right: 0, top: 0, bottom: 0, width: px(10) },
  edgeTop: { left: 0, right: 0, top: 0, height: px(10) },
  edgeBottom: { left: 0, right: 0, bottom: 0, height: px(10) },

  // The envelope: azimuth across, elevation up; ring = the real camera, dot = this view.
  gaugeBox: {
    position: "absolute",
    right: px(48),
    bottom: px(130),
    padding: px(16),
    borderRadius: px(6),
    backgroundColor: color.scrim,
    alignItems: "center",
  },
  gaugeTitle: { color: color.dim, fontSize: font.small, marginBottom: px(10) },
  gauge: {
    width: px(220),
    height: px(110),
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
    borderColor: color.dim,
  },
  gaugeDot: {
    position: "absolute",
    width: px(18),
    height: px(18),
    marginLeft: px(-9),
    marginBottom: px(-9),
    borderRadius: px(9),
    backgroundColor: color.accent,
  },
  gaugeText: { fontSize: font.small, marginTop: px(10) },

  hintBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: px(48),
    paddingBottom: px(28),
    backgroundColor: "rgba(5, 7, 10, 0.72)",
  },
});
