// §6.3 DoD line 5: a rough recording of the demo, as insurance. Plays the whole core
// loop on the real 240 s game with the remote only. The .webm lands under
// test-results/ and is copied out — it holds third-party footage, so it never goes in
// the repo (D-7).
//
//   REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-03
import { expect, test } from "@playwright/test";
import { API, findGame, videoState, waitForVideo } from "./helpers";

const TITLE = process.env.REPLAY_E2E_REAL_TITLE ?? "Kennesaw 240";

test.use({ video: { mode: "on", size: { width: 1920, height: 1080 } } });

test("R-03 demo reel: library -> watch -> select -> follow -> highlights -> review", async ({
  page,
}) => {
  test.setTimeout(300_000);
  const gameId = await findGame(page, TITLE);
  test.skip(!gameId, `no processed game titled "${TITLE}" on ${API}`);

  await page.goto("/tv");
  await expect(page.locator(`[data-testid=game-card][data-game-id="${gameId}"]`)).toBeVisible();
  await page.waitForTimeout(1500);

  await page.goto(`/tv/${gameId}`);
  await waitForVideo(page);
  await page.keyboard.press("Space"); // play 5 s
  await expect.poll(async () => (await videoState(page))?.paused).toBe(false);
  await page.waitForTimeout(5000);
  await page.keyboard.press("Space"); // pause -> select mode
  await expect.poll(async () => (await videoState(page))?.paused).toBe(true);
  await expect(page.locator('[data-testid^="select-box-"]').first()).toBeVisible();

  for (const dir of ["ArrowRight", "ArrowUp", "ArrowRight"]) {
    await page.keyboard.press(dir);
    await page.waitForTimeout(700);
  }
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toBeVisible();
  await page.keyboard.press("Space"); // 8 s of follow-cam
  await page.waitForTimeout(8000);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  await page.waitForTimeout(1200);

  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await page.waitForURL(new RegExp(`/tv/${gameId}/highlights`));
  await expect(page.getByTestId("query-chip").first()).toBeVisible();
  await page.keyboard.press("Enter"); // the focused chip
  await expect(page.getByTestId("reel-clip").first()).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter"); // play the first clip
  await waitForVideo(page);
  await page.waitForTimeout(6000);

  await page.goto(`/tv/${gameId}/review`);
  await expect(
    page.getByTestId("review-item").or(page.getByTestId("review-empty")),
  ).toBeVisible();
  if (await page.getByTestId("review-item").isVisible()) {
    await page.waitForTimeout(1200);
    await page.keyboard.press("Enter"); // confirm one
  }
  await page.waitForTimeout(2000);
});
