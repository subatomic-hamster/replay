// M13 Watch on the web TV: broadcast mode (M6 rendition, with sound, same media time),
// commentary captions synced to media time (M7), the hype meter on the scrubber and
// jump-to-peak (D-45). Mock fixture: g_mock01 has a broadcast rendition
// (wide.mp4?rendition=broadcast), a commentary script and hype peaks at 3.5 s and 14.5 s;
// g_pickle4 has no broadcast and g_mock02 no hype candidates.
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, NET_GAME_ID, menuTo, openWatch } from "./helpers";

async function media(page: Page) {
  return page.evaluate(() => {
    const el = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return el
      ? { t: el.currentTime, paused: el.paused, src: el.currentSrc, ready: el.readyState, muted: el.muted }
      : { t: -1, paused: true, src: "", ready: 0, muted: true };
  });
}

test("S-40 Broadcast swaps to the broadcast rendition at the same media time, with sound", async ({
  page,
}) => {
  await openWatch(page);
  await page.keyboard.press("Space"); // play
  await expect.poll(async () => (await media(page)).t, { timeout: 10_000 }).toBeGreaterThan(1.5);

  await menuTo(page, "action-broadcast");
  const before = (await media(page)).t;
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("watch")).toHaveAttribute("data-broadcast", "true");
  await expect(page.getByTestId("action-broadcast")).toHaveAttribute("data-on", "true");
  await expect(page.getByTestId("mode-pill")).toHaveText("BROADCAST");
  await expect(page.getByTestId("court-inset")).toHaveCount(0);
  await expect
    .poll(async () => {
      const m = await media(page);
      return m.src.includes("rendition=broadcast") && m.ready >= 2;
    })
    .toBe(true);
  const after = await media(page);
  expect(after.t).toBeGreaterThan(before - 0.1); // resumed where the wide shot was
  expect(after.t).toBeLessThan(before + 3);
  expect(after.muted).toBe(false); // the broadcast mix plays with sound
  await expect.poll(async () => (await media(page)).paused).toBe(false);

  // Pausing over the broadcast does not open select mode (boxes describe the wide frame).
  await page.keyboard.press("ArrowDown"); // close the row
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await expect(page.getByTestId("watch")).toHaveAttribute("data-mode", "wide");
  await page.keyboard.press("Space");

  // Broadcast off: back to the muted wide shot, still at the same place.
  await menuTo(page, "action-broadcast");
  const t1 = (await media(page)).t;
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("watch")).toHaveAttribute("data-broadcast", "false");
  await expect.poll(async () => (await media(page)).src).toMatch(/\/mock\/wide\.mp4$/);
  await expect.poll(async () => (await media(page)).ready).toBeGreaterThanOrEqual(2);
  expect((await media(page)).t).toBeGreaterThan(t1 - 0.1);
  expect((await media(page)).muted).toBe(true);
});

test("S-40 no broadcast rendition: no Broadcast item, the game plays wide", async ({ page }) => {
  await openWatch(page, NET_GAME_ID);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("nav-search")).toBeAttached(); // the row has loaded
  await expect(page.getByTestId("action-broadcast")).toHaveCount(0);
  await expect(page.getByTestId("watch")).toHaveAttribute("data-broadcast", "false");
  expect((await media(page)).src).toMatch(/\/mock\/wide\.mp4$/);
});

test("S-41 Commentary captions follow media time", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}?t=3.2`);
  await expect.poll(async () => (await media(page)).t, { timeout: 15_000 }).toBeGreaterThan(3.1);
  await expect(page.getByTestId("caption")).toHaveCount(0); // off by default

  await menuTo(page, "action-captions");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("action-captions")).toHaveAttribute("data-on", "true");
  await expect(page.getByTestId("caption")).toHaveText("Marcus scores two.");

  await page.keyboard.press("ArrowDown"); // close the row
  await page.keyboard.press("ArrowRight"); // scrub +5 s → 8.2 s
  await expect.poll(async () => (await media(page)).t).toBeGreaterThan(8);
  await expect(page.getByTestId("caption")).toHaveText("Player 2 shoots, no good.");
  await page.keyboard.press("ArrowRight"); // 13.2 s: between lines
  await expect(page.getByTestId("caption")).toHaveCount(0);
});

test("S-42 hype meter on the scrubber; Hype peak jumps to each peak's lead-in", async ({ page }) => {
  await openWatch(page);
  const meter = page.getByTestId("hype-meter");
  await expect(meter).toHaveAttribute("data-bars", "96");
  const values = await page
    .getByTestId("hype-bar")
    .evaluateAll((els) => els.map((e) => Number(e.getAttribute("data-value"))));
  const peak = values.indexOf(Math.max(...values));
  expect(Math.abs(((peak + 0.5) / values.length) * 20 - 14.5)).toBeLessThan(0.5); // the 14.5 s peak

  await menuTo(page, "action-hype-peak");
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page)).t).toBeCloseTo(0.5, 1);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page)).t).toBeCloseTo(11.5, 1);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page)).t).toBeCloseTo(0.5, 1); // wraps

  // A game with no candidates hides the item.
  await openWatch(page, "g_mock02");
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-search")).toBeAttached();
  await expect(page.getByTestId("action-hype-peak")).toHaveCount(0);
});
