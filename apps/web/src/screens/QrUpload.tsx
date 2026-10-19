// D-80 phone page: `/u/:id#t=<token>`, opened from the QR code the TV shows. No app, no
// login: the per-game upload token in the fragment (never sent to CloudFront or S3 logs)
// authenticates every call. Pick the video, upload it straight to S3 in parts, then the
// existing calibrate and status screens with the token client.
import { useMemo, useRef, useState } from "react";
import { ApiError, createHttpApi, uploadVideo, type ReplayApi } from "../../../../packages/tv-core/src/api";
import { mockUploadApi } from "../../../../packages/tv-core/src/mock";
import type { Game } from "../api/types";
import { API_BASE, MOCK_API } from "../config";
import { navigate } from "../router";
import { useAsync } from "../ui";
import { Calibrate, UploadStatus } from "./Upload";

const EXPIRED = "This upload link has expired. On the TV, choose Add game again for a new QR code.";

function explain(e: Error): string {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return EXPIRED;
  if (e instanceof ApiError && e.status === 404) return "This game no longer exists. Start again from the TV.";
  return `Could not reach Replay: ${e.message}`;
}

export function QrUpload({ gameId, step }: { gameId: string; step?: string }) {
  const token = useMemo(() => new URLSearchParams(window.location.hash.slice(1)).get("t") ?? "", []);
  const client = useMemo(
    () => (MOCK_API ? mockUploadApi(token) : createHttpApi(API_BASE, "", token)),
    [token],
  );
  const { data: game, error, reload } = useAsync(() => client.getGame(gameId), [client, gameId]);
  // The fragment rides along on every step, so a reload keeps working.
  const to = (s: string) => `/u/${gameId}${s}${window.location.hash}`;

  if (!token) {
    return <Problem text="This link is missing its upload code. Scan the QR code on the TV again." />;
  }
  if (error) return <Problem text={explain(error)} onRetry={reload} />;
  if (!game) return <div className="screen phone">Loading…</div>;
  if (step === "calibrate") return <Calibrate gameId={gameId} client={client} statusPath={to("/status")} />;
  if (step === "status") {
    return <UploadStatus gameId={gameId} client={client} readyNote="Ready. Watch it on the TV." />;
  }
  return <PickVideo game={game} client={client} onUploaded={() => navigate(to("/calibrate"))} next={to} />;
}

function Problem({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="screen phone">
      <h1>Replay</h1>
      <p className="error" data-testid="qr-problem" role="alert">
        {text}
      </p>
      {onRetry && text !== EXPIRED ? (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

function PickVideo({
  game,
  client,
  onUploaded,
  next,
}: {
  game: Game;
  client: ReplayApi;
  onUploaded: () => void;
  next: (step: string) => string;
}) {
  const [pct, setPct] = useState<number | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const file = useRef<File | null>(null);
  const cancel = useRef<AbortController | null>(null);

  const start = () => {
    const f = file.current;
    if (!f) return;
    const ctl = new AbortController();
    cancel.current = ctl;
    setFailure(null);
    setPct(0);
    // A locked screen suspends the page and stalls the upload; keep it awake while it runs.
    const lock = navigator.wakeLock?.request("screen").catch(() => null);
    uploadVideo(client, game.id, f, `${API_BASE}/games/${game.id}/upload`, setPct, ctl.signal)
      .then(onUploaded, (e: Error) => {
        setPct(null);
        setFailure(ctl.signal.aborted ? "Upload cancelled." : e instanceof ApiError && e.status === 401 ? EXPIRED : `Upload failed: ${e.message}`);
      })
      .finally(() => void lock?.then((l) => l?.release()));
  };

  // Already past the upload (a second scan, or Back from calibration): go on from there.
  if (game.status !== "created" && game.status !== "uploading") {
    const step = game.status === "uploaded" ? "/calibrate" : "/status";
    return (
      <div className="screen phone">
        <h1>{game.title}</h1>
        <p data-testid="already-uploaded">The video for this game is already uploaded.</p>
        <button type="button" data-testid="qr-continue" onClick={() => navigate(next(step))}>
          {step === "/calibrate" ? "Calibrate" : "See progress"}
        </button>
      </div>
    );
  }

  return (
    <div className="screen phone" data-testid="qr-upload">
      <h1>{game.title}</h1>
      <p className="dim">Pick the game video. Keep this page open until the upload finishes.</p>
      <label>
        Video
        <input
          type="file"
          accept="video/*"
          data-testid="file-input"
          disabled={pct !== null}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            if (!/^video\//.test(f.type)) {
              setFailure("That is not a video file.");
              return;
            }
            file.current = f;
            start();
          }}
        />
      </label>
      {pct !== null ? (
        <>
          <progress data-testid="upload-progress" max={100} value={pct}>
            {pct}%
          </progress>
          <p className="upload-pct" data-testid="upload-pct">
            {pct}% uploaded
          </p>
          <button type="button" className="secondary" data-testid="upload-cancel" onClick={() => cancel.current?.abort()}>
            Cancel
          </button>
        </>
      ) : null}
      {failure ? (
        <>
          <p className="error" data-testid="upload-error" role="alert">
            {failure}
          </p>
          {file.current && failure !== EXPIRED ? (
            <button type="button" data-testid="upload-retry" onClick={start}>
              Retry upload
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
