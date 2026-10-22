// R-07 — the demo VIDEO, on the badminton auditorium clip. Not a product assertion
// (R-05 owns that); this exists to produce `samples/real/e2e/badminton-demo.mp4`, a
// paced end-to-end recording of the phone flow and the TV flow on real footage.
//
// Opt-in and self-skipping, like every spec in this directory: the clip and the
// landmark file are gitignored third-party footage (D-7), and so is the output.
//
//   REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-07
//
// Two recorded contexts, because the middle of the run is a 4-5 minute YOLO pass that
// nobody wants in a demo reel:
//   A  /upload -> calibrate -> start processing -> ~10 s of the status page   (recorded)
//      poll GET /games/:id until `ready`                                      (not recorded)
//   B  /tv library -> watch -> select -> follow -> spotlight -> highlights -> review
// The two .webm files are captioned, normalised to 30 fps and concatenated with ffmpeg.
import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { API, REPO, clip, haveClip, videoState, waitForVideo } from "./helpers";

const CLIP = "badminton_auditorium_smoke.mp4";
const MARKS = "badminton_auditorium_240s.landmarks.json";
const TITLE = "Auditorium badminton (demo)";
const SPORT = "badminton";
const VARIANT = "doubles";

const OUT = path.join(REPO, "samples/real/e2e");
const MP4 = path.join(OUT, "badminton-demo.mp4");
const FRAMES = path.join(OUT, "badminton-demo-frames");
const SIZE = { width: 1920, height: 1080 };

/** A pause long enough for a viewer to follow what just happened. */
const beat = (p: Page, ms = 900) => p.waitForTimeout(ms);

const sh = (cmd: string, args: string[]) =>
  execFileSync(cmd, args, { encoding: "utf8", maxBuffer: 64 << 20 });

// ---------------------------------------------------------------- calibrate screen

type Px = [number, number];

/** Where a source pixel lands on screen. The frame is drawn letterbox-free but scaled
 *  (`.wide-app .calib-frame img` is capped by the viewport), so the mapping has to come
 *  from the image's own natural size — not from 1920x1080.
 *
 *  The bounding box is re-read on every call, deliberately: on a narrow viewport taking
 *  the proposal removes the buttons stacked above the frame and slides the image up. */
async function mapper(page: Page) {
  const img = page.getByTestId("calib-image");
  await expect(img).toBeVisible();
  const nat = await img.evaluate((el: HTMLImageElement) => ({
    w: el.naturalWidth,
    h: el.naturalHeight,
  }));
  expect(
    nat.w,
    "D-14: the calibration frame exists before processing",
  ).toBeGreaterThan(0);
  return async (px: Px) => {
    const box = (await img.boundingBox())!;
    return {
      x: box.x + (px[0] / nat.w) * box.width,
      y: box.y + (px[1] / nat.h) * box.height,
    };
  };
}

/** Pick a placed point from the chips under the frame (S-04b-7). */
async function pickPoint(page: Page, name: string) {
  const chip = page.getByTestId(`calib-point-${name}`);
  const box = (await chip.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {
    steps: 15,
  });
  await beat(page, 400);
  await chip.click();
  await expect(page.getByTestId("calib-prompt")).toHaveAttribute(
    "data-target",
    name,
  );
  await beat(page, 700);
}

/** Put a proposed landmark on its true pixel. Dragged when its handle is the one on top
 *  at its own centre — the legible move for the video; the mouse is walked there first
 *  and the drag is stepped. A proposal can pile several points inside one 44 px handle,
 *  and a drag there grabs whichever handle is on top, so then the point is picked from
 *  the chips and placed with a tap instead. */
async function correctLandmark(
  page: Page,
  name: string,
  to: { x: number; y: number },
) {
  const handle = page.getByTestId(`landmark-handle-${name}`);
  if (!(await handle.count())) return;
  const onTop = await handle.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return (
      document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === el
    );
  });
  if (onTop) {
    const from = (await handle.boundingBox())!;
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2, {
      steps: 15,
    });
    await beat(page, 500);
    await page.mouse.down();
    await page.mouse.move(to.x, to.y, { steps: 30 });
    await beat(page, 400);
    await page.mouse.up();
  } else {
    await pickPoint(page, name);
    await page.mouse.move(to.x, to.y, { steps: 20 });
    await beat(page, 300);
    await page.mouse.click(to.x, to.y);
    await expect(page.getByTestId(`calib-point-${name}`)).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  }
  await beat(page, 800);
}

/** Walk the prompt: click the landmarks we have a ground-truth pixel for, and press
 *  "Not visible" for the ones this camera cannot see (the four `corner_*` are off-frame
 *  on this clip — D-19 wants them left out, not guessed at). */
async function walkPrompts(
  page: Page,
  truth: Record<string, Px>,
  at: (px: Px) => Promise<{ x: number; y: number }>,
) {
  for (let guard = 0; guard < 40; guard++) {
    // the landmark id (the prompt itself is in plain words: "Tap the near-left corner")
    const name = await page
      .getByTestId("calib-prompt")
      .getAttribute("data-target");
    if (!name) return; // "All landmarks placed."
    const px = truth[name];
    if (!px) {
      await page.getByTestId("calib-skip").click();
      await beat(page, 550);
      continue;
    }
    const pt = await at(px);
    await page.mouse.move(pt.x, pt.y, { steps: 10 });
    await beat(page, 250);
    await page.mouse.click(pt.x, pt.y);
    await expect(page.getByTestId(`landmark-${name}`)).toBeVisible();
    await beat(page, 550);
  }
}

// ------------------------------------------------------------------------------ TV

/** One Space, then wait for it to land. `PlayerSurface` holds a play request that the
 *  still-settling source rejects and retries it once the element can play (S-13), so a
 *  single press is enough — this used to have to press again. */
async function setPlaying(p: Page, want: boolean) {
  if ((await videoState(p))?.paused === !want) return;
  await p.keyboard.press("Space");
  await expect
    .poll(async () => (await videoState(p))?.paused, { timeout: 15_000 })
    .toBe(!want);
}

// ------------------------------------------------------------------------- ffmpeg

const FONT = [
  "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
].find((f) => fs.existsSync(f));
// The laptop's ffmpeg has only openh264, the box's static build only x264.
const H264 = (() => {
  try {
    return /\blibopenh264\b/.test(sh("ffmpeg", ["-hide_banner", "-encoders"]))
      ? "libopenh264"
      : "libx264";
  } catch {
    return "libx264";
  }
})();
const HAS_DRAWTEXT = (() => {
  try {
    return (
      /\bdrawtext\b/.test(sh("ffmpeg", ["-hide_banner", "-filters"])) && !!FONT
    );
  } catch {
    return false;
  }
})();

/** webm -> constant-30-fps mp4, with the segment caption burnt in when drawtext exists.
 *  H.264 through whichever encoder this ffmpeg build has (`H264`).
 *
 *  `cut` drops one [from, to] window. The only thing it is used for is the D-23 model
 *  wait: `courtcam autocalib --backend template` is a measured 46 s on this frame, and a
 *  three-minute reel cannot spend a quarter of itself on a spinner. A couple of seconds
 *  of it stays in, so the recording does not pretend the wait is not there. */
function encode(
  src: string,
  dst: string,
  caption: string,
  cut?: [number, number],
) {
  const text = caption.replace(/[\\:']/g, (c) => `\\${c}`);
  const tail = HAS_DRAWTEXT
    ? `,drawtext=fontfile=${FONT}:text='${text}':x=48:y=h-104:fontsize=36:fontcolor=white` +
      `:box=1:boxcolor=black@0.6:boxborderw=18`
    : "";
  const graph = cut
    ? `[0:v]trim=0:${cut[0].toFixed(2)},setpts=PTS-STARTPTS[v0];` +
      `[0:v]trim=start=${cut[1].toFixed(2)},setpts=PTS-STARTPTS[v1];` +
      `[v0][v1]concat=n=2:v=1[c];[c]fps=30${tail}[out]`
    : `[0:v]fps=30${tail}[out]`;
  sh("ffmpeg", [
    "-y",
    "-i",
    src,
    "-filter_complex",
    graph,
    "-map",
    "[out]",
    "-an",
    "-c:v",
    H264,
    "-b:v",
    "8M",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    dst,
  ]);
}

// ---------------------------------------------------------------------------- spec

// The project default is `trace: "retain-on-failure"`, which keeps a screenshot and a DOM
// snapshot per action for the whole run. This test is 10-20 minutes long and already
// records two 1080p videos; carrying the trace as well pushed the renderer into an OOM
// crash ("Target crashed") in follow mode on a 16 GB box. The video *is* the artifact.
test.use({ trace: "off" });
test.describe.configure({ mode: "serial" });
test.skip(
  !haveClip(CLIP),
  `samples/real/${CLIP} is gitignored (D-7); nothing to record`,
);
test.skip(
  !haveClip(MARKS),
  `samples/real/${MARKS} is missing; calibrate the clip first`,
);

test("R-07 demo video: phone upload+calibrate, then the TV loop", async ({
  browser,
  baseURL,
  request,
}) => {
  test.setTimeout(2_700_000); // 45 min: a real YOLO pass on the 50 s cut is 4-5 of them
  fs.mkdirSync(OUT, { recursive: true });
  const truth: Record<string, Px> = JSON.parse(
    fs.readFileSync(clip(MARKS), "utf8"),
  ).landmarks_px;

  // ===================================================== A — the phone flow ==========
  const ctxA = await browser.newContext({
    baseURL,
    viewport: SIZE,
    recordVideo: { dir: OUT, size: SIZE },
  });
  const a = await ctxA.newPage();
  const t0 = Date.now();
  const clock = () => (Date.now() - t0) / 1000;
  let spinner: [number, number] | undefined;
  let gameId = "";
  try {
    await a.goto("/upload");
    await expect(a.getByTestId(`sport-option-${SPORT}`)).toBeVisible({
      timeout: 60_000,
    });
    await beat(a, 1200);
    await a.getByTestId("game-title-input").fill(TITLE);
    await beat(a);
    await a.getByTestId(`sport-option-${SPORT}`).check();
    await beat(a, 1100);
    await a.getByTestId("create-game").click();
    await a.waitForURL(/\/upload\/g_[a-z0-9]+/);
    gameId = new URL(a.url()).pathname.split("/")[2];

    await beat(a, 1000);
    await a.getByTestId("file-input").setInputFiles(clip(CLIP));
    await expect(a.getByTestId("upload-done")).toBeVisible({
      timeout: 300_000,
    });
    await beat(a, 1500);
    await a.getByTestId("go-calibrate").click();
    await a.waitForURL(/\/calibrate$/);

    // --- calibrate, part 1: what the model proposes, and dragging it ----------------
    const at = await mapper(a);
    // Only a profile with more than one court variant renders the picker (badminton's
    // doubles/singles may be merged into one); when it is there, doubles is `variants[0]`
    // and therefore already the checked default.
    const doubles = a.getByTestId(`variant-${VARIANT}`);
    if (await doubles.count()) {
      await expect(doubles).toBeChecked();
      await beat(a, 700);
    }

    // D-23: the proposal is queued on page load and polled. Wait for it to settle.
    const status = a.getByTestId("autocalib-status");
    const spinFrom = clock();
    await expect(status).toHaveAttribute("data-state", /done|failed|idle/, {
      timeout: 300_000,
    });
    const spinTo = clock();
    // Keep ~3 s of the spinner, cut the rest out in post (see `encode`).
    if (spinTo - spinFrom > 8) spinner = [spinFrom + 3, spinTo - 0.5];
    await beat(a, 2500); // let the viewer read "Found N points · … · needs a check"

    const adjusted = (await a.getByTestId("autocalib-adjust").count()) > 0;
    if (adjusted) {
      await a.getByTestId("autocalib-adjust").click();
      await expect(status).toHaveAttribute("data-state", "applied");
      await beat(a, 1200);

      // --- calibrate, part 2: correct the proposal in place ---------------------------
      // Every proposed point we have a true pixel for goes onto it (the net posts are
      // the two this camera sees best; the template fit can be ~70 px out here, so these
      // are big, legible moves and `calib-error` changes as they land). The fit also
      // proposes points that are physically off-frame on this clip, `corner_*` among
      // them; D-19 wants those left out, not guessed at, so each is picked from the
      // chips and marked "Not visible".
      const proposed = await a
        .locator('[data-testid^="landmark-handle-"]')
        .evaluateAll((els) =>
          els.map((e) => e.getAttribute("data-testid")!.slice(16)),
        );
      const posts = proposed.filter((n) => n.startsWith("net_post"));
      for (const name of [
        ...posts,
        ...proposed.filter((n) => !posts.includes(n)),
      ]) {
        if (truth[name]) {
          await correctLandmark(a, name, await at(truth[name]));
          continue;
        }
        await pickPoint(a, name);
        await a.getByTestId("calib-skip").click();
        await expect(a.getByTestId(`landmark-${name}`)).toHaveCount(0);
        await beat(a, 900);
      }
    } else {
      // No proposal to correct: "Place points myself" is the whole walk.
      await a.getByTestId("autocalib-manual").click();
      await expect(status).toHaveAttribute("data-state", "manual");
      await beat(a, 1200);
    }

    // Whatever the proposal left out: clicked when we have a true pixel, else
    // "Not visible". After a manual start this is the whole required walk.
    await walkPrompts(a, truth, at);
    await beat(a, 1000);

    // Optional: the short-service, centre and singles points that give the lens model
    // the eight landmarks it needs (samples/real/RESULTS.md).
    if (await a.getByTestId("calib-more").count()) {
      await a.getByTestId("calib-more").click();
      await beat(a, 900);
      await walkPrompts(a, truth, at);
    }

    await expect(a.getByTestId("calib-error")).toHaveAttribute(
      "data-ok",
      "true",
      {
        timeout: 30_000,
      },
    );
    await expect(a.getByTestId("calib-worst")).toBeVisible();
    console.log(
      "R-07 calibration:",
      await a.getByTestId("calib-error").textContent(),
      "·",
      await a.getByTestId("calib-worst").textContent(),
    );
    await beat(a, 3000);

    await a.getByTestId("start-processing").click();
    await a.waitForURL(/\/status$/);
    await expect(a.getByTestId("game-status")).toHaveText(
      /processing|queued|ready/,
    );
    await beat(a, 10_000); // ~10 s of the stage list with `ingest` running
  } finally {
    await ctxA.close();
  }
  const webmA = await a.video()!.path();

  // ============================================ wait out the pipeline, unrecorded ====
  // Swallowing the error is the point: uvicorn runs the pipeline on a worker thread and
  // resets the odd keep-alive connection while YOLO has the GIL. `expect.poll` fails the
  // whole test on a throw, so one ECONNRESET 4 minutes in would burn the entire run.
  await expect
    .poll(
      async () => {
        try {
          const r = await request.get(`${API}/games/${gameId}`, {
            timeout: 15_000,
          });
          return ((await r.json()) as { status: string }).status;
        } catch {
          return "unreachable";
        }
      },
      { timeout: 2_100_000, intervals: [5000] },
    )
    .toBe("ready");

  // ======================================================== B — the TV flow ==========
  const ctxB = await browser.newContext({
    baseURL,
    viewport: SIZE,
    recordVideo: { dir: OUT, size: SIZE },
  });
  const b = await ctxB.newPage();
  try {
    await b.goto("/tv");
    const card = b.locator(`[data-testid=game-card][data-game-id="${gameId}"]`);
    await expect(card).toBeVisible({ timeout: 30_000 });
    await expect(card.getByTestId("game-status")).toHaveText(/ready|Ready/i);
    await beat(b, 1500);

    // D-1: the library is keyboard only. Arrow onto our card, then Enter.
    const cards = b.getByTestId("game-card");
    const want = await cards.evaluateAll(
      (els, id) => els.findIndex((e) => e.getAttribute("data-game-id") === id),
      gameId,
    );
    for (let i = 0; i < Math.max(0, want); i++) {
      await b.keyboard.press("ArrowRight");
      await beat(b, 450);
    }
    await expect(card).toHaveAttribute("data-focused", "true");
    await beat(b, 800);
    await b.keyboard.press("Enter");
    await b.waitForURL(new RegExp(`/tv/${gameId}$`));

    // --- wide -> select ------------------------------------------------------------
    await waitForVideo(b);
    await beat(b, 900);
    await setPlaying(b, true);
    await beat(b, 4000);
    await setPlaying(b, false); // pause -> select mode
    const boxes = b.locator('[data-testid^="select-box-"]');
    await expect(boxes.first()).toBeVisible({ timeout: 30_000 });
    await expect(b.getByTestId("court-inset")).toBeVisible();
    console.log("R-07 select boxes:", await boxes.count());
    await beat(b, 2500);

    // --- spotlight (W6) ------------------------------------------------------------
    // Ordered here, not after Escape: `SelectOverlay` — and with it the spotlight
    // cutout — is only mounted in select and follow mode, so `s` in the wide shot has
    // nothing to dim.
    await b.keyboard.press("s");
    await expect(b.getByTestId("spotlight-overlay")).toBeVisible();
    await beat(b, 3000);
    await b.keyboard.press("s");
    await expect(b.getByTestId("spotlight-overlay")).toHaveCount(0);
    await beat(b, 1200);

    for (let i = 0; i < 2; i++) {
      await b.keyboard.press("ArrowRight");
      await beat(b, 1100);
    }

    // --- follow --------------------------------------------------------------------
    await b.keyboard.press("Enter");
    await expect(b.getByTestId("followcam-active")).toBeVisible();
    await expect(b.getByTestId("follow-frame")).toBeAttached();
    await beat(b, 1500);
    await setPlaying(b, true); // 8 s of follow-cam
    await beat(b, 8000);
    await b.keyboard.press("Escape");
    await expect(b.getByTestId("followcam-active")).toHaveCount(0);
    await expect(b.getByTestId("follow-frame")).toBeAttached(); // W4: the frame persists
    await beat(b, 2500);

    // --- bookmark (H5) -------------------------------------------------------------
    await b.keyboard.press("b");
    await beat(b, 1800);

    // --- highlights ----------------------------------------------------------------
    await b.goto(`/tv/${gameId}/highlights`);
    const chips = b.getByTestId("query-chip");
    await expect(chips.first()).toBeVisible();
    await beat(b, 1500);
    // Walk the chips left to right and stop at the first one that actually has clips.
    // On a 50 s cut the rally detector finds nothing, so "Rallies" alone would show an
    // empty reel; the bookmark dropped a moment ago always gives "Bookmarks" one clip.
    const reel = b.getByTestId("reel-clip");
    const chipCount = await chips.count();
    for (let i = 0; i < chipCount; i++) {
      // the last chip is "Ask…", which opens a text prompt instead of running a query
      if (((await chips.nth(i).textContent()) ?? "").startsWith("Ask")) break;
      await b.keyboard.press("Enter"); // run the focused chip
      await expect(b.getByTestId("query-interpretation")).toBeVisible();
      await beat(b, 1600);
      if (await reel.count()) break;
      if (i < chipCount - 1) {
        await b.keyboard.press("ArrowRight");
        await beat(b, 700);
      }
    }
    if (await reel.count()) {
      await b.keyboard.press("ArrowDown");
      await beat(b, 800);
      await b.keyboard.press("Enter");
      await waitForVideo(b);
      await beat(b, 5000);
      await b.keyboard.press("Escape");
      await beat(b, 900);
    } else {
      // Tier 1: the rally detector is a stub, so an honest "no clips" is the answer.
      console.log(
        "R-07 highlights: no reel clips —",
        await b.getByTestId("query-interpretation").textContent(),
      );
      await beat(b, 2500);
    }

    // --- review --------------------------------------------------------------------
    await b.goto(`/tv/${gameId}/review`);
    await expect(b.getByTestId("heatmap")).toBeVisible({ timeout: 30_000 });
    await beat(b, 2500);
    await b.keyboard.press("ArrowDown"); // row 1 = the heatmap's player picker
    await beat(b, 900);
    for (let i = 0; i < 2; i++) {
      await b.keyboard.press("ArrowRight");
      await beat(b, 1600);
    }
    await beat(b, 2000);
  } finally {
    await ctxB.close();
  }
  const webmB = await b.video()!.path();

  // ========================================================= stitch with ffmpeg ======
  const rawA = path.join(OUT, "badminton-demo-a.webm");
  const rawB = path.join(OUT, "badminton-demo-b.webm");
  fs.renameSync(webmA, rawA);
  fs.renameSync(webmB, rawB);

  const mp4A = path.join(OUT, "badminton-demo-a.mp4");
  const mp4B = path.join(OUT, "badminton-demo-b.mp4");
  encode(
    rawA,
    mp4A,
    "1 — Phone: upload, auto-calibrate, correct, process",
    spinner,
  );
  encode(rawB, mp4B, "2 — TV: select, follow, spotlight, highlights, review");

  const list = path.join(OUT, "concat.txt");
  fs.writeFileSync(
    list,
    [mp4A, mp4B].map((f) => `file '${f}'`).join("\n") + "\n",
  );
  sh("ffmpeg", [
    "-y",
    "-f",
    "concat",
    "-safe",
    "0",
    "-i",
    list,
    "-c",
    "copy",
    "-movflags",
    "+faststart",
    MP4,
  ]);
  fs.rmSync(list, { force: true });

  expect(fs.existsSync(MP4), `${MP4} must exist`).toBe(true);
  const probe = JSON.parse(
    sh("ffprobe", [
      "-v",
      "error",
      "-select_streams",
      "v:0",
      "-show_entries",
      "stream=width,height,avg_frame_rate:format=duration,size",
      "-of",
      "json",
      MP4,
    ]),
  );
  const seconds = Number(probe.format.duration);
  console.log("R-07 demo video:", MP4, JSON.stringify(probe));
  expect(probe.streams[0].width).toBe(SIZE.width);
  expect(probe.streams[0].height).toBe(SIZE.height);
  expect(seconds, "the reel should be minutes, not seconds").toBeGreaterThan(
    60,
  );

  // Six evenly spaced stills, for eyeballing that each segment shows what it should.
  fs.rmSync(FRAMES, { recursive: true, force: true });
  fs.mkdirSync(FRAMES, { recursive: true });
  for (let i = 1; i <= 6; i++) {
    const t = (seconds * i) / 7;
    sh("ffmpeg", [
      "-y",
      "-ss",
      t.toFixed(2),
      "-i",
      MP4,
      "-frames:v",
      "1",
      path.join(FRAMES, `f${i}.png`),
    ]);
  }
});
