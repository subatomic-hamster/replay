// The player's "On your phone" layer (docs/ux/redesign.md principle 4 and "Do more"):
// typing and fine edits go to the phone. One QR per job, the same code card as Add game,
// to apps/web's phone page for this game, job and moment. The API mints the link
// (POST /games/{id}/phone-link) with its own short-lived token in the `#k=` fragment,
// which only the QR carries. Left/Right pick the job, Back closes.
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import type {
  PhoneJob,
  PhoneLink,
} from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { useDpad, type DpadAction } from "../input";
import { color, px, safe, sp, type } from "../theme";
import { Chip, Hint, SlideIn, Spinner, T } from "../ui";
import { QrCode } from "./QrCode";

const JOBS: { id: PhoneJob; label: string; title: string; body: string }[] = [
  {
    id: "clip",
    label: "Clip",
    title: "Clip this play",
    body: "Opens this moment on your phone, to trim the clip and share it.",
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
    body: "Type or say what you want to see in this game.",
  },
  {
    id: "reel",
    label: "Highlight reel",
    title: "Get the highlight reel",
    body: "Your clips and the top plays in one video, wide or tall, to save and share.",
  },
];

/** Re-mint this long before the token runs out (a scan takes a moment). */
const MARGIN_MS = 60_000;
/** Minted links by game, job and second (t is fixed while the panel is open), so moving
 *  between jobs or reopening at the same moment does not mint again. A failure is not kept. */
const links = new Map<string, { p: Promise<PhoneLink>; until: number }>();

function phoneLink(gameId: string, job: PhoneJob, t: number) {
  const key = `${gameId}|${job}|${t}`;
  const hit = links.get(key);
  if (hit && hit.until > Date.now()) return hit.p;
  const p = api.phoneLink(gameId, job, t);
  links.set(key, { p, until: Infinity });
  p.then(
    (l) => {
      // epoch seconds per the contract; tolerate milliseconds
      const ms = l.expires_at < 1e11 ? l.expires_at * 1000 : l.expires_at;
      links.set(key, { p, until: ms - MARGIN_MS });
    },
    () => links.delete(key),
  );
  return p;
}

/** "https://host/p/g1?job=clip&t=12#k=…" → "host/p/g1": readable, and never the token. */
export const shortUrl = (url: string) =>
  url.replace(/^https?:\/\//, "").split(/[?#]/)[0];

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
  const job = JOBS[k];
  const sec = Math.floor(t);
  /** undefined while minting; null = no link (API error, or the server has no web base) */
  const [link, setLink] = useState<{ key: string; url: string | null }>();
  const key = `${job.id}|${sec}`;

  useEffect(() => {
    let on = true;
    phoneLink(gameId, job.id, sec).then(
      (l) => on && setLink({ key, url: l.url }),
      () => on && setLink({ key, url: null }),
    );
    return () => {
      on = false;
    };
  }, [gameId, job.id, sec, key]);

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

  const url = link?.key === key ? link.url : undefined;
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
            ) : url === null ? (
              <T style={[type.body, styles.dim]} testID="phone-no-qr">
                Phone handoff needs the web address set on the server
              </T>
            ) : (
              <View style={styles.placeholder} testID="phone-loading">
                <Spinner />
              </View>
            )}
          </View>
          <View style={styles.side}>
            <T style={type.title}>{job.title}</T>
            <T style={[type.body, styles.dim, styles.gap]}>{job.body}</T>
            {url ? (
              <>
                <T style={[type.body, styles.gap]}>
                  Scan with your phone's camera.
                </T>
                <T style={[type.figures, styles.url]} testID="phone-url">
                  {shortUrl(url)}
                </T>
              </>
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
  // the QR's footprint, quiet, while the link is minted
  placeholder: {
    width: px(440),
    height: px(440),
    borderRadius: px(12),
    backgroundColor: "rgba(255, 255, 255, 0.06)",
    alignItems: "center",
    justifyContent: "center",
  },
  side: { flex: 1, marginLeft: sp(8) },
  gap: { marginTop: sp(2) },
  url: { color: color.chalk, marginTop: sp(3) },
});
