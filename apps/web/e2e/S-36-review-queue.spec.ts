import { expect, test } from "@playwright/test";
import { GAME_ID, NET_GAME_ID, mockCalls } from "./helpers";

// S-36 confirm, S-37 correct, E-19 confidence indicator, R1/R3 shot chart + box score.
test("S-36 confirming Made PATCHes the event and clears the queue", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);

  const item = page.getByTestId("review-item");
  await expect(item).toBeVisible();
  // E-19: only the sub-threshold, unconfirmed event is queued.
  await expect(item).toHaveAttribute("data-event-id", "e_0004");
  await expect(item).toHaveAttribute("data-confidence", "0.55");

  await page.keyboard.press("Enter"); // "Made" is the focused action

  await expect(page.getByTestId("review-empty")).toBeVisible();
  const patch = (await mockCalls(page)).filter(
    (c) => c.method === "PATCH" && c.path.includes("/events/e_0004"),
  );
  expect(patch).toHaveLength(1);
  expect(patch[0].body).toEqual({ made: true, confirmed: true });
});

test("S-37 correcting to Missed sends made:false", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  await expect(page.getByTestId("review-item")).toBeVisible();

  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("review-action-missed")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("review-empty")).toBeVisible();
  const patch = (await mockCalls(page)).filter((c) => c.method === "PATCH");
  expect(patch[0].body).toEqual({ made: false, confirmed: true });
});

test("R1/R3 the shot chart and box score render, labelled auto-detected", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  await expect(page.getByTestId("auto-detected-label")).toBeVisible();
  await expect(page.getByTestId("shot-chart")).toBeVisible();
  await expect(page.getByTestId("shot-marker")).toHaveCount(4);
  await expect(page.getByTestId("box-score-row")).toHaveCount(4);

  const marcus = page.locator('[data-testid="box-score-row"][data-player-id="p1"]');
  await expect(marcus).toContainText("Marcus");
  const cells = await marcus.locator("td").allTextContents();
  expect(cells.slice(0, 3)).toEqual(["Marcus", "2", "2"]);
});

test("R3 stats recompute after a review answer", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  await expect(page.getByTestId("review-item")).toBeVisible();
  const p3 = page.locator('[data-testid="box-score-row"][data-player-id="p3"]');
  await expect(p3).toBeVisible();

  await page.keyboard.press("ArrowRight"); // Missed
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("review-empty")).toBeVisible();
  await expect
    .poll(async () => (await p3.locator("td").allTextContents()).slice(1, 3))
    .toEqual(["1", "0"]);
});

// Bug 4: `sport_ui.review` was ignored, so a net sport declaring `[heatmap]` still drew
// an empty shot chart and an empty box score.
test("S-33/S-35 only the panels in sport_ui.review are rendered", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  // basketball lists all three
  await expect(page.getByTestId("shot-chart")).toBeVisible();
  await expect(page.getByTestId("heatmap")).toBeVisible();
  await expect(page.getByTestId("box-score-row").first()).toBeVisible();

  await page.goto(`/tv/${NET_GAME_ID}/review`);
  // pickleball lists only the heatmap
  await expect(page.getByTestId("heatmap")).toBeVisible();
  await expect(page.getByTestId("shot-chart")).toHaveCount(0);
  await expect(page.getByTestId("box-score-row")).toHaveCount(0);
  // the queue is the screen's job, not a stat, so it stays for every sport
  await expect(page.getByTestId("review-empty")).toBeVisible();
});
