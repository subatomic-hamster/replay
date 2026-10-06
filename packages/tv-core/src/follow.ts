// D-6 / D-20 follow-cam math, shared by apps/web (CSS transform) and apps/tv (RN
// transform). All rects are [x, y, w, h] normalized to the wide frame.
import type { CropPath, TrackPlayer } from "./types";

type Rect = [number, number, number, number];

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

/** The crop rect the follow-cam is using at time `t`, clamped past the last rect (E-12). */
export function cropRectAt(crop: CropPath, t: number): Rect {
  const i = clamp(Math.round((t - crop.t0) * crop.rate_hz), 0, crop.rects.length - 1);
  return crop.rects[i];
}

/** Frame-normalized box → viewport-normalized box under a crop rect. */
export function mapBB(bb: TrackPlayer["bb"], rect: Rect | null): TrackPlayer["bb"] {
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
