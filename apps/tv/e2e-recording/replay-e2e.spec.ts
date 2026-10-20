// Recorded end-to-end run (opt-in project `recording`, scripts/record-e2e.sh) of the
// redesigned TV app (D-81, docs/ux/redesign.md): the TV web build and a phone browser, two
// browser contexts, against the real services/api with REPLAY_PIPELINE=worker on hfbox.
// Nothing is mocked. The footage is SYNTHETIC: a short `courtcam synth` clip uploaded
// through the phone page the TV's QR code opens, and the `make demo` games.
//
// The phone never types an address: it opens only the URLs the TV's QR codes encode (Add
// game's `/u/<id>#t=`, On your phone's `/p/<id>?job=..#k=`). Each QR code drawn on the TV is
// checked module for module against an independent encoding of the URL the API returned.
//
// Every beat asserts what the viewer should see. A beat that fails is recorded as failed
// (with the first line of the error) and the run moves on to the next beat, so one broken
// screen does not hide the rest; the test still fails at the end. beats.json (times are
// seconds since the TV video started) drives the captions and cuts in
// scripts/record_e2e_compose.py.
//
//   REPLAY_REC_API       the API base (also baked into both web builds)
//   REPLAY_REC_TV        the TV web build (also the project's baseURL)
//   REPLAY_REC_PHONE     the phone pages (apps/web), the API's REPLAY_PUBLIC_WEB_BASE
//   REPLAY_REC_CLIP      the synthetic clip to upload
//   REPLAY_REC_LANDMARKS its landmarks.json from `courtcam synth` (the hand-placed points)
//   REPLAY_REC_OUT       where beats.json, the phone video and the key frames go
import { expect, test, type Locator, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import qrcode from "qrcode-generator";
import { menuTo } from "../e2e/helpers";

const env = (k: string) => process.env[k] ?? "";
const API = env("REPLAY_REC_API");
const PHONE = env("REPLAY_REC_PHONE");
const CLIP = env("REPLAY_REC_CLIP");
const LANDMARKS = env("REPLAY_REC_LANDMARKS");
const OUT = env("REPLAY_REC_OUT") || "test-results/recording";
const SPORT = "basketball";
const BB = "g_demo_basketball";
const PB = "g_demo_pickleball";
const TAG_NAME = "Riley";
const DWELL = 2000; // after each beat, so a viewer can read the screen

interface Beat {
  name: string;
  caption: string;
  start: number;
  end: number;
  ok: boolean;
  /** what the beat found (the caption's second line) */
  detail?: string;
  error?: string;
  /** the error's first lines, for debugging a failed beat */
  log?: string;
}
interface Moment {
  id: string;
  t: number;
  t_start: number;
  t_end: number;
  kind: string;
  label: string;
  thumb_url: string | null;
}

function byId(ms: Moment[], id: string | null | undefined): Moment {
  const m = ms.find((x) => x.id === id);
  if (!m) throw new Error(`no moment ${id} in GET /moments`);
  return m;
}

const T0 = { tv: 0, phone: 0 };
const beats: Beat[] = [];
const cuts: { from: number; to: number; note: string }[] = [];
const now = () => (Date.now() - T0.tv) / 1000;
const videos: Record<string, string> = {};

function save() {
  fs.mkdirSync(OUT, { recursive: true });
  const phoneOffset = (T0.phone - T0.tv) / 1000;
  fs.writeFileSync(
    path.join(OUT, "beats.json"),
    JSON.stringify(
      { phone_offset_s: phoneOffset, beats, cuts, videos },
      null,
      2,
    ),
  );
}

/** `fn` may return a caption that says what the beat found. */
async function beat(
  page: Page,
  name: string,
  caption: string,
  fn: () => Promise<void | string>,
) {
  const b: Beat = { name, caption, start: now(), end: 0, ok: true };
  try {
    b.detail = (await test.step(name, fn)) || "";
  } catch (e) {
    b.ok = false;
    const lines = String((e as Error).message ?? e)
      .replace(new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g"), "") // ANSI colours
      .split("\n")
      .filter(Boolean);
    b.error = lines.slice(0, 2).join(" | ");
    b.log = lines.slice(0, 12).join("\n");
    await keyFrame(page, `FAIL_${name.replace(/\W+/g, "_")}`).catch(() => {});
  }
  await page.waitForTimeout(DWELL).catch(() => {});
  b.end = now();
  beats.push(b);
  save();
}

async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v
      ? {
          t: v.currentTime,
          paused: v.paused,
          ready: v.readyState,
          src: v.currentSrc,
        }
      : { t: -1, paused: true, ready: 0, src: "" };
  });
}

async function videoReady(page: Page) {
  await expect(page.getByTestId("video")).toBeAttached({ timeout: 20_000 });
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(2);
}

const playing = (page: Page) =>
  expect
    .poll(async () => (await media(page)).paused, { timeout: 10_000 })
    .toBe(false);

let shots = 0;
/** A full-resolution key frame of the TV, for checking the recording by eye. */
async function keyFrame(page: Page, name: string) {
  fs.mkdirSync(path.join(OUT, "frames"), { recursive: true });
  const file = `${String(++shots).padStart(2, "0")}_${name}.jpg`;
  await page.screenshot({
    path: path.join(OUT, "frames", file),
    type: "jpeg",
    quality: 88,
  });
}

const mmss = (s: number) =>
  `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const focused = (l: Locator) =>
  l.getAttribute("data-focused").then((f) => f === "true");

/** Back until Home is on screen (the player peels its layers one per press). */
async function toHome(page: Page) {
  for (let i = 0; i < 6 && !(await page.getByTestId("home").count()); i++) {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
  }
  await expect(page.getByTestId("home")).toBeVisible();
}

/** Home's Games row: Left/Right until card `id` (or Add game) has the focus ring. */
async function focusCard(page: Page, id: string | "add") {
  const el =
    id === "add"
      ? page.getByTestId("library-add")
      : page.locator(`[data-testid="game-card"][data-game-id="${id}"]`);
  await expect(el).toBeVisible({ timeout: 20_000 });
  for (const key of ["ArrowLeft", "ArrowRight"])
    for (let i = 0; i < 8 && !(await focused(el)); i++) {
      await page.keyboard.press(key);
      await page.waitForTimeout(350);
    }
  await expect(el).toHaveAttribute("data-focused", "true");
}

/** From the focused card: Up to the hero's ways to watch, then Right to `hero-<action>`. */
async function heroTo(page: Page, action: string) {
  await page.keyboard.press("ArrowUp");
  const el = page.getByTestId(`hero-${action}`);
  await expect(el).toBeVisible();
  for (let i = 0; i < 4 && !(await focused(el)); i++) {
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(350);
  }
  await expect(el).toHaveAttribute("data-focused", "true");
}

/** Open Do more with Up (the remote's grammar), then walk to tile `id`. */
async function doMore(page: Page, id: string) {
  if (!(await page.getByTestId("domore").count())) {
    await page.keyboard.press("ArrowUp");
    await page.waitForTimeout(600);
  }
  await menuTo(page, id);
  await page.waitForTimeout(700);
}

async function apiGet<T>(page: Page, p: string): Promise<T> {
  const res = await page.request.get(`${API}${p}`);
  expect(res.ok(), `GET ${p}`).toBe(true);
  return (await res.json()) as T;
}

/** The QR code drawn in `qr` (the element carrying data-cell) has exactly the dark modules
 *  of `text` encoded independently here (qrcode-generator, level M). */
async function expectQr(qr: Locator, text: string) {
  const code = qrcode(0, "M");
  code.addData(text);
  code.make();
  const n = code.getModuleCount();
  const want: string[] = [];
  for (let r = 0; r < n; r++)
    for (let c = 0; c < n; c++) {
      if (!code.isDark(r, c)) continue;
      const last = want.length
        ? want[want.length - 1].split(",").map(Number)
        : null;
      if (last && last[0] === r && last[1] + last[2] === c)
        want[want.length - 1] = `${r},${last[1]},${last[2] + 1}`;
      else want.push(`${r},${c},1`);
    }
  const got = await qr.evaluate((el) => {
    const box = el.getBoundingClientRect();
    const cell = Number(el.getAttribute("data-cell"));
    return [...el.children].map((k) => {
      const b = k.getBoundingClientRect();
      const [y, x, w] = [
        (b.top - box.top) / cell,
        (b.left - box.left) / cell,
        b.width / cell,
      ];
      return `${Math.round(y) - 4},${Math.round(x) - 4},${Math.round(w)}`;
    });
  });
  expect(got.sort(), "QR modules").toEqual(want.sort());
}

test("Replay end to end: QR upload → worker pipeline → the redesigned TV player → phone handoff", async ({
  page,
  browser,
}) => {
  test.setTimeout(75 * 60_000);
  for (const [k, v] of Object.entries({ API, PHONE, CLIP, LANDMARKS }))
    expect(v, `REPLAY_REC_${k}`).not.toBe("");
  T0.tv = Date.now();
  const phoneCtx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    hasTouch: true,
    recordVideo: {
      dir: path.join(OUT, "phone"),
      size: { width: 390, height: 844 },
    },
  });
  phoneCtx.setDefaultTimeout(20_000); // the project's actionTimeout covers only `page`
  const phone = await phoneCtx.newPage();
  T0.phone = Date.now();
  // Nothing of the product: the phone pane is idle until it opens a QR code's URL.
  await phone.setContent(
    `<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#222;color:#999;font:20px sans-serif;text-align:center">phone idle:<br>no page open yet</body>`,
  );
  await page.goto("/");
  await expect(
    page.locator('[data-testid="game-card"][data-focused="true"]'),
  ).toBeVisible({
    timeout: 30_000,
  });
  await page.waitForTimeout(2500);

  // ------------------------------------------------------------------ Home + Settings
  await beat(
    page,
    "Home + Settings",
    "Home: the immersive hero follows the focused game; Up to the gear → Settings → Test connection",
    async () => {
      const hero = page.getByTestId("hero");
      const games = await page.getByTestId("game-card").count();
      expect(games).toBeGreaterThanOrEqual(2);
      // Right along the Games row: the hero (title + art) follows the focus.
      const titles = new Set<string>();
      for (const id of [PB, BB]) {
        await focusCard(page, id);
        await expect(hero).toHaveAttribute("data-game-id", id);
        titles.add((await page.getByTestId("hero-title").textContent()) ?? "");
        await page.waitForTimeout(1200);
      }
      expect(titles.size).toBe(2);
      await expect(page.getByTestId("hero-play")).toBeVisible();
      await keyFrame(page, "home");
      const gear = page.getByTestId("library-settings");
      for (let i = 0; i < 3 && !(await focused(gear)); i++) {
        await page.keyboard.press("ArrowUp");
        await page.waitForTimeout(400);
      }
      await expect(gear).toHaveAttribute("data-focused", "true");
      await page.waitForTimeout(800);
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("settings-api-base")).toHaveText(API);
      await expect(page.getByTestId("settings-item-2")).toHaveAttribute(
        "data-focused",
        "true",
      );
      await page.waitForTimeout(1000);
      await page.keyboard.press("Enter"); // Test connection
      const check = page.getByTestId("settings-check");
      await expect(check).toHaveAttribute("data-state", "ok", {
        timeout: 10_000,
      });
      await expect(check).toHaveText(/^Connected · \d+ games?$/);
      const said = (await check.textContent()) ?? "";
      await page.waitForTimeout(2000);
      await page.keyboard.press("ArrowDown"); // Done
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("home")).toBeVisible();
      return `Home: the hero follows the focused game (${games} games); Settings → Test connection → “${said}”`;
    },
  );

  // ------------------------------------------------------------------ Add game (QR upload)
  let gameId = "";
  let uploadUrl = "";
  await beat(
    page,
    "Add game: sport → QR",
    "Add game: pick the sport; the TV creates the game and shows the QR code of its phone upload page",
    async () => {
      await focusCard(page, "add");
      await page.waitForTimeout(800);
      await page.keyboard.press("Enter");
      const tile = page.getByTestId(`add-sport-${SPORT}`);
      await expect(tile).toBeVisible();
      for (const key of ["ArrowRight", "ArrowLeft"])
        for (let i = 0; i < 6 && !(await focused(tile)); i++) {
          await page.keyboard.press(key);
          await page.waitForTimeout(350);
        }
      await expect(tile).toHaveAttribute("data-focused", "true");
      await page.waitForTimeout(1000);
      const created = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          new URL(r.url()).pathname === "/games",
      );
      await page.keyboard.press("Enter");
      const body = (await (await created).json()) as {
        id: string;
        upload_page_url?: string;
      };
      gameId = body.id;
      uploadUrl = body.upload_page_url ?? "";
      expect(uploadUrl).toMatch(
        new RegExp(`^${PHONE}/u/${gameId}#t=[\\w.-]{20,}$`),
      );
      await expect(page.getByTestId("add-qr")).toBeVisible();
      await expectQr(page.getByTestId("add-qr"), uploadUrl);
      const shown = uploadUrl.replace(/^https?:\/\//, "").split("#")[0];
      await expect(page.getByTestId("add-url")).toHaveText(shown);
      await expect(page.locator("body")).not.toContainText("#t=");
      const status = page.getByTestId("add-status");
      await expect(status).toHaveAttribute("data-status", "created");
      await expect(status).toContainText("Waiting for your phone");
      await page.waitForTimeout(2500);
      await keyFrame(page, "add_qr");
      return `Add game: Basketball → ${gameId}; the QR encodes ${shown}#t=… (token only in the QR) · “Waiting for your phone”`;
    },
  );

  await beat(
    phone,
    "Phone: open the QR link + upload",
    "Phone: opens the QR code's URL and uploads a 20 s SYNTHETIC clip; the TV follows",
    async () => {
      expect(uploadUrl).not.toBe("");
      await phone.goto(uploadUrl);
      await expect(phone.getByTestId("qr-upload")).toBeVisible();
      await phone.waitForTimeout(1500);
      await phone.getByTestId("file-input").setInputFiles(CLIP);
      await expect
        .poll(() => new URL(phone.url()).pathname, { timeout: 120_000 })
        .toBe(`/u/${gameId}/calibrate`);
      const status = page.getByTestId("add-status");
      await expect(status).toHaveAttribute("data-status", "uploaded", {
        timeout: 15_000,
      });
      await expect(status).toContainText("Calibrating on the phone");
      await expect(phone.getByTestId("calib-image")).toBeVisible({
        timeout: 30_000,
      });
      return `Phone: ${PHONE.replace(/^https?:\/\//, "")}/u/${gameId} → 20 s SYNTHETIC clip uploaded · TV: “${(await status.textContent())?.trim()}”`;
    },
  );

  await beat(
    phone,
    "Phone: calibrate",
    "Phone: auto-calibration proposes the court landmarks",
    async () => {
      // D-72: an ok proposal is accepted as-is; a low-confidence one needs a hand (here the
      // manual walk, clicked at the clip's own landmark pixels). Never the override box.
      const marks = JSON.parse(fs.readFileSync(LANDMARKS, "utf8"));
      const variant = (marks.variant as string | undefined) ?? "half";
      if (await phone.getByTestId(`variant-${variant}`).count())
        await phone.getByTestId(`variant-${variant}`).check();
      await expect(phone.getByTestId("autocalib-status")).not.toHaveText(/^$/, {
        timeout: 60_000,
      });
      await expect(phone.getByTestId("autocalib-busy")).toHaveCount(0, {
        timeout: 180_000,
      });
      await phone.waitForTimeout(2000);
      const accept = phone.getByTestId("autocalib-accept");
      const proposed =
        (await phone.getByTestId("autocalib-status").textContent()) ?? "";
      let said = "Phone: auto-calibration proposal accepted (ok)";
      if ((await accept.count()) && (await accept.isEnabled())) {
        await accept.click();
      } else {
        if (!(await phone.getByTestId("autocalib-weak").count()))
          throw new Error(`no usable proposal and no D-72 note: ${proposed}`);
        await expect(accept).toBeDisabled(); // D-72 refusal on screen
        said = `Phone: auto-calibration “${proposed}” refused (D-72, Accept disabled) → landmarks placed by hand`;
        await phone.waitForTimeout(2500);
        await phone.getByTestId("autocalib-manual").click();
        const truth = marks.landmarks_px as Record<string, [number, number]>;
        const sports: { id: string; landmarks?: string[] }[] = await (
          await phone.request.get(`${API}/sports`)
        ).json();
        const order = sports.find((s) => s.id === SPORT)?.landmarks ?? [];
        const img = phone.getByTestId("calib-image");
        const frame = await img.evaluate((el: HTMLImageElement) => ({
          w: el.naturalWidth,
          h: el.naturalHeight,
        }));
        for (const name of order) {
          await expect(phone.getByTestId("calib-prompt")).toContainText(
            name.replace(/_/g, " "),
          );
          const box = await img.boundingBox();
          if (!box) throw new Error("the calibration frame has no box");
          if (!truth[name]) {
            await phone.getByTestId("calib-skip").click();
            continue;
          }
          const [x, y] = truth[name];
          await phone.mouse.click(
            box.x + (x / frame.w) * box.width,
            box.y + (y / frame.h) * box.height,
          );
          await phone.waitForTimeout(450);
        }
      }
      await expect(phone.getByTestId("calib-error")).toHaveAttribute(
        "data-ok",
        "true",
      );
      await phone.getByTestId("start-processing").scrollIntoViewIfNeeded();
      await expect(phone.getByTestId("start-processing")).toBeEnabled();
      return said;
    },
  );

  const processing =
    "Phone: start processing — the real worker pipeline runs on hfbox; the TV shows the stage";
  await beat(page, "Process → the TV opens the game", processing, async () => {
    await phone.getByTestId("start-processing").click();
    const started = now();
    await phone.waitForURL(new RegExp(`/u/${gameId}/status`));
    const status = page.getByTestId("add-status");
    await expect(status).toHaveAttribute("data-status", "processing", {
      timeout: 60_000,
    });
    await expect(status).toHaveText("Processing. It's on Home.");
    const stage = page.getByTestId("add-stage");
    await expect(stage).toHaveText(
      /^[A-Z][a-z ]+, (about \d+ min|under a minute|\d+%)$/,
    );
    await expect(page.getByTestId("add-progress")).toBeVisible();
    const words = (await stage.textContent()) ?? "";
    await keyFrame(page, "add_processing");
    const waitFrom = now() + 8;
    // Ready: the TV leaves Add game for the player by itself.
    await expect(page.getByTestId("video")).toBeAttached({
      timeout: 40 * 60_000,
    });
    const waitTo = now() - 2;
    const took = now() - started;
    const m = (s: number) =>
      `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
    if (waitTo - waitFrom > 15)
      cuts.push({
        from: waitFrom,
        to: waitTo,
        note: `processing took ${m(took)} (real elapsed); ${m(waitTo - waitFrom)} of waiting cut`,
      });
    await expect(page.getByTestId("add-game")).toHaveCount(0);
    await expect(phone.getByTestId("game-status")).toHaveText("ready", {
      timeout: 15_000,
    });
    await videoReady(page);
    await playing(page);
    await expect
      .poll(async () => (await media(page)).t, { timeout: 10_000 })
      .toBeGreaterThan(2);
    await keyFrame(page, "upload_plays");
    return `TV: “${words}” while the worker runs → ready after ${m(took)} → the TV opens the uploaded game and plays it`;
  });

  await demoBeats(page, phone);

  // ------------------------------------------------------------------ wrap up
  await phoneCtx.close(); // flushes the phone video
  videos.phone = (await phone.video()?.path()) ?? "";
  videos.tv = test.info().outputPath("video.webm"); // where `video: on` saves it after the test
  save();
  expect(
    beats.filter((b) => !b.ok).map((b) => `${b.name}: ${b.error}`),
  ).toEqual([]);
});

// -------------------------------------------------------------------- the player
async function demoBeats(page: Page, phone: Page) {
  const bbMoments = (): Promise<Moment[]> =>
    apiGet(page, `/games/${BB}/moments`);
  const near = (ms: Moment[], t: number, tol = 0.6) =>
    ms.find((m) => Math.abs(m.t_start - t) < tol);

  await beat(
    page,
    "Player: transport + court-line timeline",
    "Player: Home → the basketball demo → Play; title, times and the court-line timeline with moment notches",
    async () => {
      await toHome(page);
      await focusCard(page, BB);
      await page.waitForTimeout(1000);
      await heroTo(page, "play");
      await page.waitForTimeout(800);
      await page.keyboard.press("Enter");
      await videoReady(page);
      await playing(page);
      const ms = await bbMoments();
      expect(ms.length).toBeGreaterThan(1);
      await expect(page.getByTestId("transport")).toHaveAttribute(
        "data-hidden",
        "false",
      );
      await expect(page.getByTestId("watch-title")).toHaveText(
        "SYNTHETIC basketball (demo)",
      );
      await expect(page.getByTestId("timeline")).toBeVisible();
      await expect(page.getByTestId("time-elapsed")).toBeVisible();
      await expect(page.getByTestId("time-remaining")).toBeVisible();
      await expect(page.getByTestId("moment-notch")).toHaveCount(ms.length);
      await page.waitForTimeout(1500);
      await keyFrame(page, "transport");
      return `Player: the basketball demo plays; court-line timeline with ${ms.length} moment notches (= GET /moments)`;
    },
  );

  await beat(
    page,
    "Tap seek: preview snaps to a moment",
    "Right taps seek 10 s with a storyboard preview; near a moment it snaps and names it",
    async () => {
      const ms = await bbMoments();
      const preview = page.getByTestId("seek-preview");
      for (let i = 0; i < 6; i++) {
        await page.keyboard.press("ArrowRight");
        await expect(preview).toBeVisible();
        expect((await media(page)).paused).toBe(true); // paused while seeking
        const id = await preview.getAttribute("data-snapped");
        if (id) {
          // snapped: the moment's own frame (the moments stage's thumb), named
          const m = byId(ms, id);
          await expect(page.getByTestId("seek-label")).toHaveText(m.label);
          await expect(preview).toHaveAttribute("data-t", m.t.toFixed(1));
          expect(m.thumb_url).toContain("/moments/");
          await expect(preview.locator("img")).toHaveAttribute(
            "src",
            m.thumb_url ?? "",
          );
          await keyFrame(page, "seek_snap");
          await expect(preview).toHaveCount(0, { timeout: 5_000 });
          await playing(page);
          const t = (await media(page)).t;
          expect(t).toBeGreaterThanOrEqual(m.t_start - 0.1);
          expect(t).toBeLessThan(m.t + 1.5);
          return `Right tap → the storyboard preview snapped to “${m.label}” at ${mmss(m.t)}; playback resumed at its start`;
        }
        // not near a moment: the storyboard sprite's cell for that time, +0:10
        expect(await preview.getAttribute("data-sheet")).toContain(
          "/storyboard/",
        );
        await expect(page.getByTestId("seek-readout")).toHaveText(/^\+0:1\d$/);
        await expect(preview).toHaveCount(0, { timeout: 5_000 });
        await page.waitForTimeout(800);
      }
      throw new Error("no tap landed within 3 s of a moment");
    },
  );

  await beat(
    page,
    "Hold-seek acceleration",
    "Holding Left accelerates: 10 s steps, then 30 s after 1 s held; release resumes there",
    async () => {
      const preview = page.getByTestId("seek-preview");
      const steps: string[] = [];
      await page.keyboard.down("ArrowLeft");
      const t0 = Date.now();
      // Remote-style key repeats every 300 ms; read the step before and after the 1 s tier.
      for (const at of [500, 1500, 2100]) {
        while (Date.now() - t0 < at) {
          await page.waitForTimeout(300);
          await page.keyboard.down("ArrowLeft");
        }
        steps.push((await preview.getAttribute("data-step")) ?? "");
        if (at === 1500) await keyFrame(page, "hold_seek");
      }
      expect((await media(page)).paused).toBe(true);
      const readout =
        (await page.getByTestId("seek-readout").textContent()) ?? "";
      await page.keyboard.up("ArrowLeft");
      expect(steps.slice(0, 2)).toEqual(["10", "30"]);
      await expect(preview).toHaveCount(0, { timeout: 5_000 });
      await playing(page);
      return `Hold Left: step ${steps.join(" → ")} s (readout ${readout}); released → playing from ${mmss((await media(page)).t)}`;
    },
  );

  await beat(
    page,
    "FF scrub ×8 + Prev/Next moment",
    "Fast-forward ×3 scrubs at ×8, Select commits; Next / Prev moment jump to moment starts",
    async () => {
      const ms = await bbMoments();
      const preview = page.getByTestId("seek-preview");
      for (let i = 0; i < 3; i++) {
        await page.keyboard.press(".");
        await page.waitForTimeout(500);
      }
      await expect(page.getByTestId("seek-readout")).toHaveText("×8");
      await expect(preview).toHaveAttribute("data-speed", "8");
      const a = Number(await preview.getAttribute("data-t"));
      await page.waitForTimeout(1000);
      const b = Number(await preview.getAttribute("data-t"));
      expect(b - a).toBeGreaterThan(5); // ~8 s of game per second
      await keyFrame(page, "ff_x8");
      await page.keyboard.press("Enter");
      await expect(preview).toHaveCount(0);
      await playing(page);
      expect((await media(page)).t).toBeGreaterThan(b - 0.5);
      await page.waitForTimeout(1500);

      const before = (await media(page)).t;
      await page.keyboard.press("]");
      await expect
        .poll(async () => near(ms, (await media(page)).t)?.id ?? "", {
          timeout: 5_000,
        })
        .not.toBe("");
      const next = byId(ms, near(ms, (await media(page)).t)?.id);
      expect(next.t_start).toBeGreaterThan(before);
      await page.waitForTimeout(2500);
      await page.keyboard.press("[");
      await page.keyboard.press("[");
      await expect
        .poll(async () => near(ms, (await media(page)).t)?.t_start ?? 999, {
          timeout: 5_000,
        })
        .toBeLessThan(next.t_start);
      const prev = byId(ms, near(ms, (await media(page)).t)?.id);
      await page.waitForTimeout(1500);
      return `FF ×8 (${(b - a).toFixed(1)} s of game in 1 s) → Select; Next → “${next.label}” ${mmss(next.t_start)}, Prev → “${prev.label}” ${mmss(prev.t_start)}`;
    },
  );

  await beat(
    page,
    "Moments row",
    "Down: the Moments row — cards cued to the nearest moment, filter chips, walk, jump",
    async () => {
      const ms = await bbMoments();
      await page.keyboard.press("ArrowDown");
      const layer = page.getByTestId("moments-layer");
      await expect(layer).toBeVisible();
      const cards = page.getByTestId("moment-card");
      await expect(cards).toHaveCount(ms.length);
      const card = page.locator(
        '[data-testid="moment-card"][data-focused="true"]',
      );
      await page.waitForTimeout(1200);
      for (let i = 0; i < 2; i++) {
        await page.keyboard.press("ArrowRight");
        await page.waitForTimeout(900);
        const m = byId(ms, await card.getAttribute("data-moment-id"));
        await expect(page.getByTestId("timeline")).toHaveAttribute(
          "data-t",
          m.t.toFixed(1),
        ); // the playhead follows
      }
      const chips = await page.getByTestId("moment-filter").allTextContents();
      expect(chips[0]).toBe(`All ${ms.length}`);
      await keyFrame(page, "moments");
      await page.keyboard.press("ArrowUp"); // to the chips
      await expect(layer).toHaveAttribute("data-zone", "chips");
      await page.waitForTimeout(700);
      await page.keyboard.press("ArrowRight");
      const focusedChip = page.locator(
        '[data-testid="moment-filter"][data-focused="true"]',
      );
      const name = (await focusedChip.textContent()) ?? "";
      const chip = page.locator(
        `[data-testid="moment-filter"][data-filter="${await focusedChip.getAttribute("data-filter")}"]`,
      );
      await page.waitForTimeout(700);
      await page.keyboard.press("Enter"); // filter; the focus goes back to the cards
      await expect(chip).toHaveAttribute("data-active", "true");
      const n = await cards.count();
      expect(n).toBeGreaterThan(0);
      expect(n).toBeLessThan(ms.length);
      await page.waitForTimeout(1500);
      const pick = byId(ms, await card.getAttribute("data-moment-id"));
      await page.keyboard.press("Enter"); // jump there; the row closes
      await expect(layer).toHaveCount(0);
      await expect
        .poll(async () => (await media(page)).t)
        .toBeGreaterThanOrEqual(pick.t_start - 0.05);
      expect((await media(page)).t).toBeLessThan(pick.t + 1);
      await playing(page);
      return `Moments: ${ms.length} cards, the playhead follows the walk; chip “${name}” → ${n} cards; Select → “${pick.label}” at ${mmss(pick.t_start)}`;
    },
  );

  // ------------------------------------------------------------------ ways to watch
  await beat(
    page,
    "Ways to watch: Highlights",
    "Home's hero → Highlights: the top plays back to back (“Highlights, n of N”); Next skips on",
    async () => {
      await toHome(page);
      await focusCard(page, BB);
      await heroTo(page, "highlights");
      await page.waitForTimeout(800);
      await page.keyboard.press("Enter");
      const ind = page.getByTestId("way-indicator");
      await expect(ind).toHaveText(/^Highlights, 1 of \d+$/, {
        timeout: 20_000,
      });
      const total = Number(await ind.getAttribute("data-count"));
      expect(total).toBeGreaterThan(1);
      await videoReady(page);
      await playing(page);
      await keyFrame(page, "highlights");
      // back to back: the reel moves on to the next play by itself
      await expect(ind).toHaveText(`Highlights, 2 of ${total}`, {
        timeout: 30_000,
      });
      if (total < 3)
        return `Highlights: “1 of ${total}” → “2 of ${total}” back to back`;
      await page.waitForTimeout(1500);
      await page.keyboard.press("]"); // Next: skip to the next play
      await expect(ind).toHaveText(`Highlights, 3 of ${total}`);
      await page.waitForTimeout(1500);
      // Prev, and leave mid-reel: the last play runs to the game's end, and a game left
      // there reopens at its end from Home's Play (bug reported with the recording).
      await page.keyboard.press("[");
      await expect(ind).toHaveText(`Highlights, 2 of ${total}`);
      await page.waitForTimeout(1500);
      return `Highlights: “1 of ${total}” → “2 of ${total}” back to back → Next → “3 of ${total}” → Prev → “2 of ${total}”`;
    },
  );

  await beat(
    page,
    "Ways to watch: Condensed",
    "Pickleball demo → Condensed: dead time cut, the rally counter on screen",
    async () => {
      await toHome(page);
      await focusCard(page, PB);
      await heroTo(page, "condensed");
      await page.waitForTimeout(800);
      await page.keyboard.press("Enter");
      await videoReady(page);
      await expect(page.getByTestId("watch")).toHaveAttribute(
        "data-way",
        "condensed",
      );
      await expect
        .poll(async () => (await media(page)).src)
        .toContain("condensed");
      await playing(page);
      const ind = page.getByTestId("way-indicator");
      await expect(ind).toHaveText(/^Condensed, rally \d+ of \d+$/, {
        timeout: 20_000,
      });
      const first = (await ind.textContent()) ?? "";
      const n0 = Number(await ind.getAttribute("data-index"));
      await keyFrame(page, "condensed");
      // the counter follows the cut: the next rally comes up
      await expect
        .poll(async () => Number(await ind.getAttribute("data-index")), {
          timeout: 30_000,
        })
        .toBeGreaterThan(n0);
      await page.waitForTimeout(2000);
      return `Condensed (pickleball doubles demo): “${first}” → “${await ind.textContent()}”`;
    },
  );

  // ------------------------------------------------------------------ Do more (Up)
  await beat(
    page,
    "Do more: Follow player",
    "Up → Do more → Follow player: the roster as chips; pick one → “Following …”; Back stops",
    async () => {
      await toHome(page);
      await focusCard(page, BB);
      // Watched through Highlights to the end: Play starts over (Start over when it resumes)
      await heroTo(
        page,
        (await page.getByTestId("hero-restart").count()) ? "restart" : "play",
      );
      await page.keyboard.press("Enter");
      await videoReady(page);
      await playing(page);
      expect((await media(page)).t).toBeLessThan(3);
      await page.waitForTimeout(1500);
      await doMore(page, "action-follow");
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("domore")).toHaveAttribute(
        "data-row",
        "action-follow",
      );
      const chips = page.locator(
        '[data-testid="domore"] [data-testid^="follow-"]:not([data-testid="follow-pick"])',
      );
      const n = await chips.count();
      expect(n).toBeGreaterThan(1);
      await page.waitForTimeout(1200);
      await page.keyboard.press("ArrowRight");
      await page.waitForTimeout(900);
      const chip = page.locator(
        '[data-testid="domore"] [data-testid^="follow-"]:not([data-testid="follow-pick"])[data-focused="true"]',
      );
      const pid = ((await chip.getAttribute("data-testid")) ?? "").replace(
        /^follow-/,
        "",
      );
      const initials = (await chip.getByTestId("avatar").textContent()) ?? "";
      const name = ((await chip.textContent()) ?? "")
        .replace(initials, "")
        .trim();
      await keyFrame(page, "follow_chips");
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("domore")).toHaveCount(0);
      await expect(page.getByTestId("watch")).toHaveAttribute(
        "data-mode",
        "follow",
      );
      const following = page.getByTestId("followcam-active");
      await expect(following).toHaveAttribute("data-player-id", pid);
      await expect(following).toContainText("Following");
      expect((await media(page)).paused).toBe(false);
      await page.waitForTimeout(5000);
      await keyFrame(page, "following");
      const label = ((await following.textContent()) ?? "").trim();
      await page.keyboard.press("Escape");
      await expect(following).toHaveCount(0);
      await expect(page.getByTestId("watch")).toHaveAttribute(
        "data-mode",
        "wide",
      );
      await playing(page);
      return `Follow player: ${n} chips → “${name}” → “${label}” while playing → Back → the wide shot`;
    },
  );

  await beat(
    page,
    "Do more: Angles",
    "Do more → Angles: the nearest play's replay angles play in the player; Right cuts; Back returns at the same time",
    async () => {
      await page.keyboard.press("Space"); // pause: Back must come back to this frame
      await expect.poll(async () => (await media(page)).paused).toBe(true);
      const t0 = (await media(page)).t;
      await doMore(page, "nav-replays");
      const play = (
        (await page.getByTestId("nav-replays").textContent()) ?? ""
      ).replace(/^Angles/, "");
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("domore")).toHaveAttribute(
        "data-row",
        "nav-replays",
      );
      const thumbs = page.locator(
        '[data-testid="domore"] [data-testid^="angle-"]:not([data-testid="angle-free"])',
      );
      const n = await thumbs.count();
      expect(n).toBeGreaterThan(1);
      await page.waitForTimeout(1500);
      await page.keyboard.press("Enter"); // the first angle
      const replay = page.getByTestId("replay");
      await expect(replay).toBeVisible();
      await videoReady(page);
      const tiers = new Set<string>([
        (await page.getByTestId("replay-tier-badge").textContent()) ?? "",
      ]);
      await page.waitForTimeout(2200);
      for (let i = 2; i <= n; i++) {
        await page.keyboard.press("ArrowRight");
        await expect(page.getByTestId("replay-angle-pos")).toHaveText(
          `${i} / ${n}`,
        );
        await videoReady(page);
        const tier =
          (await page.getByTestId("replay-tier-badge").textContent()) ?? "";
        if (!tiers.has(tier))
          await keyFrame(page, `angle_${tier.replace(/\W+/g, "")}`);
        tiers.add(tier);
        await page.waitForTimeout(1100);
      }
      expect([...tiers].sort()).toEqual(["2.5D", "3D", "Real video"]);
      await page.keyboard.press("Escape");
      await expect(page.getByTestId("watch")).toBeVisible();
      await expect
        .poll(async () => Math.abs((await media(page)).t - t0), {
          timeout: 10_000,
        })
        .toBeLessThan(0.15);
      return `Angles of “${play.trim()}”: ${n} angles — ${[...tiers].sort().join(" + ")}; Back → the game at ${mmss(t0)}`;
    },
  );

  // No Free view beat: the demo games have no 2.5D scene packages (the opt-in `scene`
  // stage is not in box-demo.sh's build), so the player offers no Free view tile.

  let reviewN = -1;
  await beat(
    page,
    "Do more: Stats panel",
    "Do more → Stats: box score and shot chart in a side panel while the game plays on",
    async () => {
      await page.keyboard.press("Space"); // play
      await playing(page);
      await doMore(page, "nav-review");
      await page.keyboard.press("Enter");
      const panel = page.getByTestId("stats-panel");
      await expect(panel).toBeVisible();
      await expect(page.getByTestId("watch")).toHaveAttribute(
        "data-layer",
        "stats",
      );
      await expect(page.getByTestId("auto-detected-label")).toContainText(
        "Auto-detected",
      );
      await expect
        .poll(() => page.getByTestId("box-score-row").count(), {
          timeout: 15_000,
        })
        .toBeGreaterThan(0);
      await expect(page.getByTestId("shot-chart")).toBeVisible();
      const t0 = (await media(page)).t;
      await expect
        .poll(async () => (await media(page)).t, { timeout: 5_000 })
        .toBeGreaterThan(t0 + 0.5);
      const review =
        (await page.getByTestId("stats-review").textContent()) ?? "";
      reviewN = Number(review.match(/Review (\d+) play/)?.[1] ?? -1);
      const rows = await page.getByTestId("box-score-row").count();
      await page.waitForTimeout(4000);
      await keyFrame(page, "stats");
      await page.keyboard.press("Escape");
      await expect(panel).toHaveCount(0);
      return `Stats panel: ${rows} box-score rows, the shot chart, “${review}” — the video plays on`;
    },
  );

  await beat(
    page,
    "Do more: Commentary",
    "Do more → Commentary on: the broadcast rendition with grounded commentary captions",
    async () => {
      await doMore(page, "action-captions");
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("action-captions")).toContainText("On");
      await page.waitForTimeout(1000);
      await page.keyboard.press("Escape"); // close Do more: captions show over the bare game
      await expect(page.getByTestId("watch")).toHaveAttribute(
        "data-broadcast",
        "true",
      );
      await expect
        .poll(async () => (await media(page)).src)
        .toContain("broadcast");
      await videoReady(page);
      if ((await media(page)).paused) await page.keyboard.press("Space");
      const cap = page.getByTestId("caption");
      await expect(cap).toBeVisible({ timeout: 30_000 });
      const line = ((await cap.textContent()) ?? "").trim();
      await page.waitForTimeout(6000);
      await keyFrame(page, "commentary");
      await doMore(page, "action-captions"); // off again (follow sits commentary out)
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("action-captions")).toContainText("Off");
      await page.keyboard.press("Escape");
      await expect(page.getByTestId("watch")).toHaveAttribute(
        "data-broadcast",
        "false",
      );
      return `Commentary on: the broadcast rendition plays with captions (“${line.slice(0, 70)}”); off again`;
    },
  );

  // ------------------------------------------------------------------ On your phone
  await beat(
    page,
    "On your phone: Clip",
    "Do more → On your phone: the Clip QR; the phone opens it, trims and saves the clip, then a 9:16 cut",
    async () => {
      await videoReady(page);
      if (!(await media(page)).paused) await page.keyboard.press("Space");
      await expect.poll(async () => (await media(page)).paused).toBe(true);
      await doMore(page, "nav-phone");
      const minted = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" &&
          r.url().endsWith(`/games/${BB}/phone-link`),
      );
      await page.keyboard.press("Enter"); // opening the panel mints the Clip link
      const panel = page.getByTestId("phone-panel");
      await expect(panel).toHaveAttribute("data-job", "clip");
      const link = (await (await minted).json()) as { url: string };
      const qr = page.getByTestId("phone-qr");
      await expect(qr).toHaveAttribute("data-url", link.url);
      expect(link.url).toMatch(
        new RegExp(`^${PHONE}/p/${BB}\\?job=clip&t=[\\d.]+#k=[\\w.-]{20,}$`),
      );
      await expectQr(qr.locator("[data-cell]"), link.url);
      await expect(page.getByTestId("phone-url")).toHaveText(
        `${PHONE.replace(/^https?:\/\//, "")}/p/${BB}`,
      );
      await expect(panel).not.toContainText("#k=");
      await page.waitForTimeout(2000);
      await keyFrame(page, "phone_qr_clip");

      await phone.goto(link.url);
      await expect(phone.getByTestId("phone-title")).toHaveText(
        "SYNTHETIC basketball (demo)",
      );
      await expect(phone.getByTestId("phone-tab-clip")).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(new URL(phone.url()).hash).toBe(""); // the token leaves the address bar
      await expect(phone.getByTestId("clip-start")).toBeVisible();
      const span = async () =>
        `${await phone.getByTestId("clip-start").textContent()}–${await phone.getByTestId("clip-end").textContent()}`;
      const moment = await span();
      await phone.waitForTimeout(1500);
      for (const handle of ["clip-start-earlier", "clip-end-later"]) {
        await phone.getByTestId(handle).click(); // the trim handles: 0.5 s a tap
        await phone.waitForTimeout(600);
      }
      const range = await span();
      expect(range).not.toBe(moment);
      await phone.getByTestId("clip-save").click();
      await expect(phone.getByTestId("clip-note")).toHaveText("Clip saved.", {
        timeout: 15_000,
      });
      const clipId =
        (await phone.getByTestId("clip-note").getAttribute("data-clip-id")) ??
        "";
      const clips = await apiGet<
        { clips?: { id: string }[] } | { id: string }[]
      >(page, `/games/${BB}/clips`);
      const list = Array.isArray(clips) ? clips : (clips.clips ?? []);
      expect(list.map((c) => c.id)).toContain(clipId);
      await phone.waitForTimeout(1500);
      await phone.getByTestId("clip-aspect-tall").click();
      await phone.getByTestId("clip-save").click();
      await expect(phone.getByTestId("clip-link")).toHaveText(
        "Download 9:16 clip",
        { timeout: 240_000 },
      );
      await phone.getByTestId("clip-link").scrollIntoViewIfNeeded();
      await phone.waitForTimeout(1500);
      return `Phone: the Clip QR's link → the moment ${moment}, trimmed to ${range} → “Clip saved.” (${clipId} in GET /clips) → 9:16 cut rendered`;
    },
  );

  let tagged = "";
  await beat(
    phone,
    "On your phone: Tag + Review",
    "Same phone page: Tag a player as a new name-only profile, then answer a review question",
    async () => {
      await phone.getByTestId("phone-tab-tag").click();
      const players = phone.getByTestId("tag-player");
      await expect(players.first()).toBeVisible();
      const target = phone
        .locator('[data-testid="tag-player"][data-name=""]')
        .first();
      tagged = (await target.getAttribute("data-player-id")) ?? "";
      await phone.waitForTimeout(1200);
      await target.click();
      await expect(phone.getByTestId("tag-panel")).toBeVisible();
      await phone
        .getByTestId("tag-new-name")
        .pressSequentially(TAG_NAME, { delay: 90 });
      await phone.getByTestId("tag-new-save").click();
      await expect(phone.getByTestId("tag-note")).toHaveText(
        `Tagged as ${TAG_NAME}.`,
      );
      await expect(
        phone.locator(`[data-testid="tag-player"][data-player-id="${tagged}"]`),
      ).toHaveAttribute("data-name", TAG_NAME);
      await phone.waitForTimeout(2000);

      await phone.getByTestId("phone-tab-review").click();
      const cards = phone.getByTestId("review-card");
      await expect(cards.first()).toBeVisible();
      const before = await cards.count();
      const answer = cards
        .first()
        // an answer that saves in one tap (not "Type a name", which opens a text box)
        .locator(
          '[data-testid^="review-action-"]:not([data-testid="review-action-type-a-name"])',
        )
        .first();
      const said = ((await answer.textContent()) ?? "").trim();
      await phone.waitForTimeout(1500);
      await answer.click();
      await expect(phone.getByTestId("review-note")).toHaveText(/^Saved: /);
      await expect(cards).toHaveCount(before - 1);
      await phone.waitForTimeout(1500);
      return `Phone: ${tagged} tagged as “${TAG_NAME}” (a name-only profile); review answered “${said}” → ${before - 1} left`;
    },
  );

  // ------------------------------------------------------------------ Resume
  let resumeT = -1;
  await beat(
    page,
    "Resume from Home",
    "Back to Home: the hero offers “Resume m:ss”; Select resumes the game at that time",
    async () => {
      await page.keyboard.press("Escape"); // the phone panel
      await expect(page.getByTestId("phone-panel")).toHaveCount(0);
      const t = (await media(page)).t;
      expect((await media(page)).paused).toBe(true);
      await toHome(page);
      await focusCard(page, BB);
      const play = page.getByTestId("hero-play");
      await expect(play).toHaveText(`Resume ${mmss(t)}`);
      expect(
        Math.abs(Number(await play.getAttribute("data-resume")) - t),
      ).toBeLessThan(0.5);
      await expect(page.getByTestId("hero-restart")).toHaveText("Start over");
      await page.waitForTimeout(1200);
      await heroTo(page, "play");
      await keyFrame(page, "resume_hero");
      await page.waitForTimeout(1200);
      await page.keyboard.press("Enter");
      await videoReady(page);
      await playing(page);
      resumeT = (await media(page)).t;
      expect(resumeT).toBeGreaterThanOrEqual(t - 0.2);
      expect(resumeT).toBeLessThan(t + 3);
      return `Home: “Resume ${mmss(t)}” → the game plays on from ${resumeT.toFixed(1)} s`;
    },
  );

  await beat(
    page,
    "TV picks up the phone's edits",
    "The TV shows what the phone did: the tagged name on the follow chip and in the box score, one review question fewer",
    async () => {
      expect(tagged).not.toBe("");
      await doMore(page, "action-follow");
      await page.keyboard.press("Enter");
      const chip = page.getByTestId(`follow-${tagged}`);
      await expect(chip).toContainText(TAG_NAME);
      await menuTo(page, `follow-${tagged}`);
      await page.waitForTimeout(1500);
      await keyFrame(page, "tagged_chip");
      await page.keyboard.press("Escape");
      await doMore(page, "nav-review");
      await page.keyboard.press("Enter");
      const review = page.getByTestId("stats-review");
      await expect(review).toBeVisible();
      expect(reviewN, "the Stats beat's review count").toBeGreaterThan(1);
      await expect(review).toContainText(`Review ${reviewN - 1} play`);
      await expect(
        page.getByTestId("box-score-row").filter({ hasText: TAG_NAME }),
      ).toHaveCount(1);
      await page.waitForTimeout(2500);
      await keyFrame(page, "stats_after");
      return `TV: follow chip and box score say “${TAG_NAME}” for ${tagged}; Stats: “${await review.textContent()}” (was ${reviewN})`;
    },
  );
}
