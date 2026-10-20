// The court line (docs/ux/redesign.md "The one bold thing"): a 6 px line across the bottom
// safe edge, Line ahead of the playhead and Scoreboard behind it, moments cut into it like
// hash marks (4 px wide; 20 px tall for scores, 12 px for other plays, a small diamond for
// bookmarks; Floor on the played side so they read without colour). Elapsed time on the
// left, remaining on the right, in Figures. While seeking, a 400 px preview frame (a crop
// of the storyboard sprite, or the moment's own thumb when the seek snapped to one) rides
// above the playhead with a Scoreboard readout (`×8`, `+2:00`) beside it.
import { Image, StyleSheet, View } from "react-native";
import { fmtDuration } from "../../../../packages/tv-core/src/display";
import type {
  Moment,
  Storyboard,
} from "../../../../packages/tv-core/src/types";
import { fmtDelta, storyboardCell } from "../playback/seek";
import { color, face, px, radius, safe, sp, type } from "../theme";
import { T } from "../ui";

export const LINE_W = px(1920) - 2 * safe.x;
const LINE_H = px(6);
const HEAD = px(24);
const PREVIEW_W = px(400);
/** Line + gap + the times row: what sits under a preview or the Moments row. */
export const TIMELINE_H = LINE_H + sp(2) + px(48);
const LABEL_H = px(48);
const PREVIEW_BOTTOM = TIMELINE_H + sp(1);

export interface SeekView {
  /** The raw seek point. */
  target: number;
  /** Hold seeks: the distance from where the seek started, and the current step (s). */
  delta: number;
  step: number;
  /** Rew/FF: ×speed in a direction; null for a hold seek. */
  scrub: { dir: 1 | -1; speed: number } | null;
  /** The moment within ±3 s the preview snapped to. */
  snapped: Moment | null;
}

interface Props {
  duration: number;
  /** The playhead (the media time, or the seek point while seeking). */
  t: number;
  moments: Moment[];
  seek: SeekView | null;
  storyboard: Storyboard | null;
}

export function Timeline({ duration, t, moments, seek, storyboard }: Props) {
  const X = (s: number) =>
    duration > 0 ? Math.max(0, Math.min(1, s / duration)) * LINE_W : 0;
  const shown = seek ? (seek.snapped?.t ?? seek.target) : t;
  const x = X(shown);
  return (
    <View
      style={styles.wrap}
      pointerEvents="none"
      testID="timeline"
      dataSet={{ t: shown.toFixed(1), duration: Math.round(duration) }}
    >
      {seek ? (
        <Preview seek={seek} at={shown} x={x} storyboard={storyboard} />
      ) : null}
      <View style={styles.times}>
        <T style={styles.fig} testID="time-elapsed">
          {fmtDuration(shown)}
        </T>
        <T style={[styles.fig, styles.dim]} testID="time-remaining">
          −{fmtDuration(Math.max(0, duration - shown))}
        </T>
      </View>
      <View style={styles.line}>
        <View style={[styles.played, { width: x }]} />
        {moments.map((m) => {
          const played = m.t <= shown;
          const ink = played ? color.floor : color.scoreboard;
          const h = m.kind === "score" ? px(20) : px(12);
          return (
            <View
              key={m.id}
              testID="moment-notch"
              dataSet={{
                kind: m.kind,
                t: m.t,
                played: played ? "true" : "false",
              }}
              style={
                m.kind === "bookmark"
                  ? [
                      styles.diamond,
                      { left: X(m.t) - px(6), backgroundColor: ink },
                    ]
                  : [
                      styles.notch,
                      {
                        left: X(m.t) - px(2),
                        height: h,
                        top: (LINE_H - h) / 2,
                        backgroundColor: ink,
                      },
                    ]
              }
            />
          );
        })}
        <View
          testID="timeline-playhead"
          style={[styles.head, { left: x - HEAD / 2 }]}
        />
      </View>
    </View>
  );
}

function Preview({
  seek,
  at,
  x,
  storyboard,
}: {
  seek: SeekView;
  at: number;
  x: number;
  storyboard: Storyboard | null;
}) {
  const h = storyboard
    ? (PREVIEW_W * storyboard.height) / storyboard.width
    : (PREVIEW_W * 9) / 16;
  const left = Math.max(0, Math.min(LINE_W - PREVIEW_W, x - PREVIEW_W / 2));
  const thumb = seek.snapped?.thumb_url;
  const cell = !thumb && storyboard ? storyboardCell(storyboard, at) : null;
  const k = storyboard ? PREVIEW_W / storyboard.width : 1;
  // The readout sits left of the frame, or right of it when the frame hugs the left edge.
  const readoutSide =
    left >= px(220)
      ? { right: LINE_W - left + sp(3) }
      : { left: left + PREVIEW_W + sp(3) };
  return (
    <>
      <View
        style={[styles.preview, { left }]}
        testID="seek-preview"
        dataSet={{
          t: at.toFixed(1),
          step: seek.scrub ? "" : seek.step,
          speed: seek.scrub?.speed ?? "",
          snapped: seek.snapped?.id ?? "",
          sheet: cell?.sheet ?? "",
          x: cell?.x ?? "",
          y: cell?.y ?? "",
        }}
      >
        <View style={[styles.frame, { height: h }]}>
          {thumb ? (
            <Image
              source={{ uri: thumb }}
              style={StyleSheet.absoluteFill}
              resizeMode="cover"
            />
          ) : cell ? (
            <Image
              testID="seek-sprite"
              source={{ uri: cell.sheet }}
              resizeMode="stretch"
              style={{
                position: "absolute",
                left: -cell.x * k,
                top: -cell.y * k,
                width: cell.sheetW * k,
                height: cell.sheetH * k,
              }}
            />
          ) : null}
          <View style={styles.timeChip}>
            <T style={styles.fig}>{fmtDuration(at)}</T>
          </View>
        </View>
        <View
          style={[
            styles.caption,
            { width: Math.min(PREVIEW_W + px(240), LINE_W - left) },
          ]}
        >
          {seek.snapped ? (
            <T
              style={[type.body, styles.label]}
              numberOfLines={1}
              testID="seek-label"
            >
              {seek.snapped.label}
            </T>
          ) : null}
        </View>
      </View>
      <View
        style={[
          styles.readout,
          readoutSide,
          { bottom: PREVIEW_BOTTOM + LABEL_H + h / 2 - px(44) },
        ]}
        testID="seek-readout"
        dataSet={{ dir: seek.scrub?.dir ?? "" }}
      >
        {seek.scrub ? <Arrows dir={seek.scrub.dir} /> : null}
        <T style={styles.readoutText}>
          {seek.scrub ? `×${seek.scrub.speed}` : fmtDelta(seek.delta)}
        </T>
      </View>
    </>
  );
}

/** ◀◀ / ▶▶ from borders (Barlow has no arrow glyphs). */
function Arrows({ dir }: { dir: 1 | -1 }) {
  const tri = dir > 0 ? styles.triR : styles.triL;
  return (
    <View style={styles.arrows}>
      <View style={tri} />
      <View style={tri} />
    </View>
  );
}

const TRI = {
  width: 0,
  height: 0,
  borderTopWidth: px(16),
  borderBottomWidth: px(16),
  borderTopColor: "transparent",
  borderBottomColor: "transparent",
} as const;

const styles = StyleSheet.create({
  wrap: {
    position: "absolute",
    left: safe.x,
    width: LINE_W,
    bottom: safe.y,
  },
  times: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: sp(2),
    height: px(48),
    alignItems: "flex-end",
  },
  fig: { ...type.figures, fontSize: px(36), lineHeight: px(44) },
  dim: { color: color.bleacher },
  line: {
    height: LINE_H,
    borderRadius: LINE_H / 2,
    backgroundColor: color.line,
  },
  played: {
    position: "absolute",
    left: 0,
    top: 0,
    bottom: 0,
    borderRadius: LINE_H / 2,
    backgroundColor: color.scoreboard,
  },
  notch: { position: "absolute", width: px(4) },
  diamond: {
    position: "absolute",
    top: (LINE_H - px(12)) / 2,
    width: px(12),
    height: px(12),
    transform: [{ rotate: "45deg" }],
  },
  head: {
    position: "absolute",
    top: (LINE_H - HEAD) / 2,
    width: HEAD,
    height: HEAD,
    borderRadius: HEAD / 2,
    backgroundColor: color.scoreboard,
    borderWidth: px(3),
    borderColor: color.floor,
  },
  preview: {
    position: "absolute",
    bottom: PREVIEW_BOTTOM,
    width: PREVIEW_W,
  },
  frame: {
    width: PREVIEW_W,
    borderRadius: radius.card,
    overflow: "hidden",
    backgroundColor: color.bench,
    boxShadow: "0px 16px 40px rgba(0, 0, 0, 0.55)",
  },
  timeChip: {
    position: "absolute",
    left: sp(1),
    bottom: sp(1),
    paddingHorizontal: sp(1.5),
    borderRadius: px(8),
    backgroundColor: "rgba(18, 26, 35, 0.84)",
  },
  // Wider than the frame so a long label still fits on one line.
  caption: {
    height: LABEL_H,
    justifyContent: "center",
  },
  label: { color: color.chalk },
  readout: {
    position: "absolute",
    flexDirection: "row",
    alignItems: "center",
  },
  readoutText: {
    fontFamily: face.figures,
    fontVariant: ["tabular-nums"],
    fontSize: px(88),
    lineHeight: px(88),
    color: color.scoreboard,
    // rides bare video: a soft shadow keeps it readable over bright frames
    textShadowColor: "rgba(0,0,0,0.6)",
    textShadowOffset: { width: 0, height: px(2) },
    textShadowRadius: px(12),
  },
  arrows: { flexDirection: "row", marginRight: sp(1.5) },
  triR: { ...TRI, borderLeftWidth: px(22), borderLeftColor: color.scoreboard },
  triL: {
    ...TRI,
    borderRightWidth: px(22),
    borderRightColor: color.scoreboard,
  },
});
