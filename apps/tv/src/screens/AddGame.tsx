// D-80 "Add game": pick the sport with the D-pad, POST /games, and show the QR code of the
// phone upload page (plus its URL). Then follow the game while the phone does the work:
// waiting for the upload, uploaded, calibrated, processing stage by stage, and ready,
// which opens it. Back returns to the library at any point; the game stays.
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import type { CreateGameResult, Game } from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { QrCode } from "../components/QrCode";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, font, px } from "../theme";
import { ApiErrorBanner, Hint, Pill, T, styles as ui, useAsync } from "../ui";

/** Poll GET /games/{id} this often while the screen is open (a Lambda call each in cloud mode). */
const POLL_MS = 2000;

const PHASE: Record<string, string> = {
  created: "Waiting for the upload…",
  uploading: "Uploading…",
  uploaded: "Uploaded. Calibrating on the phone…",
  calibrated: "Calibrated. Start processing on the phone.",
  processing: "Processing",
  ready: "Ready",
  error: "Processing failed. The phone has the details.",
};

export function AddGame() {
  const { data: sports, error, reload } = useAsync(() => api.listSports(), []);
  const [focus, setFocus] = useState(0);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Error | null>(null);
  const [created, setCreated] = useState<CreateGameResult | null>(null);
  const [game, setGame] = useState<Game | null>(null);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "back") {
        navigate({ name: "library" });
        return;
      }
      if (created || busy || !sports?.length) return;
      if (a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "right") setFocus((i) => Math.min(sports.length - 1, i + 1));
      else if (a === "select") {
        const s = sports[focus];
        const day = new Date().toLocaleDateString(undefined, { month: "short", day: "numeric" });
        setBusy(true);
        api
          .createGame(`${s.display_name} · ${day}`, s.id)
          .then(setCreated, setFailure)
          .finally(() => setBusy(false));
      }
    },
    [created, busy, sports, focus],
  );
  useDpad(onAction);

  const id = created?.id;
  useEffect(() => {
    if (!id) return;
    let live = true;
    const poll = () =>
      api.getGame(id).then(
        (g) => {
          if (!live) return;
          setGame(g);
          if (g.status === "ready") navigate({ name: "watch", gameId: g.id });
        },
        () => {}, // a missed poll is just retried on the next tick
      );
    void poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [id]);

  const err = error ?? failure;
  if (err) {
    return (
      <ApiErrorBanner
        error={err}
        onRetry={() => {
          setFailure(null);
          reload();
        }}
      />
    );
  }

  if (!created) {
    return (
      <View style={ui.screen} testID="add-game">
        <T style={ui.h1}>Add a game</T>
        <T style={{ color: color.dim, marginBottom: px(24) }}>Which sport?</T>
        <View style={styles.row}>
          {(sports ?? []).map((s, i) => (
            <Pill key={s.id} label={s.display_name} focused={i === focus} testID={`add-sport-${s.id}`} />
          ))}
        </View>
        {busy ? <T>Creating the game…</T> : null}
        <Hint>Left/Right picks · Select creates the game · Back returns</Hint>
      </View>
    );
  }

  const status = game?.status ?? "created";
  const stages = Object.entries(game?.stages ?? {});
  const done = stages.filter(([, s]) => s === "done").length;
  const running = stages.find(([, s]) => s === "running")?.[0];
  const frac = running ? (game?.progress?.[running] ?? 0) : 0;

  return (
    <View style={ui.screen} testID="add-game" dataSet={{ gameId: created.id }}>
      <T style={ui.h1}>Upload from your phone</T>
      <View style={styles.row}>
        {created.upload_page_url ? (
          <QrCode text={created.upload_page_url} size={640} testID="add-qr" />
        ) : (
          <T testID="add-no-qr" style={styles.side}>
            This Replay API has no public web address (REPLAY_PUBLIC_WEB_BASE), so there is no QR
            code. Upload from a phone at /upload instead.
          </T>
        )}
        <View style={styles.side}>
          <T style={ui.h2}>Scan with your phone camera</T>
          {/* Address only, never the token (the `#t=` fragment): it is in the QR code alone. */}
          <T style={{ color: color.dim }}>It opens the Replay upload page:</T>
          <T testID="add-url" style={styles.url}>
            {(created.upload_page_url ?? "").replace(/^https?:\/\//, "").split("#")[0]}
          </T>
          <T testID="add-status" dataSet={{ status }} style={styles.status}>
            {status === "processing" && running
              ? `Processing · ${running} · stage ${done + 1} of ${stages.length} · ${Math.round(frac * 100)}%`
              : (PHASE[status] ?? status)}
          </T>
          {status === "processing" && stages.length ? (
            <View style={styles.bar}>
              <View
                testID="add-progress"
                style={[styles.fill, { width: `${Math.round(((done + frac) / stages.length) * 100)}%` }]}
              />
            </View>
          ) : null}
          <Hint>The game opens here when it is ready · Back returns to the library</Hint>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-start" },
  side: { flex: 1, marginLeft: px(56) },
  url: { fontSize: font.small, color: color.fg, marginTop: px(8) },
  status: { fontSize: font.h2, fontWeight: "700", color: color.accent, marginTop: px(40) },
  bar: { height: px(16), borderRadius: px(8), backgroundColor: color.raised, marginTop: px(16), overflow: "hidden" },
  fill: { height: "100%", backgroundColor: color.accent },
});
