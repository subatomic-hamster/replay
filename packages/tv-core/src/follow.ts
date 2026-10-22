// D-6 / D-20 follow-cam math, shared by apps/web (CSS transform) and apps/tv (RN
// transform). All rects are [x, y, w, h] normalized to the wide frame.
import type { CropPath, TrackPlayer } from "./types";

type Rect = [number, number, number, number];

const clamp = (v: number, lo: number, hi: number) =>
  Math.min(Math.max(v, lo), hi);

/** The crop rect the follow-cam is using at time `t`, clamped past the last rect (E-12). */
export function cropRectAt(crop: CropPath, t: number): Rect {
  const i = clamp(
    Math.round((t - crop.t0) * crop.rate_hz),
    0,
    crop.rects.length - 1,
  );
  return crop.rects[i];
}

/** Frame-normalized box → viewport-normalized box under a crop rect. */
export function mapBB(
  bb: TrackPlayer["bb"],
  rect: Rect | null,
): TrackPlayer["bb"] {
  if (!rect) return bb;
  const [cx, cy, cw, ch] = rect;
  if (cw <= 0 || ch <= 0) return bb;
  return [(bb[0] - cx) / cw, (bb[1] - cy) / ch, bb[2] / cw, bb[3] / ch];
}

/**
 * Transform (origin top-left) that makes `rect` fill a W×H viewport the wide video is
 * stretched into. The axes scale independently: the crop window is 16:9 in source pixels
 * while the source may not be (a 2560x960 panorama), and the stretch into the viewport is
 * exactly what the uneven scale undoes. On a 16:9 source w === h and it is uniform.
 */
export function cropTransform(rect: Rect, W: number, H: number) {
  const [x, y, w, h] = rect;
  const sx = w > 0 ? 1 / w : 1;
  const sy = h > 0 ? 1 / h : sx;
  return { tx: -sx * x * W, ty: -sy * y * H, sx, sy };
}

// ---------------------------------------------------------------------------------------
// D-82 client follow-cam: the camera is computed on the device, every animation frame,
// from the tracks chunks the player already prefetches (no per-player crop-path download,
// so it moves the frame after Select). The same operator feel as courtcam/croppath.py: a
// critically damped spring chasing the player's box centre through a small dead zone,
// plus a short lead from the box's velocity. Real tracks fragment (a 4-minute game had 59
// track ids for ~10 people): when the followed id ends, the camera hands off to an id that
// carries on from the same spot; with none, it holds and slowly widens instead of jumping.

export interface FollowView {
  /** Crop rect now, frame-normalized; [0, 0, 1, 1] is the wide shot. */
  rect: Rect;
  /** The followed player's box at t (frame-normalized), or null in a tracking gap. */
  box: Rect | null;
  /** The track id the camera is on (changes on a hand-off). */
  id: string;
  /** Media seconds since the player's box was last seen: 0 while tracked, Infinity when
   *  never seen since a seek. Past a hand-off's reach the screen offers to pick again. */
  lost: number;
  /** Where the box was last seen (frame-normalized), to pick again near it. */
  last: Rect | null;
}

export interface FollowCam {
  /**
   * Advance to media time `t`. `dt` is wall-clock seconds since the last step: the spring
   * runs on the wall clock, so a paused picture still eases onto the player. `zoom` false
   * eases back to the wide shot while the box keeps being tracked (the ring stays on).
   */
  step(t: number, dt: number, zoom: boolean): FollowView;
  /** The last step's view (no time passes). */
  current(): FollowView;
}

// Look this far ahead along the player's motion: more than the spring's own lag behind a
// steady run (2/OMEGA ≈ 0.29 s), so a runner sits a little behind centre, facing space.
const LEAD_S = 0.5;
const VEL_WINDOW_S = 0.3; // velocity from the box now and this long ago
const MAX_LEAD = 0.25; // of the crop window, so a sprint cannot throw the frame
const DEAD = 0.04; // of the window: box jitter inside this band never moves the camera
const OMEGA = 7; // spring stiffness, rad/s (≈0.6 s to settle), courtcam's basketball value
const OMEGA_ZOOM = 6; // zoom spring: the first zoom-in lands in well under a second ...
const BOX_H_TAU_S = 0.5; // ... while the box height it reads is smoothed (heights jitter, a crouch is not a cut)
const ZOOM_K = 2.5; // window height = this × the box height ...
const MIN_H = 0.4; // ... but never tighter (a 1080p source would be upscaled > 2.5×)
const MAX_H = 0.75;
// Near a frame edge the window cannot centre the player without leaving the picture: it
// zooms in instead, up to this height (≈3.1× on 1080p), so a player at x 0.86 sits
// 0.02 off centre instead of 0.06. Off centre by up to EDGE_SLACK of the window width
// is fine as it is: the zoom does not twitch for a player just short of the edge.
const MIN_H_EDGE = 0.32;
const EDGE_SLACK = 0.06;
const WIDEN_AFTER_S = 0.6; // a gap longer than this starts widening ...
const WIDEN_S = 2.5; // ... to the wide shot over this long
/** No hand-off after a gap this long: the player is lost (the screen offers a re-pick). */
export const HANDOFF_MAX_GAP_S = 1.5;
const CLEAR_MARGIN = 0.5; // box heights the hand-off box must be nearer than any other
const BORN_SCAN = 12; // track frames (10 Hz) to look back for a duplicate id's birth
const SEEK_S = 1; // a media-time jump bigger than this is a seek: no easing across it

const centre = (b: Rect): [number, number] => [
  b[0] + b[2] / 2,
  b[1] + b[3] / 2,
];

/** Exact critically damped spring step (stable for any dt). Returns [pos, vel]. */
export function springStep(
  pos: number,
  vel: number,
  goal: number,
  dt: number,
  omega = OMEGA,
): [number, number] {
  const x = pos - goal;
  const k = vel + omega * x;
  const e = Math.exp(-omega * dt);
  return [goal + (x + k * dt) * e, (vel - omega * k * dt) * e];
}

/**
 * @param aspect the source's width / height (the crop window is 16:9 in source pixels,
 *   so on a 2560x960 panorama it is narrower than it is tall in normalized units)
 * @param teamOf a hand-off never crosses to the other team when both teams are known
 */
export function createFollowCam(
  tracks: { playersAt(t: number): TrackPlayer[] },
  pid: string,
  aspect = 16 / 9,
  teamOf: (id: string) => number | undefined = () => undefined,
  /** The ids are people (game.tracks.people, D-89): another id is someone else, never a
   *  new track of ours, so no hand-off (it would move the follow to them in a crossing). */
  people = false,
): FollowCam {
  const wPerH = 16 / 9 / aspect;
  const hCap = Math.min(1, 1 / wPerH);
  // camera: centre, size and their velocities; it starts on the wide shot
  const cam = { x: 0.5, y: 0.5, w: 1, h: 1, vx: 0, vy: 0, vw: 0, vh: 0 };
  let id = pid;
  let lastT: number | null = null;
  let lastBox: Rect | null = null;
  let lastSeen = -Infinity;
  // when the camera started looking (first step, or a seek): not yet seen is not lost,
  // and "lost" counts from here until the first box
  let looking = 0;
  let gapPrev: TrackPlayer[] | null = null; // who was on court when the gap began
  let bornCache: Map<string, boolean> | null = null; // bornOnUs, per gap
  let held: [number, number] | null = null; // dead-zone anchor
  let boxH: number | null = null; // the box height, smoothed (it sets the zoom)
  let seenH = 1; // the window height while the box was last seen (a gap widens from it)
  let view: FollowView = {
    rect: [0, 0, 1, 1],
    box: null,
    id,
    lost: 0,
    last: null,
  };

  const boxOf = (ps: TrackPlayer[], who: string) =>
    (ps.find((p) => p.id === who)?.bb as Rect | undefined) ?? null;
  const dist = (a: [number, number], b: [number, number]) =>
    Math.hypot((a[0] - b[0]) * aspect, a[1] - b[1]);

  /**
   * Was `other` born on top of our player shortly before they vanished (the tracker
   * starting a second id on the same person, which then outlives ours)? Scans back in
   * track frames from `lastSeen`.
   */
  function bornOnUs(other: string, lh: number): boolean {
    for (let k = 1; k <= BORN_SCAN; k++) {
      const tk = lastSeen - k * 0.1;
      const ps = tracks.playersAt(tk);
      if (boxOf(ps, other)) continue;
      const after = tracks.playersAt(tk + 0.1);
      const a = boxOf(after, other);
      const us = boxOf(after, id);
      return !!a && !!us && dist(centre(a), centre(us)) <= lh * 0.6;
    }
    return false; // on court all along: another player
  }

  /**
   * An id that carries on from where ours vanished, only when that is unambiguous: born
   * during the gap, or born on top of us just before it, and nobody else near the spot.
   * Real tracks bunch (a volleyball huddle, a screen), and there the nearest new box is
   * as often a teammate: then it holds and widens rather than guess (D-82).
   */
  function handoff(ps: TrackPlayer[], t: number): TrackPlayer | null {
    if (!lastBox || people) return null;
    const gap = t - lastSeen;
    if (gap < 0 || gap > HANDOFF_MAX_GAP_S) return null;
    gapPrev ??= tracks.playersAt(lastSeen);
    const at = centre(lastBox);
    const lh = lastBox[3];
    const reach = lh * Math.min(1 + gap * 1.5, 2.5);
    const team = teamOf(pid);
    const near = ps
      .filter((p) => p.id !== id)
      .map((p) => ({ p, d: dist(centre(p.bb as Rect), at) }))
      .sort((a, b) => a.d - b.d);
    // the nearest box, clearly nearer than any other (else a crowd: no guess)
    if (!near.length || near[0].d > reach) return null;
    if (near.length > 1 && near[1].d < near[0].d + lh * CLEAR_MARGIN)
      return null;
    const p = near[0].p;
    const pt = teamOf(p.id);
    if (team !== undefined && pt !== undefined && pt !== team) return null;
    if (boxOf(gapPrev, p.id)) {
      bornCache ??= new Map();
      let ok = bornCache.get(p.id);
      if (ok === undefined) bornCache.set(p.id, (ok = bornOnUs(p.id, lh)));
      if (!ok) return null;
    }
    return p;
  }

  function step(t: number, dt: number, zoom: boolean): FollowView {
    const seek = lastT !== null && Math.abs(t - lastT) > SEEK_S;
    const s = Math.min(Math.max(dt, 0), 0.1);
    if (lastT === null || seek) looking = t;
    lastT = t;
    if (seek) {
      // The chain before a seek says nothing about the new time: only our id can resume.
      lastBox = null;
      lastSeen = -Infinity;
      gapPrev = null;
      bornCache = null;
      held = null;
      boxH = null;
    }
    const ps = tracks.playersAt(t);
    let box = boxOf(ps, id);
    if (!box) {
      const next = handoff(ps, t);
      if (next) {
        id = next.id;
        box = next.bb as Rect;
      }
    }

    // Goal: the box (plus lead) at a zoom from its height; in a gap the last spot, widening.
    let gx = cam.x;
    let gy = cam.y;
    let gh = cam.h;
    if (box) {
      lastBox = box;
      lastSeen = t;
      gapPrev = null;
      bornCache = null;
      const [cx, cy] = centre(box);
      const then = boxOf(tracks.playersAt(t - VEL_WINDOW_S), id);
      const [px, py] = then ? centre(then) : [cx, cy];
      boxH =
        boxH === null
          ? box[3]
          : boxH + (box[3] - boxH) * Math.min(1, s / BOX_H_TAU_S);
      gh = Math.min(Math.max(boxH * ZOOM_K, MIN_H), MAX_H, hCap);
      const gw = gh * wPerH;
      const lead = (v: number, size: number) =>
        Math.min(Math.max(v * LEAD_S, -MAX_LEAD * size), MAX_LEAD * size);
      const tx = cx + lead((cx - px) / VEL_WINDOW_S, gw);
      const ty = cy + lead((cy - py) / VEL_WINDOW_S, gh);
      if (!held) held = [tx, ty];
      const band = (d: number, size: number) =>
        Math.sign(d) * Math.max(Math.abs(d) - DEAD * size, 0);
      held = [
        held[0] + band(tx - held[0], gw),
        held[1] + band(ty - held[1], gh),
      ];
      [gx, gy] = held;
      // near a side edge, the tightest window that still centres them, down to
      // MIN_H_EDGE. Sides only: players stand low in the frame most of the time, and
      // zooming for that would change the framing all game.
      const fits = Math.min(gx, 1 - gx) / (0.5 - EDGE_SLACK) / wPerH;
      if (fits < gh) gh = Math.max(fits, Math.min(MIN_H_EDGE, gh));
      seenH = gh;
    } else if (lastBox) {
      const gap = t - lastSeen;
      const k = Math.min(Math.max((gap - WIDEN_AFTER_S) / WIDEN_S, 0), 1);
      gh = seenH + (hCap - seenH) * k;
      [gx, gy] = held ?? centre(lastBox);
    } else {
      gh = hCap; // never seen (a seek to where this id is not): the whole court
    }

    let gw = gh * wPerH;
    if (!zoom) {
      gx = 0.5;
      gy = 0.5;
      gw = 1;
      gh = 1;
    }
    // aim inside the frame, so the spring never winds up past an edge
    gx = Math.min(Math.max(gx, gw / 2), 1 - gw / 2);
    gy = Math.min(Math.max(gy, gh / 2), 1 - gh / 2);
    // A seek jumps straight there (easing across it would sweep the court).
    if (seek && zoom && box)
      Object.assign(cam, {
        x: gx,
        y: gy,
        w: gw,
        h: gh,
        vx: 0,
        vy: 0,
        vw: 0,
        vh: 0,
      });
    [cam.w, cam.vw] = springStep(cam.w, cam.vw, gw, s, OMEGA_ZOOM);
    [cam.h, cam.vh] = springStep(cam.h, cam.vh, gh, s, OMEGA_ZOOM);
    [cam.x, cam.vx] = springStep(cam.x, cam.vx, gx, s);
    [cam.y, cam.vy] = springStep(cam.y, cam.vy, gy, s);
    if (!zoom && 1 - cam.w < 1e-3 && 1 - cam.h < 1e-3) {
      Object.assign(cam, {
        x: 0.5,
        y: 0.5,
        w: 1,
        h: 1,
        vx: 0,
        vy: 0,
        vw: 0,
        vh: 0,
      });
    }
    const w = Math.min(Math.max(cam.w, 0.05), 1);
    const h = Math.min(Math.max(cam.h, 0.05), 1);
    // keep the window inside the frame
    const x = Math.min(Math.max(cam.x - w / 2, 0), 1 - w);
    const y = Math.min(Math.max(cam.y - h / 2, 0), 1 - h);
    view = {
      rect: [x, y, w, h],
      box,
      id,
      lost: box ? 0 : t - Math.max(lastSeen, looking),
      last: lastBox,
    };
    return view;
  }

  return { step, current: () => view };
}
