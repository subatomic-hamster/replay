// The Moments layer (Down): moment cards above the court line cued to the nearest moment,
// Left/Right walk (the playhead follows), Select jumps and closes, filter chips above
// (All N, Scores, each player, Your bookmarks), Up to the chips then Up closes, Back
// closes. Mock g_mock01: moments at 3 (Basket, Marcus), 8 (Missed shot, p2),
// 14 (Basket, Marcus), 17 (Basket, p3); thumbs for all four.
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, media, menuTo, openWatch } from "./helpers";

const cards = (page: Page) => page.getByTestId("moment-card");
const focusedCard = (page: Page) =>
  page.locator('[data-testid="moment-card"][data-focused="true"]');
const chip = (page: Page, id: string) =>
  page.locator(`[data-testid="moment-filter"][data-filter="${id}"]`);

test("TV-21 Moments: cued to the nearest, walk, filter, jump", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=7.5");
  await page.keyboard.press("Space"); // pause so "nearest" stays put
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moments-layer")).toBeVisible();
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-layer",
    "moments",
  );
  await expect(cards(page)).toHaveCount(4);
  await expect(focusedCard(page)).toHaveAttribute("data-moment-id", "e_0002");
  await expect(focusedCard(page)).toContainText("0:08");
  await expect(page.getByTestId("timeline")).toHaveAttribute("data-t", "8.0"); // the playhead follows

  await page.keyboard.press("ArrowRight");
  await expect(focusedCard(page)).toHaveAttribute("data-moment-id", "e_0003");
  await expect(page.getByTestId("timeline")).toHaveAttribute("data-t", "14.0");

  // Chips: All 4, Scores, then each player in game order.
  const labels = await page.getByTestId("moment-filter").allTextContents();
  expect(labels).toEqual(["All 4", "Scores", "Marcus", "Player 2", "Player 3"]);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("moments-layer")).toHaveAttribute(
    "data-zone",
    "chips",
  );
  await expect(chip(page, "all")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter"); // Scores
  await expect(chip(page, "score")).toHaveAttribute("data-active", "true");
  await expect(cards(page)).toHaveCount(3);
  await expect(focusedCard(page)).toHaveAttribute("data-moment-id", "e_0003"); // same time kept
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter"); // Marcus
  await expect(cards(page)).toHaveCount(2);

  // Select jumps to the moment's start and closes the row.
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("moments-layer")).toHaveCount(0);
  await expect
    .poll(async () => (await media(page)).t)
    .toBeGreaterThanOrEqual(12.45);
  expect((await media(page)).t).toBeLessThan(14);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
});

test("TV-21 Back and Up close Moments; Up again opens Do more", async ({
  page,
}) => {
  await openWatch(page);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moments-layer")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("moments-layer")).toHaveCount(0);
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "false",
  );

  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp"); // cards → chips
  await page.keyboard.press("ArrowUp"); // chips → closed
  await expect(page.getByTestId("moments-layer")).toHaveCount(0);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("domore")).toBeVisible();
});

test("TV-21 a bookmark from Do more lands on the line and gets its own chip", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=10");
  await expect(page.getByTestId("moment-notch")).toHaveCount(4);
  await menuTo(page, "action-bookmark");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("toast")).toContainText("Bookmarked 0:1");
  await expect(
    page.locator('[data-testid="moment-notch"][data-kind="bookmark"]'),
  ).toHaveCount(1);
  await page.keyboard.press("ArrowDown");
  await expect(chip(page, "bookmark")).toHaveText("Your bookmarks");
  await expect(cards(page)).toHaveCount(5);
});
