import { expect, test } from "@playwright/test";
import { GAME_ID, mockCalls } from "./helpers";

test("TV-05 Highlights: a profile chip runs the shared query route and plays the reel (H3)", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}/highlights`);
  const chips = page.getByTestId("query-chip");
  // Per-player reel first (p1 is Marcus), then the profile's sport_ui.chips, Ask…, Pair.
  await expect(chips.first()).toHaveAttribute("data-chip", "Marcus — all shots");
  await expect(page.locator('[data-chip="Makes"]')).toBeVisible();

  // Marcus → All shots → Makes.
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.locator('[data-chip="Makes"]')).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("query-interpretation")).toHaveText("Showing: Makes");
  await expect(page.getByTestId("reel-clip")).toHaveCount(3);
  await expect(page.getByTestId("reel-clip").first()).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("clip-counter")).toHaveText("clip 1/3");
  const q = (await mockCalls(page)).find((c) => c.path === `/games/${GAME_ID}/query`);
  expect(q?.body).toEqual({ text: "Makes" });

  await page.keyboard.press("Enter");
  await expect
    .poll(() => page.evaluate(() => document.querySelector("video")?.paused))
    .toBe(false);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("video")).toBeAttached();
  await expect(page.getByTestId("mode-pill")).toBeVisible();
});

test("TV-06 Review: answer the queue by remote; panels follow sport_ui.review (R1-R5)", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  await expect(page.getByTestId("auto-detected-label")).toBeVisible();
  // GET /review/queue (D-48): the 0.55-confidence shot first, then untagged players.
  await expect(page.getByTestId("review-item")).toHaveAttribute("data-event-id", "e_0004");
  await expect(page.getByTestId("review-item")).toHaveAttribute("data-kind", "low_confidence");
  await expect(page.getByTestId("shot-chart")).toBeVisible();
  await expect(page.getByTestId("shot-marker")).toHaveCount(4);
  await expect(page.getByTestId("heatmap")).toBeVisible();
  await expect(page.getByTestId("box-score-row")).toHaveCount(4);

  await page.keyboard.press("ArrowRight"); // No
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("review-item")).toHaveAttribute("data-kind", "identity");
  const patch = (await mockCalls(page)).find((c) => c.method === "PATCH");
  expect(patch).toMatchObject({
    path: `/games/${GAME_ID}/events/e_0004`,
    body: { dismissed: true, confirmed: true },
  });

  // A net-sport profile lists only the heatmap: no shot chart, no box score.
  await page.goto(`/tv/g_pickle4/review`);
  await expect(page.getByTestId("auto-detected-label")).toBeVisible();
  await expect(page.getByTestId("heatmap")).toBeVisible();
  await expect(page.getByTestId("shot-chart")).toHaveCount(0);
  await expect(page.getByTestId("box-score-row")).toHaveCount(0);
});

test("TV-07 Pair: the code from POST /sessions; Back returns to the game", async ({ page }) => {
  await page.goto(`/tv/pair?game=${GAME_ID}`);
  await expect(page.getByTestId("pair-code")).toHaveText("4821");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("video")).toBeAttached();
});

test("TV-08 10-foot UI: no rendered text below 24 px at 1080p on any screen", async ({ page }) => {
  for (const path of [
    "/",
    `/tv/${GAME_ID}`,
    `/tv/${GAME_ID}/highlights`,
    `/tv/${GAME_ID}/review`,
    "/tv/pair",
    `/tv/${GAME_ID}/clips`,
    "/tv/g_pickle4/rallies",
    `/tv/${GAME_ID}/search`,
    `/tv/${GAME_ID}/advice`,
  ]) {
    await page.goto(path);
    await page.waitForTimeout(500);
    const small = await page.evaluate(() =>
      [...document.querySelectorAll("div, span")]
        .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent?.trim()))
        .map((el) => ({ text: el.textContent, size: parseFloat(getComputedStyle(el).fontSize) }))
        .filter((x) => x.size < 24),
    );
    expect(small, path).toEqual([]);
  }
});
