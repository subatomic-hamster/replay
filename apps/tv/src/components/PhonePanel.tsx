// The player's "On your phone" layer (docs/ux/redesign.md principle 4 and "Do more"):
// typing and fine edits go to the phone. One QR per job, the same code card as Add game,
// to the apps/web page for it: Clip and Search open the companion paired to this TV
// (its "Clip that" cuts the play on screen, "Play on TV" jumps here), Review and Tag open
// this game's review page and its player at this moment. Left/Right pick the job, Back
// closes. Replaces the old Clips, Search, Advice and Pair screens as the way in.
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import type { Session } from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { WEB_BASE } from "../platform/config";
import { storeSession, storedSession } from "../session";
import { color, px, safe, sp, type } from "../theme";
import { Chip, Hint, SlideIn, T } from "../ui";
import { QrCode } from "./QrCode";

export type PhoneJob = "clip" | "tag" | "review" | "search";

const JOBS: { id: PhoneJob; label: string; title: string; body: string }[] = [
  {
    id: "clip",
    label: "Clip",
    title: "Clip this play",
    body: "Your phone pairs with this TV. Tap Clip that to save the play on screen, then trim and share it there.",
  },
  {
    id: "tag",
    label: "Tag players",
    title: "Name the players",
    body: "Opens this game at this moment, so you can put a name to each player.",
  },
  {
    id: "review",
    label: "Review",
    title: "Check the calls",
    body: "Answer the plays Replay was not sure about. The stats update here.",
  },
  {
    id: "search",
    label: "Search",
    title: "Find a play",
    body: "Type or say what you want to see. Play on TV jumps here.",
  },
];

/** The apps/web page for a job, or null while the pairing code is still coming. */
export function phoneUrl(
  web: string,
  job: PhoneJob,
  gameId: string,
  t: number,
  session: Session | null,
): string | null {
  const base = web.replace(/\/+$/, "");
  if (job === "review") return `${base}/tv/${gameId}/review`;
  if (job === "tag")
    return `${base}/tv/${gameId}?mode=select&t=${Math.floor(t)}`;
  return session ? `${base}/companion/${session.code}` : null;
}

export function PhonePanel({
  gameId,
  t,
  onClose,
  onPlayPause,
}: {
  gameId: string;
  /** game time when the layer opened */
  t: number;
  onClose: () => void;
  onPlayPause: () => void;
}) {
  const [k, setK] = useState(0);
  const [session, setSession] = useState<Session | null>(storedSession);
  const job = JOBS[k];
  const needsCode = job.id === "clip" || job.id === "search";

  // The companion pairs by the session code; reuse the one this TV already has.
  useEffect(() => {
    if (!needsCode || session) return;
    let on = true;
    api.createSession().then(
      (s) => {
        storeSession(s);
        if (on) setSession(s);
      },
      () => {},
    );
    return () => {
      on = false;
    };
  }, [needsCode, session]);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back" || a === "up" || a === "down") onClose();
      else if (a === "playpause") onPlayPause();
      else if (a === "left") setK(Math.max(0, k - 1));
      else if (a === "right") setK(Math.min(JOBS.length - 1, k + 1));
    },
    [k, onClose, onPlayPause],
  );
  useDpad(onAction);

  const url = WEB_BASE ? phoneUrl(WEB_BASE, job.id, gameId, t, session) : null;
  return (
    <View style={styles.scrim} pointerEvents="none">
      <SlideIn
        from="above"
        style={styles.layer}
        testID="phone-panel"
        dataSet={{ job: job.id }}
      >
        <T style={[type.meta, styles.dim]}>On your phone</T>
        <View style={styles.chips}>
          {JOBS.map((j, i) => (
            <Chip
              key={j.id}
              label={j.label}
              focused={i === k}
              testID={`phone-${j.id}`}
            />
          ))}
        </View>
        <View style={styles.body}>
          <View style={styles.qrBox}>
            {url ? (
              <View testID="phone-qr" dataSet={{ url }}>
                <QrCode text={url} size={440} />
              </View>
            ) : !WEB_BASE ? (
              <T style={[type.body, styles.dim]} testID="phone-no-qr">
                This TV doesn't know the address of Replay's phone pages yet.
              </T>
            ) : (
              <T style={[type.body, styles.dim]}>Getting a code…</T>
            )}
          </View>
          <View style={styles.side}>
            <T style={type.title}>{job.title}</T>
            <T style={[type.body, styles.dim, styles.gap]}>{job.body}</T>
            <T style={[type.body, styles.gap]}>
              Scan with your phone's camera.
            </T>
            {url ? (
              <T style={[type.figures, styles.url]} testID="phone-url">
                {url.replace(/^https?:\/\//, "")}
              </T>
            ) : null}
            <Hint k="Back">The game</Hint>
          </View>
        </View>
      </SlideIn>
    </View>
  );
}

const styles = StyleSheet.create({
  scrim: {
    ...StyleSheet.absoluteFill,
    backgroundColor: "rgba(18, 26, 35, 0.92)",
  },
  layer: {
    position: "absolute",
    left: safe.x,
    right: safe.x,
    top: safe.y,
  },
  dim: { color: color.bleacher },
  chips: { flexDirection: "row", marginTop: sp(2) },
  body: { flexDirection: "row", alignItems: "center", marginTop: sp(4) },
  qrBox: { width: px(440), minHeight: px(440), justifyContent: "center" },
  side: { flex: 1, marginLeft: sp(8) },
  gap: { marginTop: sp(2) },
  url: { color: color.chalk, marginTop: sp(3) },
});
