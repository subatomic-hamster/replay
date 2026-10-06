// Free view (2.5D) camera: the camera state of docs/scene-format.md ("Camera envelope and
// presets"), the envelope clamp, presets, D-pad steps and the pose/projection math.
// Pure TS shared by both renderers (FreeView.web.tsx = WebGL, FreeView.native.tsx = the
// Fabric GL view) and the Replay screen, which owns the state: D-pad handling lives in JS
// on both platforms. `camera` passed to FreeView is the TARGET; each renderer eases its
// displayed camera towards it with `easeCamera` (same constant on both), so a native view
// gets one prop update per key press instead of one per frame.
import type { SceneLayout, Vec3 } from "../../../../packages/tv-core/src/types";

/** Degrees and metres. azimuth is the offset from envelope.azimuth0_deg (0 = the real
 *  camera's azimuth); elevation is absolute. roll only moves with a preset. */
export interface CameraState {
  azimuth: number;
  elevation: number;
  distance: number;
  roll: number;
  fovY: number;
}

/** What both FreeView implementations accept (FreeView.web.tsx / FreeView.native.tsx). */
export interface FreeViewProps {
  /** GET /games/{id}/scenes/{play_id}: plates[].url and atlas.url are absolute. */
  layout: SceneLayout;
  /** Target camera; the view eases towards it (easeCamera). */
  camera: CameraState;
  paused: boolean;
  /** Media time to start the atlas at (the angle's time when entering free view). */
  startTimeSec?: number;
  /** Atlas media time: a few times per second while playing, on pause, and once while
   *  unmounting (the Replay screen resumes the video angle at that time). */
  onTime?: (sec: number) => void;
  onReady?: () => void;
  onError?: (msg: string) => void;
}

export type CameraAction = "left" | "right" | "up" | "down" | "zoom-in" | "zoom-out" | "reset";

/** One press: 2.5° (contract), 5 % of the real distance for zoom. */
export const STEP_DEG = 2.5;
export const STEP_DIST_FRAC = 0.05;
/** Held: at most 12 steps/s (30°/s). Presses of the same action closer together than
 *  MIN_STEP_MS are dropped, so a keyboard's ~30 Hz auto-repeat becomes ~25°/s and the
 *  Fire TV's 120 ms JS repeat (platform/keys.native.ts) ~21°/s; the eased display glides. */
export const HOLD_STEPS_PER_S = 12;
export const MIN_STEP_MS = 1000 / HOLD_STEPS_PER_S;
/** Time constant of the displayed camera's exponential approach to the target. */
export const EASE_MS = 140;
/** A field within this of its limit counts as clamped (edge indicator). */
const EDGE_EPS = 1e-3;
const NEAR_M = 0.3;

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

export function clampToEnvelope(s: CameraState, layout: SceneLayout): CameraState {
  const e = layout.envelope;
  return {
    ...s,
    azimuth: clamp(s.azimuth, e.azimuth_deg[0], e.azimuth_deg[1]),
    elevation: clamp(s.elevation, e.elevation_deg[0], e.elevation_deg[1]),
    distance: clamp(s.distance, e.distance_m[0], e.distance_m[1]),
  };
}

export type Edge = "az-min" | "az-max" | "el-min" | "el-max" | "d-min" | "d-max";

/** The envelope limits `s` sits on (for the edge indicator). */
export function envelopeEdges(s: CameraState, layout: SceneLayout): Edge[] {
  const e = layout.envelope;
  const out: Edge[] = [];
  const at = (v: number, lim: number) => Math.abs(v - lim) <= EDGE_EPS;
  if (at(s.azimuth, e.azimuth_deg[0])) out.push("az-min");
  if (at(s.azimuth, e.azimuth_deg[1])) out.push("az-max");
  if (at(s.elevation, e.elevation_deg[0])) out.push("el-min");
  if (at(s.elevation, e.elevation_deg[1])) out.push("el-max");
  if (at(s.distance, e.distance_m[0])) out.push("d-min");
  if (at(s.distance, e.distance_m[1])) out.push("d-max");
  return out;
}

/** A preset's state, clamped; unknown ids give `real` (then the first preset). */
export function presetState(id: string, layout: SceneLayout): CameraState {
  const p =
    layout.presets.find((q) => q.id === id) ??
    layout.presets.find((q) => q.id === "real") ??
    layout.presets[0];
  const e = layout.envelope;
  const s = p
    ? { azimuth: p.azimuth_deg, elevation: p.elevation_deg, distance: p.distance_m, roll: p.roll_deg, fovY: p.fov_y_deg }
    : { azimuth: 0, elevation: e.elevation_deg[0], distance: e.distance_m[1], roll: 0, fovY: e.fov_y_deg };
  return clampToEnvelope(s, layout);
}

/** One D-pad step. `dtMs`: time since the previous accepted press of the same action
 *  (Infinity for the first); returns `s` itself when the press is dropped (see
 *  MIN_STEP_MS). Left/Right = azimuth −/+, Up/Down = elevation +/−, zoom = distance ∓. */
export function stepCamera(s: CameraState, action: CameraAction, dtMs: number, layout: SceneLayout): CameraState {
  if (action === "reset") return presetState("real", layout);
  if (dtMs < MIN_STEP_MS) return s;
  const dist = STEP_DIST_FRAC * presetState("real", layout).distance;
  const deg = STEP_DEG;
  const next = { ...s };
  if (action === "left") next.azimuth -= deg;
  else if (action === "right") next.azimuth += deg;
  else if (action === "up") next.elevation += deg;
  else if (action === "down") next.elevation -= deg;
  else if (action === "zoom-in") next.distance -= dist;
  else if (action === "zoom-out") next.distance += dist;
  return clampToEnvelope(next, layout);
}

/** Displayed camera after `dtMs` of easing towards `target` (every field on the same
 *  exponential, so the path is the straight line in state space). Snaps when close. */
export function easeCamera(cur: CameraState, target: CameraState, dtMs: number): CameraState {
  const k = 1 - Math.exp(-Math.max(0, dtMs) / EASE_MS);
  const out = { ...cur };
  let far = false;
  for (const key of ["azimuth", "elevation", "distance", "roll", "fovY"] as const) {
    const d = target[key] - cur[key];
    if (Math.abs(d) > 1e-3) far = true;
    out[key] = cur[key] + d * k;
  }
  return far ? out : { ...target };
}

export const sameCamera = (a: CameraState, b: CameraState) =>
  a.azimuth === b.azimuth &&
  a.elevation === b.elevation &&
  a.distance === b.distance &&
  a.roll === b.roll &&
  a.fovY === b.fovY;

/** Eye position and rotation (rows: right, down, forward; OpenCV x_cam = R·(X − eye)). */
export function cameraPose(s: CameraState, layout: SceneLayout): { eye: Vec3; R: [Vec3, Vec3, Vec3] } {
  const e = layout.envelope;
  const rad = Math.PI / 180;
  const az = (e.azimuth0_deg + s.azimuth) * rad;
  const el = s.elevation * rad;
  const tg = e.target_m;
  const eye: Vec3 = [
    tg[0] + s.distance * Math.cos(el) * Math.cos(az),
    tg[1] + s.distance * Math.cos(el) * Math.sin(az),
    tg[2] + s.distance * Math.sin(el),
  ];
  const fwd = norm([tg[0] - eye[0], tg[1] - eye[1], tg[2] - eye[2]]);
  const right = norm(cross(fwd, [0, 0, 1]));
  const down = cross(fwd, right);
  const c = Math.cos(s.roll * rad);
  const n = Math.sin(s.roll * rad);
  // R = Rz(roll) · R0
  const R: [Vec3, Vec3, Vec3] = [
    [c * right[0] - n * down[0], c * right[1] - n * down[1], c * right[2] - n * down[2]],
    [n * right[0] + c * down[0], n * right[1] + c * down[1], n * right[2] + c * down[2]],
    fwd,
  ];
  return { eye, R };
}

/** World → clip matrix (column-major, for uniformMatrix4fv) of the pinhole camera with
 *  principal point (W/2, H/2) in OpenCV pixels (pixel centres on integers, as K and the
 *  reference renderer use; GL's are on half-integers, hence the half-pixel terms), y
 *  flipped (OpenCV y is down), and z mapped so [near, far] → [−1, 1] (GL clips at the near
 *  plane). Also returns the camera-space depth function for painter's order. */
export function viewProjection(s: CameraState, layout: SceneLayout, width: number, height: number, far = 500) {
  const { eye, R } = cameraPose(s, layout);
  const f = height / 2 / Math.tan(((s.fovY * Math.PI) / 180) / 2);
  const t = R.map((r) => -(r[0] * eye[0] + r[1] * eye[1] + r[2] * eye[2])) as Vec3;
  const sx = (2 * f) / width;
  const sy = (-2 * f) / height;
  const a = (far + NEAR_M) / (far - NEAR_M);
  const b = (-2 * far * NEAR_M) / (far - NEAR_M);
  // rows of the 4x4 (row-major), then transposed into column-major below
  const hx = 1 / width;
  const hy = -1 / height;
  const rows = [
    [sx * R[0][0] + hx * R[2][0], sx * R[0][1] + hx * R[2][1], sx * R[0][2] + hx * R[2][2], sx * t[0] + hx * t[2]],
    [sy * R[1][0] + hy * R[2][0], sy * R[1][1] + hy * R[2][1], sy * R[1][2] + hy * R[2][2], sy * t[1] + hy * t[2]],
    [a * R[2][0], a * R[2][1], a * R[2][2], a * t[2] + b],
    [R[2][0], R[2][1], R[2][2], t[2]],
  ];
  const m = new Float32Array(16);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) m[c * 4 + r] = rows[r][c];
  const depth = (p: Vec3) => R[2][0] * p[0] + R[2][1] * p[1] + R[2][2] * p[2] + t[2];
  return { matrix: m, eye, R, t, f, depth };
}

/** Horizontal unit axis of a billboard at `foot` facing camera position `c` (its right). */
export function billboardAxis(c: Vec3, foot: Vec3): Vec3 {
  const d = [foot[0] - c[0], foot[1] - c[1]];
  const l = Math.hypot(d[0], d[1]) || 1;
  return [d[1] / l, -d[0] / l, 0];
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

function norm(v: Vec3): Vec3 {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
}
