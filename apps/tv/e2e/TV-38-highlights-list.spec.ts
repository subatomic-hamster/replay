// TV-38 the Highlights list: Home → Highlights opens a row of the reel's plays in game
// order over the paused game, "Play all" first; the best play's card carries "★ Best
// play"; Select plays that one play in the player (the best play under its banner), Back
// comes back to the list on the same card, and Back from the list goes Home. Play all is
// the reel. SYNTHETIC mock g_mock01 (20 s): hype plays 0.5–4.5 s (the 3 s basket, Marcus)
// and 11.5–15.5 s; the game winner (17 s, p3) joins the second: 11.5–18.5 s (TV-37).
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, media, smallText } from "./helpers";

const cards = (page: Page) => page.getByTestId("highlight-card");

async function openList(page: Page) {
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
  await expect(page.getByTestId("highlights-layer")).toBeVisible();
}

test("TV-38 Home → Highlights lists the plays; Select plays one, Back returns", async ({
  page,
}) => {
  await openList(page);
  await expect(page.getByTestId("highlights-title")).toHaveText(
    "Highlights · 2 plays",
  );
  await expect(page.getByTestId("context-chip")).toContainText("Highlights");
  // Play all, then the plays in game order; nothing plays under the list
  await expect(cards(page)).toHaveCount(3);
  await expect(cards(page).nth(0)).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("highlights-play-all")).toBeVisible();
  await expect(cards(page).nth(1)).toHaveAttribute("data-t", "3");
  await expect(cards(page).nth(1)).toHaveAttribute("data-best", "false");
  await expect(cards(page).nth(2)).toHaveAttribute("data-t", "17");
  await expect(cards(page).nth(2)).toHaveAttribute("data-best", "true");
  await expect(page.getByTestId("highlight-best")).toHaveCount(1);
  await expect(cards(page).nth(2)).toContainText("★ Best play");
  await expect(cards(page).nth(2)).toContainText("0:17");
  const labels = page.getByTestId("highlight-label");
  await expect(labels.nth(0)).toHaveText("Play all");
  await expect(labels.nth(1)).toHaveText("Basket, Marcus");
  await expect(page.getByTestId("key-legend")).toContainText("Home");
  expect(await smallText(page)).toEqual([]);
  expect((await media(page)).paused).toBe(true);
  await page.screenshot({ path: test.info().outputPath("highlights.png") });

  // the remote walks the row, stopping at each end
  await page.keyboard.press("ArrowLeft");
  await expect(cards(page).nth(0)).toHaveAttribute("data-focused", "true");
  for (let k = 0; k < 4; k++) await page.keyboard.press("ArrowRight");
  await expect(cards(page).nth(2)).toHaveAttribute("data-focused", "true");

  // the best play, alone, in the player under its banner
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("highlights-layer")).toHaveCount(0);
  const ind = page.getByTestId("way-indicator");
  await expect(ind).toHaveAttribute("data-count", "1");
  await expect(page.getByTestId("best-play-card")).toBeVisible();
  await expect
    .poll(async () => (await media(page)).t, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(11.4);
  await expect.poll(async () => (await media(page)).paused).toBe(false);

  // Back: the list again, on the card just played, the game paused
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("highlights-layer")).toBeVisible();
  await expect(cards(page).nth(2)).toHaveAttribute("data-focused", "true");
  await expect.poll(async () => (await media(page)).paused).toBe(true);

  // the first play: its own name on the chip, no banner
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Enter");
  await expect(ind).toHaveText("Basket, Marcus");
  await expect(page.getByTestId("best-play-card")).toHaveCount(0);
  await expect
    .poll(async () => (await media(page)).t, { timeout: 15_000 })
    .toBeGreaterThan(0.4);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("highlights-layer")).toBeVisible();

  // Back from the list: Home
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("home")).toBeVisible();
});

test("TV-38 Play all is the Highlights reel, ending on the best play", async ({
  page,
}) => {
  await openList(page);
  await expect(cards(page)).toHaveCount(3);
  await page.keyboard.press("Enter"); // Play all is focused
  const ind = page.getByTestId("way-indicator");
  await expect(ind).toHaveText("Highlights · 1 of 2");
  await page.keyboard.press("]");
  await expect(ind).toHaveText("Highlights · 2 of 2");
  await expect(page.getByTestId("best-play-card")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("highlights-layer")).toBeVisible();
  await expect(cards(page).nth(0)).toHaveAttribute("data-focused", "true");
});
