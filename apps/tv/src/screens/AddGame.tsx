// D-80 "Add game" (docs/ux/redesign.md "Add game"), two beats on one screen: pick the
// sport tile with the D-pad (POST /games), then the QR code of the phone upload page with
// its short URL, and a status line that follows the game while the phone does the work:
// waiting, uploading, uploaded, calibrated, processing, and ready, which opens it. Back
// returns to Home at any point; the game stays (it shows on Home while it processes).
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import type {
  CreateGameResult,
  Game,
} from "../../../../packages/tv-core/src/types";
import { api } from "../api";
import { QrCode } from "../components/QrCode";
import { progressOf, stageWords } from "../gameState";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, px, radius, safe, sp, type } from "../theme";
import {
  ApiErrorBanner,
  ContextChip,
  Focusable,
  KeyLegend,
  Spinner,
  T,
  styles as ui,
  useAsync,
} from "../ui";

/** Poll GET /games/{id} this often while the screen is open (a Lambda call each in cloud mode). */
const POLL_MS = 2000;

const PHASE: Record<string, string> = {
  created: "Waiting for your phone…",
  uploading: "Uploading…",
  uploaded: "Uploaded. Calibrating on the phone…",
  calibrated: "Calibrated. Start processing on the phone.",
  processing: "Processing. It's on Home.",
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
      else if (a === "right")
        setFocus((i) => Math.min(sports.length - 1, i + 1));
      else if (a === "select") {
        const s = sports[focus];
        const day = new Date().toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        });
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
      <View style={ui.safe} testID="add-game">
        <ContextChip parts={["Home", "Add game"]} kind="room" />
        <T style={[type.display, styles.head]}>Add a game</T>
        <T style={[type.body, styles.sub]}>Which sport?</T>
        <View style={styles.tiles}>
          {sports ? null : (
            <View style={styles.tileSpin}>
              <Spinner testID="add-loading" />
            </View>
          )}
          {(sports ?? []).map((s, i) => (
            <View
              key={s.id}
              style={styles.tileSlot}
              testID={`add-sport-${s.id}`}
              dataSet={{ focused: i === focus ? "true" : "false" }}
            >
              <Focusable focused={i === focus}>
                <View style={styles.tile}>
                  <T style={type.title} numberOfLines={1}>
                    {s.display_name}
                  </T>
                </View>
              </Focusable>
            </View>
          ))}
        </View>
        {busy ? (
          <View style={styles.busyRow} testID="add-creating">
            <Spinner small delay={0} />
            <T style={[type.body, styles.busyText]}>Creating the game</T>
          </View>
        ) : null}
        <KeyLegend
          items={[
            { k: "◀▶", label: "Sport" },
            { k: "Select", label: "Choose" },
            { k: "Back", label: "Home" },
          ]}
          style={styles.legend}
        />
      </View>
    );
  }

  const status = game?.status ?? "created";
  const working = status === "processing" && game;

  return (
    <View
      style={[ui.safe, styles.pair]}
      testID="add-game"
      dataSet={{ gameId: created.id }}
    >
      <ContextChip parts={["Home", "Add game"]} kind="room" />
      {created.upload_page_url ? (
        <QrCode text={created.upload_page_url} size={520} testID="add-qr" />
      ) : (
        <T testID="add-no-qr" style={[styles.side, { color: color.bleacher }]}>
          This Replay API has no public web address (REPLAY_PUBLIC_WEB_BASE), so
          there is no QR code. Upload from a phone at /upload instead.
        </T>
      )}
      <View style={styles.side}>
        <T style={type.title}>Scan with your phone's camera</T>
        <T style={[type.body, styles.sub]}>
          It opens a page to pick the video and upload it.
        </T>
        {/* Address only, never the token (the `#t=` fragment): it is in the QR code alone. */}
        <T testID="add-url" style={[type.figures, styles.url]}>
          {
            (created.upload_page_url ?? "")
              .replace(/^https?:\/\//, "")
              .split("#")[0]
          }
        </T>
        <T
          testID="add-status"
          dataSet={{ status }}
          style={[type.title, styles.status]}
        >
          {PHASE[status] ?? status}
        </T>
        {working ? (
          <>
            <T
              testID="add-stage"
              style={[type.body, { color: color.bleacher }]}
            >
              {stageWords(game)}
            </T>
            <View style={styles.bar}>
              <View
                testID="add-progress"
                style={[
                  styles.fill,
                  { width: `${Math.round(progressOf(game) * 100)}%` },
                ]}
              />
            </View>
          </>
        ) : null}
        <T style={[type.body, styles.sub, { marginTop: sp(6) }]}>
          You can go back to Home. The game appears there and plays as soon as
          it's ready.
        </T>
      </View>
      <KeyLegend items={[{ k: "Back", label: "Home" }]} style={styles.legend} />
    </View>
  );
}

const styles = StyleSheet.create({
  head: { marginTop: px(120) },
  sub: { color: color.bleacher, marginTop: sp(1) },
  tiles: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginTop: sp(6),
    marginLeft: -px(8),
  },
  tileSlot: { marginRight: sp(3), marginBottom: sp(3) },
  tileSpin: { height: px(216), justifyContent: "center", marginLeft: sp(4) },
  busyRow: { flexDirection: "row", alignItems: "center" },
  busyText: { color: color.bleacher, marginLeft: sp(2) },
  tile: {
    width: px(360),
    height: px(200),
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: sp(3),
  },
  legend: { bottom: safe.y },
  pair: { flexDirection: "row", alignItems: "center" },
  side: { flex: 1, marginLeft: sp(10) },
  url: { color: color.chalk, marginTop: sp(3) },
  status: { marginTop: sp(6) },
  bar: {
    height: px(8),
    borderRadius: radius.chip,
    backgroundColor: color.line,
    marginTop: sp(2),
    overflow: "hidden",
    maxWidth: px(720),
  },
  fill: { height: "100%", backgroundColor: color.scoreboard },
});
