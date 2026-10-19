// Recorded end-to-end run (opt-in project `recording`, scripts/record-e2e.sh): the TV app's
// web build and the phone companion, two browser contexts, against the real services/api
// with REPLAY_PIPELINE=worker on hfbox. Nothing is mocked. By default the footage is
// SYNTHETIC: a short `courtcam synth` clip uploaded through the phone, and the `make demo`
// games (REAL mode below).
//
// Every beat asserts what the viewer should see. A beat that fails is recorded as failed
// (with the first line of the error) and the run moves on to the next beat, so one broken
// screen does not hide the rest; the test still fails at the end. beats.json (times are
// seconds since the TV video started) drives the captions and cuts in
// scripts/record_e2e_compose.py.
//
//   REPLAY_REC_API       the API base (also baked into both web builds)
//   REPLAY_REC_TV        the TV web build (also the project's baseURL)
//   REPLAY_REC_PHONE     the phone companion (apps/web)
//   REPLAY_REC_CLIP      the synthetic clip to upload
//   REPLAY_REC_LANDMARKS its landmarks.json from `courtcam synth` (manual-walk fallback)
//   REPLAY_REC_OUT       where beats.json, the phone video and the key frames go
//
// REAL mode (REPLAY_REC_REAL=1, `make record-e2e-real`, LOCAL ONLY under D-7/D-76): the clip
// is a cut of a samples/real clip, REPLAY_REC_LANDMARKS its tracked hand-clicked
// landmarks.json, REPLAY_REC_SPORT its sport (basketball | volleyball). The phone always
// places those landmarks by hand (after showing what auto-calibration proposed, and the D-72
// refusal when it is ok=false), the API runs the worker with the opt-in replay + scene
// stages (REPLAY_WORKER_STAGES), and every TV beat uses the uploaded game: watch/follow,
// replay angles, Free view (envelope edges, dolly, presets, play, Back), then the sport's
// own screens. There are no demo games in that run.
//   REPLAY_REC_CLIP_LABEL  how the captions name the clip
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import type { SceneLayout } from "../../../packages/tv-core/src/types";
import { enterSelectMode, menuTo } from "../e2e/helpers";
import { presetState } from "../src/scene/camera";

const env = (k: string) => process.env[k] ?? "";
const API = env("REPLAY_REC_API");
const PHONE = env("REPLAY_REC_PHONE");
const CLIP = env("REPLAY_REC_CLIP");
const LANDMARKS = env("REPLAY_REC_LANDMARKS");
const OUT = env("REPLAY_REC_OUT") || "test-results/recording";
const REAL = env("REPLAY_REC_REAL") === "1";
const SPORT = env("REPLAY_REC_SPORT") || "basketball";
const CLIP_LABEL = env("REPLAY_REC_CLIP_LABEL") || (REAL ? `a REAL ${SPORT} clip` : "a 20 s SYNTHETIC clip");
const BB = "g_demo_basketball";
const PB = "g_demo_pickleball";
const UPLOAD_TITLE = REAL ? `REAL ${SPORT} (local test only)` : "SYNTHETIC upload (recording)";
const DWELL = 2500; // after each beat, so a viewer can read the screen

interface Beat {
  name: string;
  caption: string;
  start: number;
  end: number;
  ok: boolean;
  error?: string;
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
    JSON.stringify({ phone_offset_s: phoneOffset, beats, cuts, videos }, null, 2),
  );
}

/** `fn` may return a caption that says which path the beat took. */
async function beat(page: Page, name: string, caption: string, fn: () => Promise<void | string>) {
  const b: Beat = { name, caption, start: now(), end: 0, ok: true };
  try {
    b.caption = (await test.step(name, fn)) || caption;
  } catch (e) {
    b.ok = false;
    b.error = String((e as Error).message ?? e)
      .replace(new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g"), "") // ANSI colours
      .split("\n")
      .filter(Boolean)
      .slice(0, 2)
      .join(" | ");
  }
  await page.waitForTimeout(DWELL).catch(() => {});
  b.end = now();
  beats.push(b);
  save();
}

async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v ? { t: v.currentTime, paused: v.paused, ready: v.readyState, src: v.currentSrc } : null;
  });
}

async function videoReady(page: Page) {
  await expect(page.getByTestId("video")).toBeAttached({ timeout: 20_000 });
  await expect.poll(async () => (await media(page))?.ready ?? 0, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
}

/** Library: Right along the cards until `id` has the focus ring, then Select. */
async function openFromLibrary(page: Page, id: string) {
  await page.goto("/");
  const card = page.locator(`[data-testid="game-card"][data-game-id="${id}"]`);
  await expect(card).toBeVisible({ timeout: 20_000 });
  for (let i = 0; i < 12 && (await card.getAttribute("data-focused")) !== "true"; i++) {
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(250);
  }
  await expect(card).toHaveAttribute("data-focused", "true");
  await page.waitForTimeout(800);
  await page.keyboard.press("Enter");
  await videoReady(page);
}

/** Walk an on-screen keyboard to each key with the arrows and Select it (TV-16's walk). */
async function typeKeys(page: Page, prefix: string, labels: string[]) {
  const rect = (sel: string) => page.locator(sel).first().evaluate((el) => el.getBoundingClientRect().toJSON());
  for (const label of labels) {
    const target = `[data-testid="${prefix}-key-${label}"]`;
    for (let i = 0; i < 30 && (await page.locator(target).getAttribute("data-focused")) !== "true"; i++) {
      const [from, to] = [await rect(`[data-testid^="${prefix}-key-"][data-focused="true"]`), await rect(target)];
      if (Math.abs(to.top - from.top) > 5) await page.keyboard.press(to.top > from.top ? "ArrowDown" : "ArrowUp");
      else await page.keyboard.press(to.left > from.left ? "ArrowRight" : "ArrowLeft");
      await page.waitForTimeout(120);
    }
    await expect(page.locator(target)).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("Enter");
  }
}

let shots = 0;
/** A full-resolution key frame of the TV (the README's artefact notes are read off these). */
async function keyFrame(page: Page, name: string) {
  fs.mkdirSync(path.join(OUT, "frames"), { recursive: true });
  const file = `${String(++shots).padStart(2, "0")}_${name}.jpg`;
  await page.screenshot({ path: path.join(OUT, "frames", file), type: "jpeg", quality: 88 });
}

const replayAttr = (page: Page, name: string) => page.getByTestId("replay").getAttribute(`data-${name}`);

/** Watch ▸ Replays ▸ the first highlight, on its first angle; returns its play id. */
async function openFirstReplay(page: Page, gameId: string): Promise<string> {
  await page.goto(`/tv/${gameId}`);
  await videoReady(page);
  await menuTo(page, "nav-replays");
  await page.keyboard.press("Enter");
  const card = page.locator('[data-testid="replay-card"][data-focused="true"]');
  await expect(card).toBeVisible({ timeout: 15_000 });
  const play = (await card.getAttribute("data-play-id")) ?? "";
  await page.waitForTimeout(1500);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("replay-angle-pos")).toHaveText(/^1 \/ \d+$/, { timeout: 15_000 });
  await videoReady(page);
  return play;
}

/** Free view: press `key` (one 2.5° / 5 % step each, paced for a viewer) until the envelope
 *  edge `edge` is reported; the presses it took. */
async function pushTo(page: Page, key: string, edge: string, max = 40) {
  for (let i = 0; i < max; i++) {
    if ((await replayAttr(page, "edges"))?.split(" ").includes(edge)) return i;
    await page.keyboard.press(key);
    await page.waitForTimeout(300);
  }
  throw new Error(`${edge} not reached with ${key}`);
}

test("Replay end to end: phone upload → worker pipeline → TV demo beats", async ({ page, browser }) => {
  test.setTimeout(75 * 60_000);
  for (const [k, v] of Object.entries({ API, PHONE, CLIP, LANDMARKS })) expect(v, `REPLAY_REC_${k}`).not.toBe("");
  T0.tv = Date.now();
  const phoneCtx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    hasTouch: true,
    recordVideo: { dir: path.join(OUT, "phone"), size: { width: 390, height: 844 } },
  });
  phoneCtx.setDefaultTimeout(20_000); // the project's actionTimeout covers only `page`
  const phone = await phoneCtx.newPage();
  T0.phone = Date.now();
  await phone.goto(`${PHONE}/upload`);
  await page.goto("/");
  // REAL mode starts on an empty library: the upload will be its only game.
  const library = page.getByTestId("game-card").first().or(page.getByTestId("library-empty"));
  await expect(library).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(2000);

  // ------------------------------------------------------------------ TV settings
  await beat(page, "TV settings: test connection", "TV: Library → Settings → Test connection", async () => {
    if (!REAL) await expect(page.getByTestId("game-card").first()).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("library-settings")).toHaveAttribute("data-focused", "true");
    await page.waitForTimeout(800);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("settings-api-base")).toHaveText(API);
    await expect(page.getByTestId("settings-item-2")).toHaveAttribute("data-focused", "true");
    await page.waitForTimeout(1000);
    await page.keyboard.press("Enter"); // Test connection
    await expect(page.getByTestId("settings-check")).toHaveAttribute("data-state", "ok", { timeout: 10_000 });
    await expect(page.getByTestId("settings-check")).toHaveText(/^Connected · \d+ games?$/);
    await page.waitForTimeout(2000);
    await page.keyboard.press("ArrowRight"); // Done
    await page.keyboard.press("Enter");
    await expect(library).toBeVisible();
  });

  // ------------------------------------------------------------------ phone upload
  let gameId = "";
  await beat(phone, "Phone: create game + upload", `Phone: create a ${SPORT} game and upload ${CLIP_LABEL}`, async () => {
    await expect(phone.getByTestId(`sport-option-${SPORT}`)).toBeVisible({ timeout: 20_000 });
    await phone.getByTestId("game-title-input").fill(UPLOAD_TITLE);
    await phone.getByTestId(`sport-option-${SPORT}`).check();
    await phone.waitForTimeout(1000);
    await phone.getByTestId("create-game").click();
    await phone.waitForURL(/\/upload\/g_[a-z0-9]+/);
    gameId = new URL(phone.url()).pathname.split("/")[2];
    await phone.getByTestId("file-input").setInputFiles(CLIP);
    await expect(phone.getByTestId("upload-done")).toBeVisible({ timeout: 120_000 });
    await phone.waitForTimeout(1000);
    await phone.getByTestId("go-calibrate").click();
    await expect(phone.getByTestId("calib-image")).toBeVisible();
  });

  await beat(phone, "Phone: calibrate", "Phone: auto-calibration proposes the court landmarks", async () => {
    // D-72: an ok proposal is accepted as-is; a low-confidence one needs a hand (here the
    // manual walk, clicked at the clip's own landmark pixels). Never the override box.
    // REAL mode always walks by hand, at the tracked hand-clicked landmarks.
    const marks = JSON.parse(fs.readFileSync(LANDMARKS, "utf8"));
    const variant = (marks.variant as string | undefined) ?? "half"; // the synthetic clip is a half court
    if (await phone.getByTestId(`variant-${variant}`).count()) await phone.getByTestId(`variant-${variant}`).check();
    await expect(phone.getByTestId("autocalib-status")).not.toHaveText(/^$/, { timeout: 60_000 });
    await expect(phone.getByTestId("autocalib-busy")).toHaveCount(0, { timeout: 180_000 });
    await phone.waitForTimeout(2000);
    const accept = phone.getByTestId("autocalib-accept");
    const proposed = (await phone.getByTestId("autocalib-status").textContent()) ?? "";
    let path = "Phone: auto-calibration proposal accepted (ok)";
    if (!REAL && (await accept.count()) && (await accept.isEnabled())) {
      await accept.click();
    } else {
      if (await phone.getByTestId("autocalib-weak").count()) {
        // D-72 refusal on screen: the weak-fit note, Accept disabled until a drag or the confirm
        await expect(accept).toBeDisabled();
        path = `Phone: auto-calibration “${proposed}” refused (D-72, Accept disabled) → landmarks placed by hand`;
      } else if (REAL) {
        path = `Phone: auto-calibration “${proposed}” — not used: the tracked hand-clicked landmarks are placed by hand`;
      } else {
        throw new Error(`no usable proposal and no D-72 note: ${proposed}`);
      }
      await phone.waitForTimeout(3000);
      await phone.getByTestId("autocalib-manual").click();
      const truth = marks.landmarks_px as Record<string, [number, number]>;
      const sports: { id: string; landmarks?: string[]; landmarks_optional?: string[] }[] = await (
        await phone.request.get(`${API}/sports`)
      ).json();
      const profile = sports.find((s) => s.id === SPORT);
      const optional = (profile?.landmarks_optional ?? []).filter((n) => truth[n]);
      if (optional.length) await phone.getByTestId("calib-more").click(); // "More points"
      const order = [...(profile?.landmarks ?? []), ...(optional.length ? (profile?.landmarks_optional ?? []) : [])];
      const img = phone.getByTestId("calib-image");
      const frame = await img.evaluate((el: HTMLImageElement) => ({ w: el.naturalWidth, h: el.naturalHeight }));
      let placed = 0;
      for (const name of order) {
        await expect(phone.getByTestId("calib-prompt")).toContainText(name.replace(/_/g, " "));
        const box = await img.boundingBox();
        if (!box) throw new Error("the calibration frame has no box");
        if (!truth[name]) {
          await phone.getByTestId("calib-skip").click();
          continue;
        }
        const [x, y] = truth[name];
        await phone.mouse.click(box.x + (x / frame.w) * box.width, box.y + (y / frame.h) * box.height);
        placed++;
        await phone.waitForTimeout(500);
      }
      if (REAL) path += ` (${placed} points)`;
    }
    await expect(phone.getByTestId("calib-error")).toHaveAttribute("data-ok", "true");
    if (REAL) path += ` · fit ${(await phone.getByTestId("calib-error").textContent())?.trim()}`;
    await phone.getByTestId("start-processing").scrollIntoViewIfNeeded();
    await expect(phone.getByTestId("start-processing")).toBeEnabled();
    return path;
  });

  const processing = REAL
    ? "Phone: start processing — the real worker pipeline (YOLO, + replays and 2.5D scene stages) on hfbox"
    : "Phone: start processing — the real worker pipeline runs on hfbox";
  await beat(phone, "Phone: process (real worker pipeline)", processing, async () => {
    await phone.getByTestId("start-processing").click();
    const started = now();
    await phone.waitForURL(new RegExp(`/upload/${gameId}/status`));
    await expect(phone.locator('[data-testid^="stage-"][data-state="running"]').first()).toBeVisible({ timeout: 120_000 });
    const waitFrom = now() + 10;
    await expect(phone.getByTestId("game-status")).toHaveText(/^(ready|failed)$/, { timeout: 40 * 60_000 });
    const waitTo = now() - 3;
    const mmss = (s: number) => `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
    if (waitTo - waitFrom > 20) {
      cuts.push({ from: waitFrom, to: waitTo, note: `processing took ${mmss(now() - started)} (real elapsed); ${mmss(waitTo - waitFrom)} of waiting cut` });
    }
    await expect(phone.getByTestId("game-status")).toHaveText("ready");
    return `${processing} · ready after ${mmss(now() - started)}`;
  });

  await beat(page, "TV: the uploaded game plays", "TV: the uploaded game is in the library, ready — Watch", async () => {
    expect(gameId).not.toBe("");
    await openFromLibrary(page, gameId);
    await page.keyboard.press("Enter");
    await expect.poll(async () => (await media(page))?.paused).toBe(false);
    await expect.poll(async () => (await media(page))?.t ?? 0, { timeout: 10_000 }).toBeGreaterThan(2);
    await page.keyboard.press("Enter");
  });

  if (REAL) await realBeats(page, gameId);
  else await demoBeats(page, phone);

  // ------------------------------------------------------------------ wrap up
  await phoneCtx.close(); // flushes the phone video
  videos.phone = (await phone.video()?.path()) ?? "";
  videos.tv = test.info().outputPath("video.webm"); // where `video: on` saves it after the test
  save();
  expect(beats.filter((b) => !b.ok).map((b) => `${b.name}: ${b.error}`)).toEqual([]);
});

// -------------------------------------------------------------------- REAL footage beats
async function realBeats(page: Page, gameId: string) {
  await beat(page, "Watch: event markers + hype", "TV: Watch the uploaded REAL game (event markers, hype meter)", async () => {
    await openFromLibrary(page, gameId);
    await expect(page.getByTestId("hype-meter")).toBeVisible({ timeout: 15_000 });
    expect(await page.getByTestId("event-marker").count()).toBeGreaterThan(0);
    await page.keyboard.press("Enter");
    await expect.poll(async () => (await media(page))?.paused).toBe(false);
    await page.waitForTimeout(5000);
    await keyFrame(page, "watch");
  });
  await selectFollow(page);

  await beat(page, "Replay angles", "Replays: the first highlight's angles — Tier A real video, Tier B 2.5D cutouts", async () => {
    await openFirstReplay(page, gameId);
    await page.waitForTimeout(2500);
    await page.keyboard.press("Enter"); // pause: the playhead stays put across cuts
    const n = Number(((await page.getByTestId("replay-angle-pos").textContent()) ?? "").split("/")[1]);
    const tiers = new Set<string>([(await page.getByTestId("replay-tier-badge").textContent()) ?? ""]);
    for (let i = 2; i <= n; i++) {
      await page.keyboard.press("ArrowRight");
      await expect(page.getByTestId("replay-angle-pos")).toHaveText(`${i} / ${n}`);
      await expect.poll(async () => (await media(page))?.ready ?? 0, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
      const tier = (await page.getByTestId("replay-tier-badge").textContent()) ?? "";
      if (!tiers.has(tier)) await keyFrame(page, `angle_${tier.replace(/\W+/g, "")}`);
      tiers.add(tier);
      await page.waitForTimeout(2200);
    }
    expect([...tiers]).toContain("Real video");
    expect([...tiers]).toContain("2.5D");
    return `Replays: ${n} angles of the first highlight — ${[...tiers].sort().join(" + ")}`;
  });

  // Free view (D-75/D-77): the core of the REAL run. Each step is its own beat.
  let lay: SceneLayout | null = null;
  const need = () => {
    if (!lay) throw new Error("Free view was not entered");
    return lay;
  };
  const at = async (k: string) => Number(await replayAttr(page, k));
  await beat(page, "Free view: enter", "Free view: Down on the paused replay enters the live 2.5D scene at the angle's time", async () => {
    const play = await openFirstReplay(page, gameId);
    const res = await page.request.get(`${API}/games/${gameId}/scenes/${play}`);
    expect(res.ok(), `GET /games/${gameId}/scenes/${play}`).toBe(true);
    lay = (await res.json()) as SceneLayout;
    await expect(page.getByText("▼ Free view (2.5D)", { exact: false })).toBeVisible({ timeout: 15_000 });
    await expect.poll(async () => (await media(page))?.t ?? 0, { timeout: 15_000 }).toBeGreaterThan(1.5);
    await page.keyboard.press("Enter"); // pause the autoplaying angle
    await expect.poll(async () => (await media(page))?.paused).toBe(true);
    const t = (await media(page))?.t ?? 0;
    await page.waitForTimeout(1500);
    await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId("replay")).toHaveAttribute("data-mode", "free");
    const view = page.getByTestId("free-view");
    await expect(view).toHaveAttribute("data-ready", "true", { timeout: 30_000 });
    expect(Math.abs(Number(await view.getAttribute("data-frame")) - Math.floor(t * lay.fps))).toBeLessThanOrEqual(1);
    await expect(page.getByTestId("replay")).toHaveAttribute("data-preset", "real");
    await expect(page.getByTestId("free-honesty")).toHaveText(lay.honesty_label);
    await expect(page.getByTestId("free-limit")).toBeVisible();
    await expect(page.getByTestId("free-gauge")).toBeVisible();
    await expect(page.getByTestId("replay-synthetic")).toHaveCount(0); // real footage: no SYNTHETIC tag
    await expect(view).toHaveAttribute("data-settled", "true");
    await keyFrame(page, "free_real");
    const e = lay.envelope;
    return `Free view: entered ${play} at ${t.toFixed(2)} s on the real camera · envelope az ${e.azimuth_deg[0]}…${e.azimuth_deg[1]}°, el ${e.elevation_deg[0].toFixed(1)}…${e.elevation_deg[1].toFixed(1)}°`;
  });

  await beat(page, "Free view: orbit to both azimuth limits", "Free view: Left to the azimuth limit, Right to the other — edge bars + view-limit gauge", async () => {
    const env = need().envelope;
    for (const [key, edge, want] of [["ArrowLeft", "az-min", env.azimuth_deg[0]], ["ArrowRight", "az-max", env.azimuth_deg[1]]] as const) {
      const n = await pushTo(page, key, edge);
      await expect(page.getByTestId("replay")).toHaveAttribute("data-az", want.toFixed(2));
      await expect(page.getByTestId(`edge-${edge}`)).toBeVisible();
      await expect(page.getByTestId("free-gauge")).toBeVisible();
      await expect(page.getByTestId("free-view")).toHaveAttribute("data-settled", "true");
      await page.keyboard.press(key); // pushing further does nothing
      await page.waitForTimeout(400);
      expect(await at("az")).toBeCloseTo(want, 2);
      await keyFrame(page, `free_${edge}`);
      await page.waitForTimeout(1500);
      if (n === 0) throw new Error(`already at ${edge}`);
    }
    return `Free view: azimuth limits ${env.azimuth_deg[0]}° and +${env.azimuth_deg[1]}° reached and held · edge bars + gauge on screen`;
  });

  await beat(page, "Free view: elevation limit", "Free view: Up to the elevation limit, Down to the lowest — edge bars", async () => {
    const env = need().envelope;
    for (const [key, edge, want] of [["ArrowUp", "el-max", env.elevation_deg[1]], ["ArrowDown", "el-min", env.elevation_deg[0]]] as const) {
      await pushTo(page, key, edge);
      await expect(page.getByTestId("replay")).toHaveAttribute("data-el", want.toFixed(2));
      await expect(page.getByTestId(`edge-${edge}`)).toBeVisible();
      await expect(page.getByTestId("free-view")).toHaveAttribute("data-settled", "true");
      await keyFrame(page, `free_${edge}`);
      await page.waitForTimeout(1500);
    }
    return `Free view: elevation ${env.elevation_deg[1].toFixed(1)}° (top limit) and ${env.elevation_deg[0].toFixed(1)}° (lowest) reached · edge bars on screen`;
  });

  await beat(page, "Free view: dolly in and out", "Free view: Menu switches Up/Down to dolly — in to the closest, out to the farthest", async () => {
    const env = need().envelope;
    await page.keyboard.press("m");
    await expect(page.getByTestId("replay")).toHaveAttribute("data-zoom", "true");
    await pushTo(page, "ArrowUp", "d-min");
    await expect(page.getByTestId("replay")).toHaveAttribute("data-dist", env.distance_m[0].toFixed(3));
    await expect(page.getByTestId("free-gauge")).toContainText("closest");
    await expect(page.getByTestId("free-view")).toHaveAttribute("data-settled", "true");
    await keyFrame(page, "free_dolly_in");
    await page.waitForTimeout(1500);
    await pushTo(page, "ArrowDown", "d-max");
    await expect(page.getByTestId("replay")).toHaveAttribute("data-dist", env.distance_m[1].toFixed(3));
    await keyFrame(page, "free_dolly_out");
    await page.keyboard.press("m");
    await expect(page.getByTestId("replay")).toHaveAttribute("data-zoom", "false");
    return `Free view: dolly ${env.distance_m[0].toFixed(1)} m (closest) ↔ ${env.distance_m[1].toFixed(1)} m (farthest)`;
  });

  await beat(page, "Free view: cycle all presets", "Free view: Fast-forward cycles every preset, Rewind steps back", async () => {
    const l = need();
    // From a free camera FF goes to the first preset (real), then through every preset and wraps.
    for (const p of [l.presets[0], ...l.presets.slice(1), l.presets[0]]) {
      await page.keyboard.press(".");
      await expect(page.getByTestId("replay")).toHaveAttribute("data-preset", p.id);
      await expect(page.getByTestId("free-preset-label")).toHaveText(p.label);
      const want = presetState(p.id, l);
      await expect(page.getByTestId("replay")).toHaveAttribute("data-az", want.azimuth.toFixed(2));
      await expect(page.getByTestId("replay")).toHaveAttribute("data-el", want.elevation.toFixed(2));
      await expect(page.getByTestId("free-view")).toHaveAttribute("data-settled", "true");
      await keyFrame(page, `free_preset_${p.id}`);
      await page.waitForTimeout(1800);
    }
    await page.keyboard.press(",");
    await expect(page.getByTestId("replay")).toHaveAttribute("data-preset", l.presets[l.presets.length - 1].id);
    return `Free view: presets ${l.presets.map((p) => p.label).join(" → ")} → wrap, then Rewind`;
  });

  await beat(page, "Free view: play, then Back to the angle", "Free view: Select plays the scene, Select pauses, Back → the video angle at the same time", async () => {
    const view = page.getByTestId("free-view");
    const f0 = Number(await view.getAttribute("data-frame"));
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("replay")).toHaveAttribute("data-paused", "false");
    await expect.poll(async () => Number(await view.getAttribute("data-frame")), { timeout: 10_000 }).not.toBe(f0);
    await page.waitForTimeout(4000);
    await keyFrame(page, "free_playing");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("replay")).toHaveAttribute("data-paused", "true");
    await page.waitForTimeout(400);
    const tScene = Number(await view.getAttribute("data-time"));
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("replay")).toHaveAttribute("data-mode", "angles");
    await expect(page.getByTestId("free-view")).toHaveCount(0);
    await expect.poll(async () => Math.abs(((await media(page))?.t ?? -1) - tScene), { timeout: 10_000 }).toBeLessThan(0.05);
    expect((await media(page))?.paused).toBe(true);
    await keyFrame(page, "free_back_to_angle");
    return `Free view: played from frame ${f0}, paused at ${tScene.toFixed(2)} s, Back → the angle at ${((await media(page))?.t ?? 0).toFixed(2)} s, paused`;
  });

  await beat(page, "Highlights", "Highlights: a chip → its reel", async () => {
    // The real pipeline may find no shot in a 90 s cut (shot recall on Kennesaw is 3 of 6,
    // docs/progress.md): then the screen must say so ("No clips match"), and the caption does.
    const chip = SPORT === "basketball" ? "All shots" : "Rallies";
    await page.goto(`/tv/${gameId}`);
    await videoReady(page);
    await menuTo(page, "nav-highlights");
    await page.keyboard.press("Enter");
    const c = page.locator(`[data-testid="query-chip"][data-chip="${chip}"]`);
    await expect(c).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(1200);
    for (let i = 0; i < 12 && (await c.getAttribute("data-focused")) !== "true"; i++) await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("reel-clip").first().or(page.getByTestId("no-clips"))).toBeVisible({ timeout: 15_000 });
    const n = await page.getByTestId("reel-clip").count();
    await page.waitForTimeout(3500);
    await keyFrame(page, "highlights");
    return n
      ? `Highlights: “${chip}” → a reel of ${n} clip${n === 1 ? "" : "s"}`
      : `Highlights: “${chip}” → “No clips match”: the real pipeline found nothing for it in this cut`;
  });

  if (SPORT === "basketball") {
    await reviewBoxScore(page, gameId);
  } else {
    await beat(page, "Review: heatmap", "Review: the volleyball court heatmap (the sport's review panel)", async () => {
      await page.goto(`/tv/${gameId}`);
      await videoReady(page);
      await menuTo(page, "nav-review");
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("heatmap")).toBeVisible({ timeout: 15_000 });
      await expect.poll(() => page.getByTestId("heatmap-cell").count(), { timeout: 15_000 }).toBeGreaterThan(0);
      await expect(page.getByTestId("shot-chart")).toHaveCount(0);
      await page.waitForTimeout(2500);
      await keyFrame(page, "review");
    });
    await ralliesCondensed(page, gameId, "Volleyball");
  }
}

// -------------------------------------------------------------------- SYNTHETIC demo beats
async function demoBeats(page: Page, phone: Page) {
  await beat(page, "Library → Watch", "Library → Watch the SYNTHETIC basketball demo (event markers, hype meter)", async () => {
    await openFromLibrary(page, BB);
    await expect(page.getByTestId("hype-meter")).toBeVisible({ timeout: 15_000 });
    expect(await page.getByTestId("event-marker").count()).toBeGreaterThan(0);
    await page.keyboard.press("Enter");
    await expect.poll(async () => (await media(page))?.paused).toBe(false);
    await page.waitForTimeout(5000);
  });
  await selectFollow(page);

  await beat(page, "Broadcast + commentary", "Broadcast rendition + grounded commentary captions", async () => {
    await menuTo(page, "action-broadcast");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("watch")).toHaveAttribute("data-broadcast", "true");
    await expect.poll(async () => (await media(page))?.src ?? "").toContain("broadcast");
    await expect.poll(async () => (await media(page))?.ready ?? 0, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
    await page.keyboard.press("ArrowDown");
    await menuTo(page, "action-captions");
    await page.keyboard.press("Enter");
    await page.keyboard.press("ArrowDown");
    if ((await media(page))?.paused) await page.keyboard.press("Enter");
    await expect(page.getByTestId("caption")).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(8000);
    await page.keyboard.press("Enter"); // pause
  });

  await beat(page, "Pair phone + Clip that", "Phone pairs with the TV's code, taps “Clip that” → toast on the TV → Game ▸ Clips", async () => {
    await page.goto(`/tv/${BB}`);
    await videoReady(page);
    await menuTo(page, "nav-pair");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("pair-code")).toHaveText(/^\d{4}$/, { timeout: 15_000 });
    const code = ((await page.getByTestId("pair-code").textContent()) ?? "").trim();
    await phone.goto(`${PHONE}/companion`);
    await phone.getByTestId("companion-code-input").pressSequentially(code, { delay: 250 });
    await phone.getByTestId("companion-connect").click();
    await expect(phone.getByTestId("companion-status")).toHaveAttribute("data-state", "open", { timeout: 10_000 });
    await page.waitForTimeout(1500);

    // Back to the game (the TV keeps the session in memory: no page loads from here on),
    // play and scrub past the end of the second play, then tap: D-50 cuts the play that
    // just ended.
    const plays = (await (await page.request.get(`${API}/games/${BB}/plays`)).json()).plays as { t_end: number }[];
    const play = plays[Math.min(1, plays.length - 1)];
    await page.keyboard.press("Escape");
    await videoReady(page);
    await expect(phone.getByTestId("companion-now")).toHaveAttribute("data-game-id", BB, { timeout: 10_000 });
    await page.keyboard.press("Enter");
    await expect.poll(async () => (await media(page))?.paused).toBe(false);
    for (let i = 0; i < Math.floor((play.t_end - 3) / 5); i++) {
      await page.keyboard.press("ArrowRight"); // +5 s
      await page.waitForTimeout(400);
    }
    await expect.poll(async () => (await media(page))?.t ?? 0, { timeout: 20_000 }).toBeGreaterThan(play.t_end + 0.3);
    await phone.getByTestId("companion-clip").click();
    await expect(phone.getByTestId("companion-clip-result")).toHaveText(/^Clip saved/, { timeout: 10_000 });
    const label = (await phone.getByTestId("companion-clip-result").textContent()) ?? "";
    await expect(page.getByTestId("toast")).toHaveText(label);
    await page.waitForTimeout(2500);
    await page.keyboard.press("Enter"); // pause

    await menuTo(page, "nav-clips");
    await page.keyboard.press("Enter");
    const tap = page.locator('[data-testid="clip-card"][data-trigger="tap"]').first();
    await expect(tap).toBeVisible({ timeout: 15_000 });
    for (let i = 0; i < 12 && (await tap.getAttribute("data-focused")) !== "true"; i++) {
      await page.keyboard.press("ArrowDown");
      await page.waitForTimeout(300);
    }
    await expect(tap).toHaveAttribute("data-focused", "true");
    await page.waitForTimeout(2000);
    await page.keyboard.press("Enter"); // the D-pad trim handles
    await expect(page.getByTestId("trim-panel")).toBeVisible();
    await page.keyboard.press("ArrowLeft"); // start −0.5 s
    await page.waitForTimeout(800);
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowRight"); // end +0.5 s
    await page.waitForTimeout(800);
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter"); // Save trim
    await expect(page.getByTestId("trim-note")).toHaveText("Trim saved");
  });

  await beat(page, "9:16 share", "Clips ▸ Share 9:16: portrait export with burned-in caption", async () => {
    if (!(await page.getByTestId("trim-panel").isVisible())) {
      // the previous beat did not leave a clip open: open the first one
      await page.goto(`/tv/${BB}/clips`);
      await expect(page.getByTestId("clip-card").first()).toBeVisible({ timeout: 15_000 });
      await page.keyboard.press("Enter");
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("ArrowDown"); // the action row, on Save trim
    }
    await page.keyboard.press("ArrowRight"); // Share 9:16
    await page.keyboard.press("Enter");
    const panel = page.getByTestId("export-panel");
    await expect(panel).toBeVisible();
    await expect(panel).toHaveAttribute("data-status", "done", { timeout: 240_000 });
    await expect
      .poll(
        () =>
          page.evaluate(() => document.querySelector<HTMLVideoElement>('[data-testid="vertical-preview"] video')?.readyState ?? 0),
        { timeout: 30_000 },
      )
      .toBeGreaterThanOrEqual(2);
    await page.waitForTimeout(5000);
  });

  await beat(page, "Replay angles A/B/C", "Replays: the same moment from Tier A video, Tier B 2.5D cutouts, Tier C 3D", async () => {
    await page.goto(`/tv/${BB}`);
    await videoReady(page);
    await menuTo(page, "nav-replays");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("replay-card").first()).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(1500);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("replay-angle-pos")).toHaveText(/^1 \/ \d+$/, { timeout: 15_000 });
    await videoReady(page);
    await page.waitForTimeout(2500);
    await page.keyboard.press("Enter"); // pause: the playhead stays put across cuts
    const n = Number(((await page.getByTestId("replay-angle-pos").textContent()) ?? "").split("/")[1]);
    const tiers = new Set<string>([(await page.getByTestId("replay-tier-badge").textContent()) ?? ""]);
    for (let i = 2; i <= n; i++) {
      await page.keyboard.press("ArrowRight");
      await expect(page.getByTestId("replay-angle-pos")).toHaveText(`${i} / ${n}`);
      await expect.poll(async () => (await media(page))?.ready ?? 0, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
      tiers.add((await page.getByTestId("replay-tier-badge").textContent()) ?? "");
      await page.waitForTimeout(2200);
    }
    expect([...tiers].sort()).toEqual(["2.5D", "3D", "Real video"]);
  });

  await beat(page, "Highlights + search", "Highlights reel, then Search “steal” typed with the D-pad", async () => {
    await page.goto(`/tv/${BB}`);
    await videoReady(page);
    await menuTo(page, "nav-highlights");
    await page.keyboard.press("Enter");
    const all = page.locator('[data-testid="query-chip"][data-chip="All shots"]');
    await expect(all).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(1200);
    for (let i = 0; i < 12 && (await all.getAttribute("data-focused")) !== "true"; i++) await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("reel-clip").first()).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(3500);

    await page.goto(`/tv/${BB}`);
    await videoReady(page);
    await menuTo(page, "nav-search");
    await page.keyboard.press("Enter");
    const ask = page.locator('[data-testid="search-chip"][data-chip="Type a search…"]');
    await expect(ask).toBeVisible({ timeout: 15_000 });
    for (let i = 0; i < 12 && (await ask.getAttribute("data-focused")) !== "true"; i++) await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("search-dialog")).toBeVisible();
    await typeKeys(page, "search", ["S", "T", "E", "A", "L", "SAVE"]);
    await expect(page.getByTestId("search-interpretation")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("search-hit").first().or(page.getByTestId("search-empty"))).toBeVisible();
    await page.waitForTimeout(3000);
  });

  await reviewBoxScore(page, BB);

  await beat(page, "Player profile + card", "Phone creates a profile → TV links a player → Players ▸ card", async () => {
    const name = `Riley ${Date.now() % 1000}`;
    await phone.goto(`${PHONE}/profiles`);
    await phone.getByTestId("profile-name-input").pressSequentially(name, { delay: 80 });
    await phone.getByTestId("profile-create").click();
    await expect(phone.getByTestId("profile-edit-name")).toHaveText(name, { timeout: 10_000 });
    const pid = (await phone.getByTestId("profile-edit").getAttribute("data-profile-id")) ?? "";

    await page.goto(`/tv/${BB}?t=8`);
    await videoReady(page);
    await enterSelectMode(page);
    for (let i = 0; i < 10 && (await page.getByTestId("nav-library").getAttribute("data-focused")) !== "true"; i++) {
      await page.keyboard.press("ArrowUp");
    }
    await page.keyboard.press("Escape");
    await menuTo(page, "action-link-profile");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("profile-picker")).toBeVisible();
    const row = page.locator(`[data-testid="picker-profile"][data-profile-id="${pid}"]`);
    for (let i = 0; i < 20 && (await row.getAttribute("data-focused")) !== "true"; i++) await page.keyboard.press("ArrowDown");
    await expect(row).toHaveAttribute("data-focused", "true");
    await page.waitForTimeout(1000);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("toast")).toHaveText(`Linked to ${name}`);
    await phone.reload();
    await expect(phone.getByText(/Linked in 1 game\b/)).toBeVisible();
    await page.waitForTimeout(1500);

    await page.goto("/");
    await expect(page.getByTestId("game-card").first()).toBeVisible({ timeout: 15_000 });
    await page.keyboard.press("ArrowUp"); // the Players pill
    await expect(page.getByTestId("library-players")).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("Enter");
    const card = page.locator(`[data-testid="profile-card"][data-profile-id="${pid}"]`);
    await expect(card).toBeVisible({ timeout: 15_000 });
    for (let i = 0; i < 20 && (await card.getAttribute("data-focused")) !== "true"; i++) await page.keyboard.press("ArrowRight");
    await expect(card).toHaveAttribute("data-focused", "true");
    await page.waitForTimeout(1000);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("profile")).toHaveAttribute("data-zone", "tabs");
    await page.waitForTimeout(1500);
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("profile")).toHaveAttribute("data-tab", "card");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter"); // render the card PNG on the server
    await expect(page.getByTestId("card-tab")).toHaveAttribute("data-rendered", "true", { timeout: 60_000 });
    await expect
      .poll(
        // react-native-web draws an <Image> as a div around a hidden <img>
        () => page.getByTestId("card-png").evaluate((el) => (el.querySelector("img") ?? (el as HTMLImageElement)).naturalWidth ?? 0),
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0);
    await expect(page.getByTestId("card-title")).toContainText(name);
    await page.waitForTimeout(2500);
  });

  await ralliesCondensed(page, PB, "Pickleball");
}

/** Watch is playing: pause into select mode, follow a player, spotlight + court inset. */
async function selectFollow(page: Page) {
  await beat(page, "Select → follow → spotlight → inset", "Select a player → follow-cam → spotlight, court inset", async () => {
    await page.keyboard.press("Enter"); // pause into select mode
    await expect.poll(async () => (await media(page))?.paused).toBe(true);
    await expect(page.locator('[data-testid^="select-box-"]').first()).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(1200);
    for (let i = 0; i < 2; i++) {
      await page.keyboard.press("ArrowRight");
      await page.waitForTimeout(700);
    }
    await expect(page.locator('[data-testid^="select-box-"][data-focused="true"]')).toHaveCount(1);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("followcam-active")).toBeVisible();
    await page.keyboard.press("Enter"); // play the follow-cam
    await page.waitForTimeout(3000);
    await menuTo(page, "action-spotlight");
    await page.keyboard.press("Enter");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId("spotlight-overlay")).toBeVisible();
    await expect(page.getByTestId("court-inset")).toBeVisible();
    expect(await page.locator('[data-testid^="court-dot-"]').count()).toBeGreaterThan(1);
    await page.waitForTimeout(4000);
    await keyFrame(page, "follow_spotlight");
    await page.keyboard.press("Escape"); // back to the wide shot
    await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  });
}

async function reviewBoxScore(page: Page, gameId: string) {
  await beat(page, "Review + box score", "Review: shot chart, auto-detected box score, answer the queue with the remote", async () => {
    await page.goto(`/tv/${gameId}`);
    await videoReady(page);
    await menuTo(page, "nav-review");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("auto-detected-label")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("shot-chart")).toBeVisible();
    await expect.poll(() => page.getByTestId("box-score-row").count(), { timeout: 15_000 }).toBeGreaterThan(0);
    await page.waitForTimeout(2500);
    await keyFrame(page, "review");
    const item = page.getByTestId("review-item");
    await expect(item).toBeVisible();
    const first = await item.getAttribute("data-event-id");
    await page.keyboard.press("Enter"); // the first option
    await expect(item.or(page.getByTestId("review-empty"))).not.toHaveAttribute("data-event-id", first ?? "");
  });
}

async function ralliesCondensed(page: Page, gameId: string, sport: string) {
  await beat(page, `${sport} rallies + condensed`, `${sport}: rally browser, then the condensed game (RALLY n / N)`, async () => {
    await openFromLibrary(page, gameId);
    await menuTo(page, "nav-rallies");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("rally-row").first()).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(1500);
    await page.keyboard.press("ArrowRight"); // Longest
    await page.keyboard.press("ArrowDown");
    await videoReady(page);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("rally-counter")).toBeVisible();
    await page.waitForTimeout(3000);
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("ArrowRight"); // Condensed game
    await expect(page.getByTestId("rally-tab-condensed")).toHaveAttribute("data-focused", "true");
    if (await page.getByTestId("condensed-status").count()) await page.keyboard.press("Enter");
    await expect(page.getByTestId("rallies")).toHaveAttribute("data-condensed", "true", { timeout: 240_000 });
    await videoReady(page);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("rally-counter")).toHaveText(/RALLY \d+ \/ \d+/i, { timeout: 15_000 });
    await page.waitForTimeout(5000);
    await keyFrame(page, "condensed");
  });
}
