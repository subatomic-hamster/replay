// M13 rally browser + condensed game (D-46). Mock fixture: g_pickle4 has three rallies
// (r2 the longest) and no condensed render until it is asked for; g_mock01 has none, so
// its Watch screen has no Rallies item (data-driven, never a sport-name branch).
import { expect, test, type Page } from "@playwright/test";
import { menuTo, mockCalls, openWatch } from "./helpers";

async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v
      ? { t: v.currentTime, paused: v.paused, src: v.currentSrc, ready: v.readyState }
      : { t: -1, paused: true, src: "", ready: 0 };
  });
}

test("TV-12 Rallies shows only for a game with rallies", async ({ page }) => {
  await openWatch(page);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("nav-rallies")).toHaveCount(0);

  await openWatch(page, "g_pickle4");
  await menuTo(page, "nav-rallies");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("rallies")).toBeVisible();
  await expect(page.getByTestId("rally-row")).toHaveCount(3);
  await expect(page.getByTestId("rally-summary")).toContainText("3 rallies · 16 s of play");
});

test("TV-12 longest rallies first; Select plays one with the rally counter, pausing at its end", async ({ page }) => {
  await page.goto("/tv/g_pickle4/rallies");
  const rows = page.getByTestId("rally-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toHaveAttribute("data-rally-id", "r1");
  await page.keyboard.press("ArrowRight"); // Longest
  await expect(page.getByTestId("rally-tab-longest")).toHaveAttribute("data-focused", "true");
  await expect(rows.nth(0)).toHaveAttribute("data-rally-id", "r2");
  await expect(rows.nth(2)).toHaveAttribute("data-rally-id", "r3");

  await page.keyboard.press("ArrowDown");
  await expect(rows.nth(0)).toHaveAttribute("data-focused", "true");
  await expect.poll(async () => (await media(page)).ready, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page)).t).toBeGreaterThan(8);
  await expect(page.getByTestId("rally-counter")).toHaveText("RALLY 2 / 3 · 11 SHOTS · 9 S");
  // A rally stops at its own end instead of running into the next one (r3: 17–19.5 s).
  await page.goto("/tv/g_pickle4/rallies");
  await expect(rows).toHaveCount(3);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight"); // r3 (game order)
  await expect.poll(async () => (await media(page)).ready, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("rally-counter")).toHaveText("RALLY 3 / 3 · 3 S"); // shots unknown: omitted
  await expect.poll(async () => (await media(page)).paused, { timeout: 8_000 }).toBe(true);
  const t = (await media(page)).t;
  expect(t).toBeGreaterThanOrEqual(19.4);
  expect(t).toBeLessThan(20);
});

test("TV-12 condensed game: render on request, then play it with the counter in sync", async ({ page }) => {
  await page.goto("/tv/g_pickle4/rallies");
  await expect(page.getByTestId("rally-row")).toHaveCount(3);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("rally-tab-condensed")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("condensed-status")).toHaveAttribute("data-status", "none");

  await page.keyboard.press("Enter");
  expect((await mockCalls(page)).some((c) => c.method === "POST" && c.path === "/games/g_pickle4/condensed")).toBe(true);
  await expect(page.getByTestId("rallies")).toHaveAttribute("data-condensed", "true", { timeout: 5_000 });
  await expect.poll(async () => (await media(page)).src).toContain("rendition=condensed");

  // Rallies in game order on this tab; Select on r2 seeks to its offset in the condensed video.
  await expect.poll(async () => (await media(page)).ready, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page)).t).toBeGreaterThan(6.4);
  await expect(page.getByTestId("rally-counter")).toHaveAttribute("data-rally", "r2");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  // no stop at the rally's end on the condensed video: the next rally follows
  await expect(page.getByTestId("rally-counter")).toHaveAttribute("data-rally", "r3", { timeout: 15_000 });
});
