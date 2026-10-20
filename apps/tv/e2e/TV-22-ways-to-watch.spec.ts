// Ways to watch (Full game, Highlights, Condensed), chosen on Home's hero or from Do more →
// Watch, and a game still processing: watchable at once, its pending features saying when
// they will be ready. Mock g_mock01 hype candidates: 3.5 s (0.80) and 14.5 s (0.95), each
// played from 3 s before to 1 s after; g_proc03 is processing with its video ingested.
import { expect, test } from "@playwright/test";
import { GAME_ID, media, menuTo, openWatch } from "./helpers";

test("TV-22 Home → Highlights plays the top plays back to back with an indicator", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.locator(`[data-testid="game-card"][data-game-id="${GAME_ID}"]`),
  ).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowUp"); // the hero's ways to watch
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("hero-highlights")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");

  const ind = page.getByTestId("way-indicator");
  await expect(ind).toHaveText("Highlights, 1 of 2");
  await expect(ind).toHaveAttribute("data-way", "highlights");
  await expect
    .poll(async () => (await media(page)).t, { timeout: 15_000 })
    .toBeGreaterThan(0.5);
  // 4.5 s: the first play ends, the second starts at 11.5 s.
  await expect(ind).toHaveText("Highlights, 2 of 2", { timeout: 10_000 });
  expect((await media(page)).t).toBeGreaterThanOrEqual(11.4);
  // After the last play (15.5 s) the full game takes over, paused, transport up.
  await expect(ind).toHaveCount(0, { timeout: 10_000 });
  await expect(page.getByTestId("watch")).toHaveAttribute("data-way", "full");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "false",
  );
});

test("TV-22 Do more → Watch switches ways; Back leaves the Watch row first", async ({
  page,
}) => {
  await openWatch(page);
  await menuTo(page, "menu-watch");
  await expect(page.getByTestId("menu-watch")).toContainText("Full game");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toHaveAttribute(
    "data-row",
    "menu-watch",
  );
  await expect(page.getByTestId("way-full")).toHaveAttribute("data-on", "true");
  await expect(page.getByTestId("way-full")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await expect(page.getByTestId("way-highlights")).toContainText("Top 2 plays");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("domore")).toHaveAttribute("data-row", "main");

  await menuTo(page, "way-highlights");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toHaveCount(0);
  await expect(page.getByTestId("way-indicator")).toHaveText(
    "Highlights, 1 of 2",
  );
  // Next goes to the next play of the reel.
  await page.keyboard.press("]");
  await expect(page.getByTestId("way-indicator")).toHaveText(
    "Highlights, 2 of 2",
  );
  await expect
    .poll(async () => (await media(page)).t)
    .toBeGreaterThanOrEqual(11.4);

  await menuTo(page, "way-full");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("way-indicator")).toHaveCount(0);
  await expect(page.getByTestId("watch")).toHaveAttribute("data-way", "full");
});

test("TV-22 a processing game plays now; pending features say when they will be ready", async ({
  page,
}) => {
  await page.goto("/");
  const card = page.locator(
    '[data-testid="game-card"][data-game-id="g_proc03"]',
  );
  await expect(
    page.locator(`[data-testid="game-card"][data-game-id="${GAME_ID}"]`),
  ).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowLeft"); // the processing game sits before the newest
  await expect(card).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("watch")).toBeVisible();
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
  await expect.poll(async () => (await media(page)).paused).toBe(false);

  await page.keyboard.press("ArrowUp");
  const follow = page.getByTestId("action-follow");
  await expect(follow).toHaveAttribute("data-pending", "true");
  await expect(follow).toContainText(
    /Getting ready, (about\s\d+\smin|under\sa\sminute)/,
  );
  await expect(page.getByTestId("nav-review")).toHaveAttribute(
    "data-pending",
    "true",
  );
  await page.keyboard.press("Enter"); // not selectable: nothing happens
  await expect(page.getByTestId("domore")).toBeVisible();
  await expect(page.getByTestId("watch")).toHaveAttribute("data-mode", "wide");
  await page.keyboard.press("Escape");

  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moments-empty")).toContainText(
    "Finding the big moments, about",
  );
});
