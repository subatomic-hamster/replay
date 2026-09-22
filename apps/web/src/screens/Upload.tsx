// Phone uploader (I1, I2, I3, I5, W7-from-phone). Touch/mouse, not D-pad — these pages
// never run on the TV.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { API_BASE } from "../config";
import { navigate, useLocation } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import type { AutoCalibration, Game, SportProfile } from "../api/types";

const STAGES = ["ingest", "detect", "track", "render", "label"] as const;
// What courtcam's homography needs; the API enforces the same floor (D-19).
const MIN_LANDMARKS = 4;
// D-23: below this a proposed landmark is drawn hollow and is not committed until
// the user moves it. Same bar courtcam.autocalib uses before it fits a homography.
const MIN_CONFIDENCE = 0.5;

/** `/upload` — create a game (S-02, S-09). */
export function UploadCreate() {
  const { data: sports, error, reload } = useAsync(() => api.listSports(), []);
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const sport = picked ?? sports?.[0]?.id ?? "";

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;

  return (
    <div className="screen phone">
      <h1>New game</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!title.trim() || !sport || busy) return;
          setBusy(true);
          api
            .createGame(title.trim(), sport)
            // Carry upload_url forward so a page change does not lose it.
            .then((r) => navigate(`/upload/${r.id}?upload=${encodeURIComponent(r.upload_url)}`))
            .catch((err: Error) => setFailure(err.message))
            .finally(() => setBusy(false));
        }}
      >
        <label>
          Title
          <input
            data-testid="game-title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tuesday run"
            required
          />
        </label>
        <fieldset>
          <legend>Sport</legend>
          {(sports ?? []).map((s: SportProfile) => (
            <label key={s.id} className="radio">
              <input
                type="radio"
                name="sport"
                value={s.id}
                checked={sport === s.id}
                data-testid={`sport-option-${s.id}`}
                onChange={() => setPicked(s.id)}
              />
              {s.display_name} <span className="dim">tier {s.tier}</span>
            </label>
          ))}
        </fieldset>
        <button type="submit" data-testid="create-game" disabled={busy || !title.trim()}>
          Create game
        </button>
        {failure ? (
          <p className="error" data-testid="api-error">
            {failure}
          </p>
        ) : null}
      </form>
    </div>
  );
}

/** `/upload/:id` — upload the file (S-03) and manage the roster afterwards (S-26). */
export function UploadFile({ gameId }: { gameId: string }) {
  const { data: game, error, reload } = useAsync(() => api.getGame(gameId), [gameId]);
  const [pct, setPct] = useState<number | null>(null);
  const [done, setDone] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const { params } = useLocation();
  // API assumption: on a reload the create response is gone, so fall back to the
  // conventional local endpoint.
  const uploadUrl = params.get("upload") ?? `${API_BASE}/games/${gameId}/upload`;
  const inputRef = useRef<HTMLInputElement>(null);

  const start = useCallback(
    (file: File) => {
      if (!/^video\//.test(file.type)) {
        setFailure("That is not a video file.");
        return;
      }
      setFailure(null);
      setPct(0);
      api
        .upload(uploadUrl, file, setPct)
        .then(() => setDone(true))
        .catch((e: Error) => setFailure(e.message));
    },
    [uploadUrl],
  );

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;

  return (
    <div className="screen phone">
      <h1>{game?.title ?? "Upload"}</h1>
      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        data-testid="file-input"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) start(f);
        }}
      />
      {pct !== null ? (
        <>
          <progress data-testid="upload-progress" max={100} value={pct}>
            {pct}%
          </progress>
          <p className="upload-pct">{Math.round(pct)}% uploaded</p>
        </>
      ) : null}
      {done ? <p data-testid="upload-done">Upload complete.</p> : null}
      {failure ? (
        <p className="error" data-testid="upload-error">
          {failure}{" "}
          <button type="button" onClick={() => inputRef.current?.click()}>
            Retry
          </button>
        </p>
      ) : null}
      <button
        type="button"
        data-testid="go-calibrate"
        disabled={!done}
        onClick={() => navigate(`/upload/${gameId}/calibrate`)}
      >
        Calibrate
      </button>

      {game && game.players.length > 0 ? <Roster game={game} onChange={reload} /> : null}
    </div>
  );
}

/** W7 from the phone (S-26, E-17, E-18). */
function Roster({ game, onChange }: { game: Game; onChange: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);

  return (
    <section className="roster">
      <h2>Roster</h2>
      {game.players.map((p) => (
        <div key={p.id} className="roster-row" data-testid="roster-row" data-player-id={p.id}>
          <span className="swatch" style={{ backgroundColor: p.color_hex }} />
          <input
            data-testid={`roster-name-${p.id}`}
            value={draft[p.id] ?? p.name ?? ""}
            placeholder={p.id}
            onChange={(e) => setDraft((d) => ({ ...d, [p.id]: e.target.value }))}
          />
          <button
            type="button"
            data-testid={`roster-save-${p.id}`}
            onClick={() => {
              const name = (draft[p.id] ?? p.name ?? "").trim();
              if (!name) {
                setFailure("Name cannot be empty.");
                return;
              }
              api
                .patchPlayer(game.id, p.id, { name })
                .then(onChange)
                .catch((e: Error) => setFailure(e.message));
            }}
          >
            Save
          </button>
          <select
            data-testid={`roster-merge-${p.id}`}
            value=""
            onChange={(e) => {
              if (!e.target.value) return;
              api
                .patchPlayer(game.id, p.id, { merge_into: e.target.value })
                .then(onChange)
                .catch((err: Error) => setFailure(err.message));
            }}
          >
            <option value="">merge into…</option>
            {game.players
              .filter((o) => o.id !== p.id)
              .map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name ?? o.id}
                </option>
              ))}
          </select>
        </div>
      ))}
      {failure ? (
        <p className="error" data-testid="rename-error">
          {failure}
        </p>
      ) : null}
    </section>
  );
}

/** `/upload/:id/calibrate` — I2 (S-04, S-05, S-06, S-04b, E-05..E-08).
 *
 * Two ways in. D-23: on arrival the page asks the API to *propose* the landmarks with a
 * vision model and draws them as dots the user can accept or drag. Underneath, unchanged,
 * is the manual walk of `profile.landmarks` plus `landmarks_optional` behind "more
 * points" — the proposal is an accelerator, never a gate, and the busy overlay is
 * deliberately click-through so the walk stays usable while the model thinks.
 *
 * Real wide footage routinely puts a corner off-frame (D-18) and guessing at it wrecks
 * the fit far worse than leaving it out (~20 px vs 0.3 px on the Kennesaw clip), so any
 * single point can be skipped — the API only needs 4 points the template knows (D-19).
 */
export function Calibrate({ gameId }: { gameId: string }) {
  const { data, error, reload } = useAsync(
    () => Promise.all([api.getGame(gameId), api.listSports()]),
    [gameId],
  );
  const [variant, setVariant] = useState("half");
  const [more, setMore] = useState(false);
  const [marks, setMarks] = useState<Record<string, [number, number]>>({});
  const [step, setStep] = useState(0);
  const [result, setResult] = useState<{ ok: boolean; px?: number; msg?: string } | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // D-23 state. `weak` are proposed points below the confidence bar: drawn hollow, not
  // committed until the user moves one.
  const [auto, setAuto] = useState<AutoCalibration | null>(null);
  const [weak, setWeak] = useState<Record<string, [number, number]>>({});
  const [taken, setTaken] = useState<"none" | "applied" | "manual">("none");
  const [adjust, setAdjust] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);
  const marksRef = useRef(marks);
  marksRef.current = marks;
  const variantRef = useRef(variant);
  variantRef.current = variant;

  const game = data?.[0];
  const profile = data?.[1].find((s) => s.id === game?.sport) ?? data?.[1][0];
  const required = useMemo(() => profile?.landmarks ?? [], [profile]);
  const optional = useMemo(() => profile?.landmarks_optional ?? [], [profile]);
  const names = useMemo(
    () => (more ? [...required, ...optional] : required),
    [more, required, optional],
  );

  const submit = useCallback(
    (pts: Record<string, [number, number]>) => {
      if (!game || !profile || Object.keys(pts).length < MIN_LANDMARKS) {
        setResult(null);
        return;
      }
      api
        .calibrate(game.id, {
          sport: profile.id,
          court_variant: variantRef.current,
          landmarks_px: pts,
        })
        .then((r) =>
          setResult(
            r.ok
              ? { ok: true, px: r.reprojection_error_px }
              : { ok: false, msg: r.error ?? "invalid points" },
          ),
        )
        .catch((e: Error) => setResult({ ok: false, msg: e.message }));
    },
    [game, profile],
  );

  // Re-validate when the variant changes, once the required walk is behind us.
  useEffect(() => {
    if (step >= required.length) submit(marks);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variant]);

  // D-23: ask for a proposal as soon as the page has a game and a sport, and poll for
  // it. The model call is 10-180 s, so this is a queue + poll, not a request.
  const gid = game?.id;
  const sportId = profile?.id;
  useEffect(() => {
    if (!gid || !sportId) return;
    let live = true;
    let timer = 0;
    const poll = () =>
      api.getAutoCalibration(gid).then(
        (r) => {
          if (!live) return;
          setAuto(r);
          if (r.status !== "done" && r.status !== "failed") timer = window.setTimeout(poll, 1200);
        },
        () => live && setAuto({ status: "failed", ok: false }),
      );
    api
      .startAutoCalibration(gid, sportId, variantRef.current)
      .then(() => live && void poll())
      .catch(() => live && setAuto({ status: "failed", ok: false }));
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [gid, sportId]);

  /** Image-space pixel for a pointer position, clamped to the frame (E-07). */
  const pointAt = useCallback((clientX: number, clientY: number): [number, number] | null => {
    const img = imgRef.current;
    if (!img) return null;
    const r = img.getBoundingClientRect();
    const w = img.naturalWidth || r.width;
    const h = img.naturalHeight || r.height;
    return [
      Math.max(0, Math.min(w, Math.round(((clientX - r.left) / r.width) * w))),
      Math.max(0, Math.min(h, Math.round(((clientY - r.top) / r.height) * h))),
    ];
  }, []);

  if (error) return <ApiErrorBanner error={error} onRetry={reload} />;
  if (!game || !profile) return <div className="screen phone">Loading…</div>;

  const next: string | undefined = names[step];
  const placed = Object.keys(marks);
  // The API owns the threshold (it scales with the clicked court's pixel span, because
  // 5 px is unreachable by hand on a 2560-px panorama — courtcam.calibrate). A 200 is a
  // usable fit, with or without a number attached; a 400 comes back as `ok: false`.
  const valid = !!result?.ok;

  const advance = (pts: Record<string, [number, number]>) => {
    setMarks(pts);
    setStep(step + 1);
    if (step + 1 >= required.length) submit(pts);
  };

  const proposal = auto?.status === "done" ? auto.proposal : undefined;
  const pending =
    taken === "none" && (auto === null || auto.status === "queued" || auto.status === "running");
  // Only draw the proposal while the user has not started clicking — once they have,
  // their points are the truth and two sets of dots would be a lie about which is which.
  const offering = !!proposal && taken === "none" && placed.length === 0;
  const dots: [string, [number, number], number][] = offering
    ? Object.entries(proposal.landmarks_px).map(([n, p]) => [n, p, proposal.confidence[n] ?? 0])
    : [
        ...placed.map((n): [string, [number, number], number] => [n, marks[n], 1]),
        ...Object.keys(weak).map((n): [string, [number, number], number] => [n, weak[n], 0]),
      ];

  /** Take the proposal: confident points become the calibration, weak ones stay hollow. */
  const applyProposal = (intoAdjust: boolean) => {
    if (!proposal) return;
    const strong: Record<string, [number, number]> = {};
    const hollow: Record<string, [number, number]> = {};
    for (const [n, p] of Object.entries(proposal.landmarks_px)) {
      ((proposal.confidence[n] ?? 0) >= MIN_CONFIDENCE ? strong : hollow)[n] = p;
    }
    setMarks(strong);
    marksRef.current = strong;
    setWeak(hollow);
    setStep(names.length);
    setTaken("applied");
    setAdjust(intoAdjust);
    submit(strong);
  };

  const moveHandle = (name: string, clientX: number, clientY: number) => {
    const px = pointAt(clientX, clientY);
    if (!px) return;
    setWeak((w) => {
      if (!(name in w)) return w;
      const rest = { ...w };
      delete rest[name];
      return rest;
    });
    const next = { ...marksRef.current, [name]: px };
    marksRef.current = next;
    setMarks(next);
  };

  return (
    <div className="screen phone calibrate">
      <h1>Calibrate</h1>
      <div className="variant">
        {(profile.variants ?? ["half", "full"]).map((v) => (
          <label key={v} className="radio">
            <input
              type="radio"
              name="variant"
              checked={variant === v}
              data-testid={`variant-${v}`}
              onChange={() => setVariant(v)}
            />
            {v}
          </label>
        ))}
      </div>

      <div className="autocalib">
        <p
          data-testid="autocalib-status"
          data-state={taken !== "none" ? taken : (auto?.status ?? "queued")}
        >
          {taken === "manual"
            ? "Placing the points by hand."
            : taken === "applied"
              ? adjust
                ? "Drag any point that looks wrong."
                : "Using the proposed points."
              : pending
                ? "Finding the court…"
                : proposal && Object.keys(proposal.landmarks_px).length > 0
                  ? `Found ${Object.keys(proposal.landmarks_px).length} points` +
                    (proposal.reprojection_error_px != null
                      ? ` · ${proposal.reprojection_error_px.toFixed(1)} px`
                      : "") +
                    (proposal.ok ? "" : " · needs a check")
                  : "Could not find the court — place the points yourself."}
        </p>
        {offering ? (
          <>
            <button type="button" data-testid="autocalib-accept" onClick={() => applyProposal(false)}>
              Looks right — continue
            </button>
            <button
              type="button"
              className="secondary"
              data-testid="autocalib-adjust"
              onClick={() => applyProposal(true)}
            >
              Adjust
            </button>
          </>
        ) : null}
        {taken === "none" ? (
          <button
            type="button"
            className="secondary"
            data-testid="autocalib-manual"
            onClick={() => {
              setTaken("manual");
              setAdjust(false);
              setStep(0);
              setMarks({});
              marksRef.current = {};
              setWeak({});
              setResult(null);
            }}
          >
            Place points myself
          </button>
        ) : null}
      </div>

      <p className="calib-prompt" data-testid="calib-prompt">
        {next
          ? `Tap ${next.replace(/_/g, " ")} — point ${step + 1} of ${names.length}`
          : "All landmarks placed."}
      </p>

      <div className="calib-frame">
        <img
          ref={imgRef}
          src={api.mediaUrl(game, game.calib_url ?? "calib.jpg")}
          alt="Calibration frame"
          data-testid="calib-image"
          onClick={(e) => {
            // E-07: coordinates are derived from the image rect, so a click can never
            // land outside [0,naturalWidth] x [0,naturalHeight].
            if (!next) return;
            const px = pointAt(e.clientX, e.clientY);
            if (px) advance({ ...marks, [next]: px });
          }}
        />
        {dots.map(([name, p, conf]) => {
          const img = imgRef.current;
          const w = img?.naturalWidth || 1;
          const h = img?.naturalHeight || 1;
          const hollow = conf < MIN_CONFIDENCE;
          const at = { left: `${(p[0] / w) * 100}%`, top: `${(p[1] / h) * 100}%` };
          return (
            <span key={name} style={{ display: "contents" }}>
              <span
                className={`landmark${hollow ? " hollow" : ""}`}
                data-testid={`landmark-${name}`}
                data-confidence={conf.toFixed(2)}
                style={{
                  ...at,
                  // Confidence-tinted ring: red at 0, green at 1.
                  boxShadow: offering
                    ? `0 0 0 4px hsl(${Math.round(conf * 120)} 85% 45%)`
                    : undefined,
                }}
                title={name.replace(/_/g, " ")}
              >
                {names.indexOf(name) + 1}
              </span>
              {adjust ? (
                <button
                  type="button"
                  className="landmark-handle"
                  data-testid={`landmark-handle-${name}`}
                  aria-label={`Move ${name.replace(/_/g, " ")}`}
                  style={at}
                  onPointerDown={(e) => {
                    e.preventDefault();
                    e.currentTarget.setPointerCapture(e.pointerId);
                    setDragging(name);
                  }}
                  onPointerMove={(e) => {
                    if (dragging === name) moveHandle(name, e.clientX, e.clientY);
                  }}
                  onPointerUp={(e) => {
                    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                      e.currentTarget.releasePointerCapture(e.pointerId);
                    }
                    if (dragging !== name) return;
                    setDragging(null);
                    moveHandle(name, e.clientX, e.clientY);
                    submit(marksRef.current);
                  }}
                />
              ) : null}
            </span>
          );
        })}
        {pending ? (
          <div className="autocalib-busy" data-testid="autocalib-busy">
            <span className="autocalib-spin" />
            Finding the court…
          </div>
        ) : null}
      </div>

      <div className="calib-actions">
        <p
          className={`calib-error${result && !valid ? " bad" : ""}`}
          data-testid="calib-error"
          data-ok={valid ? "true" : "false"}
        >
          {result?.ok
            ? `${result.px?.toFixed(1) ?? "?"} px`
            : result
              ? result.msg
              : `need ${Math.max(0, required.length - placed.length)} more points`}
        </p>
        <button
          type="button"
          className="secondary"
          data-testid="calib-skip"
          disabled={!next}
          onClick={() => {
            if (!next) return;
            const pts = { ...marks };
            delete pts[next];
            advance(pts);
          }}
        >
          Not visible
        </button>
        <button
          type="button"
          className="secondary"
          data-testid="calib-undo"
          disabled={step === 0}
          onClick={() => {
            const pts = { ...marks };
            delete pts[names[step - 1]];
            setMarks(pts);
            marksRef.current = pts;
            setStep(step - 1);
            setResult(null);
          }}
        >
          Undo
        </button>
        {optional.length > 0 && !more ? (
          <button
            type="button"
            className="secondary"
            data-testid="calib-more"
            onClick={() => setMore(true)}
          >
            More points
          </button>
        ) : null}
      </div>

      <button
        type="button"
        data-testid="start-processing"
        disabled={!valid}
        onClick={() =>
          api
            .startProcessing(game.id)
            .then(() => navigate(`/upload/${game.id}/status`))
            .catch(() => {})
        }
      >
        Start processing
      </button>
    </div>
  );
}


/** `/upload/:id/status` — I3 (S-07, S-08). */
export function UploadStatus({ gameId }: { gameId: string }) {
  const [game, setGame] = useState<Game | null>(null);
  const [failure, setFailure] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let live = true;
    const poll = () =>
      api.getGame(gameId).then(
        (g) => live && setGame(g),
        (e: Error) => live && setFailure(e),
      );
    void poll();
    const timer = setInterval(poll, 2000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [gameId, nonce]);

  if (failure) return <ApiErrorBanner error={failure} onRetry={() => setNonce((n) => n + 1)} />;

  return (
    <div className="screen phone">
      <h1>{game?.title ?? "Processing"}</h1>
      <p>
        Status: <strong data-testid="game-status">{game?.status ?? "…"}</strong>
      </p>
      <ol className="stages">
        {STAGES.map((s) => {
          const state = game?.stages?.[s] ?? "pending";
          return (
            <li key={s} className={`stage ${state}`} data-testid={`stage-${s}`} data-state={state}>
              <span className="stage-name">{s}</span>
              <span className="stage-state">{state}</span>
            </li>
          );
        })}
      </ol>
      {game?.status === "ready" ? (
        <button type="button" onClick={() => navigate(`/upload/${gameId}`)}>
          Name the players
        </button>
      ) : null}
    </div>
  );
}
