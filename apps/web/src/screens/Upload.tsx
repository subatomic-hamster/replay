// Phone uploader (I1, I2, I3, I5, W7-from-phone). Touch/mouse, not D-pad — these pages
// never run on the TV.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api } from "../api/client";
import { API_BASE } from "../config";
import { navigate, useLocation } from "../router";
import { ApiErrorBanner, useAsync } from "../ui";
import type { AutoCalibration, Game, SportProfile } from "../api/types";

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
  // Bug 1: this used to be `useState("half")`, which is basketball's. A profile whose
  // only variant is `doubles` then had no radio checked and posted `variant: "half"`,
  // which the API 400s. The picked value wins; otherwise the profile's first variant.
  const [pickedVariant, setPickedVariant] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [marks, setMarks] = useState<Record<string, [number, number]>>({});
  const [step, setStep] = useState(0);
  const [result, setResult] = useState<{
    ok: boolean;
    px?: number;
    msg?: string;
    residuals?: Record<string, number>;
  } | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // D-23 state. `weak` are proposed points below the confidence bar: drawn hollow, not
  // committed until the user moves one.
  const [auto, setAuto] = useState<AutoCalibration | null>(null);
  const [weak, setWeak] = useState<Record<string, [number, number]>>({});
  const [taken, setTaken] = useState<"none" | "applied" | "manual">("none");
  const [adjust, setAdjust] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);
  // A drag moves a point; a tap (no movement) selects it, so the next frame tap or
  // "Not visible" acts on that point instead of the walk cursor.
  const dragFrom = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // Points taken off by "Not visible" on a selection: the walk must not ask for them again.
  const [skipped, setSkipped] = useState<string[]>([]);
  const marksRef = useRef(marks);
  marksRef.current = marks;

  const game = data?.[0];
  const profile = data?.[1].find((s) => s.id === game?.sport) ?? data?.[1][0];
  const variants = useMemo(
    () => (profile?.variants?.length ? profile.variants : ["half", "full"]),
    [profile],
  );
  const variant = pickedVariant ?? variants[0];
  const variantRef = useRef(variant);
  variantRef.current = variant;
  const required = useMemo(() => profile?.landmarks ?? [], [profile]);
  const optional = useMemo(() => profile?.landmarks_optional ?? [], [profile]);
  const names = useMemo(
    () => (more ? [...required, ...optional] : required),
    [more, required, optional],
  );
  // The walk cursor is the first landmark at or after `step` that is neither placed nor
  // skipped. In the manual walk that is just `names[step]`; after a proposal is applied
  // it jumps over the proposed points to whatever the proposal left out.
  const pendingFrom = (list: readonly string[], from: number, pts: object, skip: string[]) =>
    list.filter((n, i) => i >= from && !(n in pts) && !skip.includes(n));

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
              ? { ok: true, px: r.reprojection_error_px, residuals: r.residuals_px }
              : { ok: false, msg: r.error ?? "invalid points" },
          ),
        )
        .catch((e: Error) => setResult({ ok: false, msg: e.message }));
    },
    [game, profile],
  );

  // Re-validate when the variant changes, once the required walk is behind us.
  useEffect(() => {
    if (pendingFrom(required, step, marks, skipped).length === 0) submit(marks);
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

  const next: string | undefined = selected ?? pendingFrom(names, step, marks, skipped)[0];
  const placed = Object.keys(marks);
  // The API owns the threshold (it scales with the clicked court's pixel span, because
  // 5 px is unreachable by hand on a 2560-px panorama — courtcam.calibrate). A 200 is a
  // usable fit, with or without a number attached; a 400 comes back as `ok: false`.
  const valid = !!result?.ok;
  // The homography now votes an outlying click out of the fit rather than letting it
  // poison the error (courtcam.calibrate), so the number alone no longer says which
  // point is wrong — the per-landmark residuals do.
  const worst = Object.entries(result?.residuals ?? {}).sort((a, b) => b[1] - a[1])[0];

  const dropWeak = (name: string) =>
    setWeak((w) => {
      if (!(name in w)) return w;
      const rest = { ...w };
      delete rest[name];
      return rest;
    });

  /** Walk past `name` (placed or skipped), validating once no required point is left. */
  const advance = (pts: Record<string, [number, number]>, name: string) => {
    const at = names.indexOf(name) + 1;
    setMarks(pts);
    marksRef.current = pts;
    dropWeak(name);
    setStep(at);
    if (pendingFrom(required, at, pts, skipped).length === 0) submit(pts);
  };

  /** A tap on the frame places the selected point, else the walk's next one. E-07:
   *  coordinates come from the image rect, so a tap never lands outside the frame. */
  const tapFrame = (clientX: number, clientY: number) => {
    if (!next) return;
    const px = pointAt(clientX, clientY);
    if (!px) return;
    if (selected) place(selected, px);
    else advance({ ...marks, [next]: px }, next);
  };

  /** Re-place (`px`) or take off (`null`) the selected point, outside the walk order. */
  const place = (name: string, px: [number, number] | null) => {
    const pts = { ...marksRef.current };
    if (px) pts[name] = px;
    else delete pts[name];
    setMarks(pts);
    marksRef.current = pts;
    dropWeak(name);
    setSkipped((s) => (px ? s.filter((n) => n !== name) : [...s, name]));
    setSelected(null);
    submit(pts);
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
    // Not parked past the end: whatever the proposal did not find is still walked.
    setStep(0);
    setSkipped([]);
    setSelected(null);
    setTaken("applied");
    setAdjust(intoAdjust);
    submit(strong);
  };

  const moveHandle = (name: string, clientX: number, clientY: number) => {
    const px = pointAt(clientX, clientY);
    if (!px) return;
    dropWeak(name);
    const next = { ...marksRef.current, [name]: px };
    marksRef.current = next;
    setMarks(next);
  };

  return (
    <div className="screen phone calibrate">
      <h1>Calibrate</h1>
      {/* One variant is not a choice — a radio group of one is just a thing to get wrong. */}
      {variants.length > 1 ? (
        <div className="variant">
          {variants.map((v) => (
            <label key={v} className="radio">
              <input
                type="radio"
                name="variant"
                checked={variant === v}
                data-testid={`variant-${v}`}
                onChange={() => setPickedVariant(v)}
              />
              {v}
            </label>
          ))}
        </div>
      ) : null}

      <div className="autocalib">
        <p
          data-testid="autocalib-status"
          data-state={taken !== "none" ? taken : (auto?.status ?? "queued")}
        >
          {taken === "manual"
            ? "Placing the points by hand."
            : taken === "applied"
              ? adjust
                ? "Drag any point that looks wrong, or tap it to re-place it or mark it not visible."
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
              setSkipped([]);
              setSelected(null);
              setResult(null);
            }}
          >
            Place points myself
          </button>
        ) : null}
      </div>

      <p className="calib-prompt" data-testid="calib-prompt" data-target={next ?? ""}>
        {selected
          ? `Tap where ${selected.replace(/_/g, " ")} really is, or "Not visible" if it is off the frame.`
          : next
            ? `Tap ${next.replace(/_/g, " ")} — point ${names.indexOf(next) + 1} of ${names.length}`
            : "All landmarks placed."}
      </p>

      <div className="calib-frame">
        <img
          ref={imgRef}
          src={api.mediaUrl(game, game.calib_url ?? "calib.jpg")}
          alt="Calibration frame"
          data-testid="calib-image"
          onClick={(e) => tapFrame(e.clientX, e.clientY)}
        />
        {dots.map(([name, p, conf]) => {
          const img = imgRef.current;
          const w = img?.naturalWidth || 1;
          const h = img?.naturalHeight || 1;
          const hollow = conf < MIN_CONFIDENCE;
          const at = { left: `${(p[0] / w) * 100}%`, top: `${(p[1] / h) * 100}%` };
          // A proposed point can sit off the frame (an invented corner); its 44 px handle
          // is kept fully inside the frame so it can still be tapped and marked "Not
          // visible". The dot itself stays where the point really is.
          const pin = (v: number, max: number) => `clamp(22px, ${(v / max) * 100}%, 100% - 22px)`;
          const handleAt = { left: pin(p[0], w), top: pin(p[1], h) };
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
                  className={`landmark-handle${selected === name ? " selected" : ""}`}
                  data-testid={`landmark-handle-${name}`}
                  aria-label={`Move ${name.replace(/_/g, " ")}`}
                  aria-pressed={selected === name}
                  style={handleAt}
                  onPointerDown={(e) => {
                    e.preventDefault();
                    e.currentTarget.setPointerCapture(e.pointerId);
                    dragFrom.current = { x: e.clientX, y: e.clientY, moved: false };
                    setDragging(name);
                  }}
                  onPointerMove={(e) => {
                    const from = dragFrom.current;
                    if (dragging !== name || !from) return;
                    if (!from.moved && Math.hypot(e.clientX - from.x, e.clientY - from.y) < 5) return;
                    from.moved = true;
                    moveHandle(name, e.clientX, e.clientY);
                  }}
                  onPointerUp={(e) => {
                    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                      e.currentTarget.releasePointerCapture(e.pointerId);
                    }
                    if (dragging !== name) return;
                    setDragging(null);
                    if (dragFrom.current?.moved) {
                      moveHandle(name, e.clientX, e.clientY);
                      setSelected(null);
                      submit(marksRef.current);
                    } else {
                      // A tap, not a drag. While a point is waiting to be placed (the
                      // selected one, else the walk's next) the tap is a frame tap for
                      // *that* point: landmarks can sit 15 px apart, well inside a 44 px
                      // handle, and a handle that swallowed the tap would silently pick
                      // the wrong point. With nothing waiting it selects this one; the
                      // chips under the frame select at any time.
                      if (next) tapFrame(e.clientX, e.clientY);
                      else setSelected(name);
                    }
                    dragFrom.current = null;
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

      {adjust && dots.length > 0 ? (
        <div className="calib-points" role="group" aria-label="Placed points">
          {dots.map(([name]) => (
            <button
              key={name}
              type="button"
              className="secondary"
              data-testid={`calib-point-${name}`}
              aria-pressed={selected === name}
              onClick={() => setSelected(selected === name ? null : name)}
            >
              {name.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      ) : null}

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
        {worst ? (
          <p className="calib-worst" data-testid="calib-worst">
            worst point: {worst[0].replace(/_/g, " ")} · {worst[1].toFixed(1)} px
          </p>
        ) : null}
        <button
          type="button"
          className="secondary"
          data-testid="calib-skip"
          disabled={!next}
          onClick={() => {
            if (!next) return;
            if (selected) return place(selected, null);
            const pts = { ...marks };
            delete pts[next];
            advance(pts, next);
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
            const last = names[step - 1];
            const pts = { ...marks };
            delete pts[last];
            setMarks(pts);
            marksRef.current = pts;
            setSkipped((s) => s.filter((n) => n !== last));
            setSelected(null);
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
      {/* The API's `stages` keys are the pipeline's own list, in run order (S-08), so the
          page renders whatever it is sent rather than a copy that goes stale. */}
      <ol className="stages">
        {Object.entries(game?.stages ?? {}).map(([s, state]) => {
          const frac = state === "running" ? game?.progress?.[s] : undefined;
          return (
            <li
              key={s}
              className={`stage ${state}`}
              data-testid={`stage-${s}`}
              data-state={state}
              data-progress={frac ?? ""}
              style={frac != null ? ({ "--p": frac } as CSSProperties) : undefined}
            >
              <span className="stage-name">{s}</span>
              <span className="stage-state">
                {state}
                {frac != null ? ` · ${Math.round(frac * 100)}%` : ""}
              </span>
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
