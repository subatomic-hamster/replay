// W4 — the amber frame that stays locked on the followed player, in wide playback and in
// follow mode alike, from the moment Enter picks them until another player is picked.
//
// It positions itself in VIEWPORT space, not frame space: in follow mode the <video> is
// crop-transformed (D-6/D-20), so a normalized track box has to go through the same crop
// rect the transform used or it lands on the wrong pixels. Driven by its own rAF off
// `clock.ts` (§4.8 overlay sync rule) rather than React state, so it tracks at the video's
// frame rate without re-rendering the Watch screen 30 times a second.
import { useEffect, useRef } from "react";
import type { CropPath } from "../api/types";
import type { TracksCache } from "../data/tracksCache";
import type { Clock } from "../playback/clock";
import { cropRectAt, mapBB } from "../../../../packages/tv-core/src/follow";

export { cropRectAt, mapBB };

interface Props {
  pid: string;
  label: string;
  tracks: TracksCache | null;
  clock: Clock | null;
  /** Non-null only while the follow-cam transform is applied. */
  crop: CropPath | null;
}

const pct = (v: number) => `${(v * 100).toFixed(3)}%`;

export function FollowFrame({ pid, label, tracks, clock, crop }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !tracks) return;
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const t = clock?.now() ?? 0;
      const bb = tracks.playersAt(t).find((p) => p.id === pid)?.bb;
      // Occluded or off court: fade out (CSS), come back when the box does.
      if (!bb) {
        el.dataset.visible = "false";
        return;
      }
      const [x, y, w, h] = mapBB(bb, crop ? cropRectAt(crop, t) : null);
      el.style.left = pct(x);
      el.style.top = pct(y);
      el.style.width = pct(w);
      el.style.height = pct(h);
      el.dataset.visible = "true";
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [pid, tracks, clock, crop]);

  return (
    <div
      className="follow-frame"
      data-testid="follow-frame"
      data-pid={pid}
      data-visible="false"
      ref={ref}
      aria-hidden
    >
      <span className="follow-frame-label">{label}</span>
    </div>
  );
}
