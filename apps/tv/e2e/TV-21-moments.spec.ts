// The Moments layer (Down): moment cards above the court line cued to the nearest moment,
// Left/Right walk (the playhead follows), Select jumps and closes, one short row above
// (the title, the filters All N, Scores, Bookmarks, and "+ Bookmark m:ss"; no chip per
// player), Up to that row then Up closes, Back closes. Mock g_mock01: moments at 3
// (Basket, Marcus), 8 (Missed shot, p2), 14 (Basket, Marcus), 17 (Basket, p3); thumbs for
// all four.
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, media, openWatch } from "./helpers";

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

  // The row: its title, All 4 and Scores (no chip per player, no bookmarks yet), then the
  // bookmark action at the playhead the layer opened on.
  await expect(page.getByTestId("moments-title")).toHaveText("Moments");
  const labels = await page.getByTestId("moment-filter").allTextContents();
  expect(labels).toEqual(["All 4", "Scores"]);
  await expect(page.getByTestId("moment-bookmark")).toHaveText(
    /^\+ Bookmark 0:0[78]$/,
  );
  // the legend: Select Play, ▼ Angles only when the focused card has them, Back Close
  const legend = page.getByTestId("key-legend");
  await expect(legend).toBeVisible();
  const angles = await focusedCard(page).getAttribute("data-angles");
  await expect(page.getByTestId("legend-▼")).toHaveCount(
    angles === "true" ? 1 : 0,
  );
  await expect(page.getByTestId("legend-Select")).toHaveAttribute(
    "data-label",
    "Play",
  );
  await expect(page.getByTestId("legend-Back")).toHaveAttribute(
    "data-label",
    "Close",
  );
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
  await expect(chip(page, "score")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Enter"); // All 4
  await expect(chip(page, "all")).toHaveAttribute("data-active", "true");
  await expect(cards(page)).toHaveCount(4);
  await expect(focusedCard(page)).toHaveAttribute("data-moment-id", "e_0003");

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

test("TV-21 + Bookmark in the Moments row saves the time shown, closes, and gets a Bookmarks filter", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=10");
  await expect(page.getByTestId("moment-notch")).toHaveCount(4);
  await page.keyboard.press("Space"); // paused: the time on the chip stays put
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moments-layer")).toBeVisible();
  const mark = page.getByTestId("moment-bookmark");
  const label = (await mark.textContent()) ?? "";
  expect(label).toMatch(/^\+ Bookmark 0:1\d$/);
  await page.keyboard.press("ArrowUp"); // to the row
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight"); // the end holds
  await expect(mark).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("legend-Select")).toHaveAttribute(
    "data-label",
    "Choose",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("moments-layer")).toHaveCount(0);
  await expect(page.getByTestId("toast")).toContainText(
    `Bookmarked ${label.replace("+ Bookmark ", "")}`,
  );
  await expect(
    page.locator('[data-testid="moment-notch"][data-kind="bookmark"]'),
  ).toHaveCount(1);
  await page.keyboard.press("ArrowDown");
  await expect(chip(page, "bookmark")).toHaveText("Bookmarks");
  await expect(cards(page)).toHaveCount(5);
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight"); // All 5 → Scores → Bookmarks
  await page.keyboard.press("Enter");
  await expect(cards(page)).toHaveCount(1);
  await expect(cards(page).first()).toHaveAttribute("data-kind", "bookmark");
});

/** Arrow keydowns sent in one task, before React re-renders: a held remote on a slow Fire
 *  TV (JS repeat every 120 ms, a render longer than that) delivers keys like this. */
const burst = (page: Page, key: string, n: number) =>
  page.evaluate(
    ([k, count]) => {
      for (let i = 0; i < count; i++)
        window.dispatchEvent(new KeyboardEvent("keydown", { key: k }));
    },
    [key, n] as const,
  );

test("TV-21 keys faster than a render all count: cards and chips", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=2.5");
  await page.keyboard.press("Space");
  await page.keyboard.press("ArrowDown");
  await expect(focusedCard(page)).toHaveAttribute("data-moment-id", "e_0001");
  await burst(page, "ArrowRight", 2);
  await expect(focusedCard(page)).toHaveAttribute("data-moment-id", "e_0003");
  await burst(page, "ArrowLeft", 2);
  await expect(focusedCard(page)).toHaveAttribute("data-moment-id", "e_0001");
  await page.keyboard.press("ArrowUp");
  await burst(page, "ArrowRight", 2); // All 4 → Scores → + Bookmark
  await expect(page.getByTestId("moment-bookmark")).toHaveAttribute(
    "data-focused",
    "true",
  );
});
