// §6.3 DoD line 1: a new REAL game goes from phone upload to watchable-with-follow-cam
// on the TV with nothing manual but the calibration clicks. Drives the product against
// services/api in REAL pipeline mode (courtcam + YOLO on CPU), so this takes minutes.
//
//   REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-01
import { expect, test } from "@playwright/test";
import {
  API,
  calibrate,
  findGame,
  haveClip,
  clip,
  landmarks,
  shot,
  transform,
  videoState,
  waitForVideo,
} from "./helpers";

const CLIP = "basketball_kennesawwide_smoke.mp4";
const TITLE = "Kennesaw wide";
const STAGES = ["ingest", "detect", "track", "render", "label"];

test.describe.configure({ mode: "serial" });

test.skip(!haveClip(CLIP), `samples/real/${CLIP} is gitignored (D-7); nothing to run`);

let gameId = "";

test("R-01 upload -> calibrate -> real pipeline -> select -> follow -> highlights -> review", async ({
  page,
}) => {
  test.setTimeout(1_200_000); // ~50 s of 2560x960 through YOLO at ~6 fps, plus ingest

  await page.goto("/upload");
  await expect(page.getByTestId("sport-option-basketball")).toBeVisible();
  await page.getByTestId("game-title-input").fill(TITLE);
  await page.getByTestId("sport-option-basketball").check();
  await page.getByTestId("create-game").click();
  await page.waitForURL(/\/upload\/g_[a-z0-9]+/);
  gameId = new URL(page.url()).pathname.split("/")[2];

  await page.getByTestId("file-input").setInputFiles(clip(CLIP));
  await expect(page.getByTestId("upload-done")).toBeVisible({ timeout: 180_000 });
  await page.getByTestId("go-calibrate").click();

  // Whole-court camera => the `full` variant, and corner_fr is off the bottom of the
  // frame. Guessing it on-frame is ~20 px of reprojection error and a useless
  // homography; skipping it and adding the optional key/ft/centre points is 0.26 px.
  const px = await calibrate(page, "full", landmarks());
  // The gate here is 1 % of the clicked span (~25 px on this 2560-px panorama), not the
  // 5 px floor: see courtcam.calibrate.max_reproj_px and samples/real/RESULTS.md.
  expect(px, "reprojection error on real footage").toBeLessThan(26);
  await shot(page, "01-calibrate-real");

  await expect(page.getByTestId("start-processing")).toBeEnabled();
  await page.getByTestId("start-processing").click();
  await page.waitForURL(new RegExp(`/upload/${gameId}/status`));

  // S-08 / D-17: exactly one stage running, earlier ones done, later ones pending.
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const status = document.querySelector('[data-testid="game-status"]')?.textContent;
          const states = [...document.querySelectorAll('[data-testid^="stage-"]')]
            .map((el) => el.getAttribute("data-state"))
            .join(",");
          return `${status} ${states}`;
        }),
      { timeout: 300_000 },
    )
    .toMatch(/^processing (done,)*running(,pending)*$/);
  await shot(page, "05-status-phone-midrun");

  for (const stage of STAGES) {
    await expect(page.getByTestId(`stage-${stage}`)).toHaveAttribute("data-state", /done|partial/, {
      timeout: 1_000_000,
    });
  }
  await expect(page.getByTestId("game-status")).toHaveText("ready");

  // --- TV: library -> open with the D-pad only ---------------------------
  await page.goto("/tv");
  const card = page.locator(`[data-testid=game-card][data-game-id="${gameId}"]`);
  await expect(card).toBeVisible();
  await expect(card.getByTestId("game-status")).toHaveText("ready");
  await page.goto(`/tv/${gameId}`);

  // --- select mode on real footage ---------------------------------------
  await waitForVideo(page);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await videoState(page))?.paused).toBe(false);
  await expect.poll(async () => (await videoState(page))?.currentTime ?? 0).toBeGreaterThan(2);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await videoState(page))?.paused).toBe(true);

  const boxes = page.locator('[data-testid^="select-box-"]');
  await expect(boxes.first()).toBeVisible({ timeout: 20_000 });
  expect(await boxes.count(), "real detections in select mode").toBeGreaterThan(1);
  await shot(page, "02-select-real");

  // --- follow mode -------------------------------------------------------
  const tBefore = (await videoState(page))!.currentTime;
  const wide = await transform(page);
  // Up twice: the lowest boxes on this camera are the scorer's table (RESULTS.md), and
  // the screenshot is supposed to show a player.
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toBeVisible();
  await expect.poll(() => transform(page)).not.toMatch(/^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);
  // W4: following happens at the same media time, not a seek.
  expect(Math.abs((await videoState(page))!.currentTime - tBefore)).toBeLessThan(1 / 30 + 1e-6);
  await shot(page, "03-follow-real");

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  await expect.poll(() => transform(page)).toBe(wide);

  // --- highlights, reached with the remote -------------------------------
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("nav-highlights")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await page.waitForURL(new RegExp(`/tv/${gameId}/highlights`));

  const chips = page.getByTestId("query-chip");
  await expect(chips.first()).toBeVisible();
  const labels = await chips.evaluateAll((els) => els.map((e) => e.getAttribute("data-chip") ?? ""));
  const target = labels.findIndex((l) => /all shots/i.test(l));
  expect(target, `no "all shots" chip in ${JSON.stringify(labels)}`).toBeGreaterThanOrEqual(0);
  for (let i = 0; i < target; i++) await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("query-interpretation")).toBeVisible();
  await expect(page.getByTestId("reel-clip").first()).toBeVisible();
  await waitForVideo(page); // the reel's first frame, or the screenshot is a black box
  await shot(page, "04-highlights-real");

  // --- review ------------------------------------------------------------
  await page.goto(`/tv/${gameId}/review`);
  await expect(
    page.getByTestId("review-item").or(page.getByTestId("review-empty")),
  ).toBeVisible();
  await shot(page, "06-review-real");

  if (await page.getByTestId("review-item").isVisible()) {
    const eventId = await page.getByTestId("review-item").getAttribute("data-event-id");
    await page.keyboard.press("Enter"); // "Made"
    const events = await (
      await page.request.get(`${API}/media/games/${gameId}/events.json`)
    ).json();
    expect(events.events.find((e: { id: string }) => e.id === eventId)).toMatchObject({
      confirmed: true,
      source: "user",
    });
  }
});

test("R-01c the library exposes the processed game by title", async ({ page }) => {
  expect(await findGame(page, TITLE)).not.toBe("");
});
