// Recorded end-to-end run (opt-in project `recording`, scripts/record-e2e.sh): the TV app's
// web build and the phone companion, two browser contexts, against the real services/api
// with REPLAY_PIPELINE=worker on hfbox. Nothing is mocked. Footage is SYNTHETIC only: a
// short `courtcam synth` clip uploaded through the phone, and the `make demo` games.
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
//   REPLAY_REC_OUT       where beats.json and the phone video go
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { enterSelectMode, menuTo } from "../e2e/helpers";

const env = (k: string) => process.env[k] ?? "";
const API = env("REPLAY_REC_API");
const PHONE = env("REPLAY_REC_PHONE");
const CLIP = env("REPLAY_REC_CLIP");
const LANDMARKS = env("REPLAY_REC_LANDMARKS");
const OUT = env("REPLAY_REC_OUT") || "test-results/recording";
const BB = "g_demo_basketball";
const PB = "g_demo_pickleball";
const UPLOAD_TITLE = "SYNTHETIC upload (recording)";
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
  await expect(page.getByTestId("game-card").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(2000);

  // ------------------------------------------------------------------ TV settings
  await beat(page, "TV settings: test connection", "TV: Library → Settings → Test connection", async () => {
    await expect(page.getByTestId("game-card").first()).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("library-settings")).toHaveAttribute("data-focused", "true");
    await page.waitForTimeout(800);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("settings-api-base")).toHaveText(API);
    await expect(page.getByTestId("settings-item-1")).toHaveAttribute("data-focused", "true");
    await page.waitForTimeout(1000);
    await page.keyboard.press("Enter"); // Test connection
    await expect(page.getByTestId("settings-check")).toHaveAttribute("data-state", "ok", { timeout: 10_000 });
    await expect(page.getByTestId("settings-check")).toHaveText(/^Connected · \d+ games?$/);
    await page.waitForTimeout(2000);
    await page.keyboard.press("ArrowRight"); // Done
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("game-card").first()).toBeVisible();
  });

  // ------------------------------------------------------------------ phone upload
  let gameId = "";
  await beat(phone, "Phone: create game + upload", "Phone: create a game and upload a 20 s SYNTHETIC clip", async () => {
    await expect(phone.getByTestId("sport-option-basketball")).toBeVisible({ timeout: 20_000 });
    await phone.getByTestId("game-title-input").fill(UPLOAD_TITLE);
    await phone.getByTestId("sport-option-basketball").check();
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
    await phone.getByTestId("variant-half").check(); // the clip is a half court
    await expect(phone.getByTestId("autocalib-status")).not.toHaveText(/^$/, { timeout: 60_000 });
    await expect(phone.getByTestId("autocalib-busy")).toHaveCount(0, { timeout: 90_000 });
    await phone.waitForTimeout(2000);
    const accept = phone.getByTestId("autocalib-accept");
    let path = "Phone: auto-calibration proposal accepted (ok)";
    if ((await accept.count()) && (await accept.isEnabled())) {
      await accept.click();
    } else {
      // D-72 refusal on screen: the weak-fit note, Accept disabled until a drag or the confirm
      await expect(phone.getByTestId("autocalib-weak")).toBeVisible();
      await expect(accept).toBeDisabled();
      await phone.waitForTimeout(3000);
      path = "Phone: low-confidence proposal refused (D-72) → landmarks placed by hand";
      await phone.getByTestId("autocalib-manual").click();
      const truth = JSON.parse(fs.readFileSync(LANDMARKS, "utf8")).landmarks_px as Record<string, [number, number]>;
      const sports: { id: string; landmarks?: string[] }[] = await (await phone.request.get(`${API}/sports`)).json();
      const order = sports.find((s) => s.id === "basketball")?.landmarks ?? [];
      const img = phone.getByTestId("calib-image");
      const frame = await img.evaluate((el: HTMLImageElement) => ({ w: el.naturalWidth, h: el.naturalHeight }));
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
        await phone.waitForTimeout(500);
      }
    }
    await expect(phone.getByTestId("calib-error")).toHaveAttribute("data-ok", "true");
    await phone.getByTestId("start-processing").scrollIntoViewIfNeeded();
    await expect(phone.getByTestId("start-processing")).toBeEnabled();
    return path;
  });

  await beat(phone, "Phone: process (real worker pipeline)", "Phone: start processing — the real worker pipeline runs on hfbox", async () => {
    await phone.getByTestId("start-processing").click();
    await phone.waitForURL(new RegExp(`/upload/${gameId}/status`));
    await expect(phone.locator('[data-testid^="stage-"][data-state="running"]').first()).toBeVisible({ timeout: 120_000 });
    const waitFrom = now() + 10;
    await expect(phone.getByTestId("game-status")).toHaveText(/^(ready|failed)$/, { timeout: 40 * 60_000 });
    const waitTo = now() - 3;
    if (waitTo - waitFrom > 20) {
      cuts.push({ from: waitFrom, to: waitTo, note: `${Math.round((waitTo - waitFrom) / 60)} min of processing cut` });
    }
    await expect(phone.getByTestId("game-status")).toHaveText("ready");
  });

  await beat(page, "TV: the uploaded game plays", "TV: the uploaded game is in the library, ready — Watch", async () => {
    expect(gameId).not.toBe("");
    await openFromLibrary(page, gameId);
    await page.keyboard.press("Enter");
    await expect.poll(async () => (await media(page))?.paused).toBe(false);
    await expect.poll(async () => (await media(page))?.t ?? 0, { timeout: 10_000 }).toBeGreaterThan(2);
    await page.keyboard.press("Enter");
  });

  // ------------------------------------------------------------------ demo beats
  await beat(page, "Library → Watch", "Library → Watch the SYNTHETIC basketball demo (event markers, hype meter)", async () => {
    await openFromLibrary(page, BB);
    await expect(page.getByTestId("hype-meter")).toBeVisible({ timeout: 15_000 });
    expect(await page.getByTestId("event-marker").count()).toBeGreaterThan(0);
    await page.keyboard.press("Enter");
    await expect.poll(async () => (await media(page))?.paused).toBe(false);
    await page.waitForTimeout(5000);
  });

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
    await page.keyboard.press("Escape"); // back to the wide shot
    await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  });

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

  await beat(page, "Review + box score", "Review: shot chart, auto-detected box score, answer the queue with the remote", async () => {
    await page.goto(`/tv/${BB}`);
    await videoReady(page);
    await menuTo(page, "nav-review");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("auto-detected-label")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("shot-chart")).toBeVisible();
    await expect.poll(() => page.getByTestId("box-score-row").count(), { timeout: 15_000 }).toBeGreaterThan(0);
    await page.waitForTimeout(2500);
    const item = page.getByTestId("review-item");
    await expect(item).toBeVisible();
    const first = await item.getAttribute("data-event-id");
    await page.keyboard.press("Enter"); // the first option
    await expect(item.or(page.getByTestId("review-empty"))).not.toHaveAttribute("data-event-id", first ?? "");
  });

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

  await beat(page, "Pickleball rallies + condensed", "Pickleball: rally browser, then the condensed game (RALLY n / N)", async () => {
    await openFromLibrary(page, PB);
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
  });

  // ------------------------------------------------------------------ wrap up
  await phoneCtx.close(); // flushes the phone video
  videos.phone = (await phone.video()?.path()) ?? "";
  videos.tv = test.info().outputPath("video.webm"); // where `video: on` saves it after the test
  save();
  expect(beats.filter((b) => !b.ok).map((b) => `${b.name}: ${b.error}`)).toEqual([]);
});
